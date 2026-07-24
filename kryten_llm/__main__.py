"""Main entry point for kryten-llm service."""

import argparse
import asyncio
import logging
import platform
import re
import signal
import sys
from pathlib import Path
from typing import Callable

from kryten_llm.components import ConfigReloader
from kryten_llm.config import load_config, validate_config_file
from kryten_llm.service import LLMService


def setup_logging(level: str = "INFO") -> None:
    """Configure logging for the service."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Kryten LLM Service - AI-powered chat bot for CyTube"
    )
    parser.add_argument(
        "--config", type=Path, default=Path("config.json"), help="Path to configuration file"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Generate responses but don't send to chat"
    )
    parser.add_argument(
        "--validate-config", action="store_true", help="Validate configuration file and exit"
    )

    # Phase 7: memory subcommand
    subparsers = parser.add_subparsers(dest="subcommand")

    mem_parser = subparsers.add_parser("memory", help="Long-term memory management commands")
    mem_sub = mem_parser.add_subparsers(dest="memory_cmd")

    seed_p = mem_sub.add_parser("seed", help="Seed long-term memory from historical chat logs")
    seed_p.add_argument(
        "--logs",
        required=True,
        metavar="GLOB",
        help="Glob pattern matching log files to process (e.g. 'logs/*.log')",
    )
    seed_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract facts but do not write them to the store",
    )

    forget_p = mem_sub.add_parser("forget", help="Delete all stored facts for a user")
    forget_p.add_argument("user", help="Username whose facts should be deleted")

    mem_sub.add_parser("stats", help="Show long-term memory statistics")

    recall_p = mem_sub.add_parser(
        "recall", help="Show facts that would be surfaced for a user given a query"
    )
    recall_p.add_argument("--user", required=True, help="Username to retrieve facts for")
    recall_p.add_argument(
        "--query",
        default=None,
        metavar="TEXT",
        help="Query text to embed (defaults to the username itself)",
    )
    recall_p.add_argument(
        "--top-k", type=int, default=10, help="Maximum facts to return (default: 10)"
    )
    recall_p.add_argument(
        "--min-similarity",
        type=float,
        default=None,
        help="Minimum similarity threshold 0-1 (default: from config)",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Memory CLI commands (Phase 7c — REQ-040 through REQ-042)
# ---------------------------------------------------------------------------

# Chat-log line pattern: "HH:MM:SS <username>: message"
_LINE_RE = re.compile(r"^(?P<time>\d{2}:\d{2}:\d{2})\s+" r"<(?P<user>[^>]+)>:\s*" r"(?P<msg>.+)$")
# Server / status lines to ignore: "HH:MM:SS <[server]>: ..." or "HH:MM:SS ***"
_SERVER_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\s+(?:<\[[^\]]+\]>|(?:\*\*\*))")


def _parse_log_file(path: Path) -> list[dict]:
    """Parse a single chat log file and return ``[{"username", "message", "time"}]``."""
    messages = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if _SERVER_RE.match(line):
                continue
            m = _LINE_RE.match(line)
            if m:
                messages.append(
                    {
                        "username": m.group("user").strip(),
                        "message": m.group("msg").strip(),
                        "time": m.group("time").strip(),
                    }
                )
    except Exception as exc:
        logging.getLogger(__name__).warning(f"Could not parse log file {path}: {exc}")
    return messages


async def cmd_memory_seed(args: argparse.Namespace, config) -> None:
    """Bulk-import facts from historical chat logs (REQ-040, REQ-041, GUD-003)."""
    import glob as _glob

    logger = logging.getLogger(__name__)

    # Locate matching files
    log_files = sorted(Path(p) for p in _glob.glob(args.logs, recursive=True))
    if not log_files:
        logger.error(f"No files matched glob: {args.logs}")
        sys.exit(1)

    logger.info(f"Found {len(log_files)} log file(s)")

    # Build LTM provider from config
    provider_cfg = _find_ltm_provider_cfg(config)
    if provider_cfg is None:
        logger.error(
            "No 'long_term_memory' provider found in config.context.providers. "
            "Add and enable the provider before seeding."
        )
        sys.exit(1)

    from kryten_llm.components.memory.embedder import build_embedder
    from kryten_llm.components.memory.heuristic_extractor import (
        HeuristicFactExtractor,
        stable_fact_id,
    )
    from kryten_llm.components.memory.safety import is_safe_message
    from kryten_llm.components.memory.vector_store import build_vector_store

    emb_cfg = provider_cfg.get("embedder", {"type": "onnx", "model": "all-MiniLM-L6-v2"})
    embedder = build_embedder(emb_cfg)

    store_cfg = provider_cfg.get(
        "store", {"backend": "chroma", "path": "./data/chroma", "collection": "user_facts"}
    )
    vector_store = build_vector_store(
        store_cfg,
        embedder_id=embedder.id,
        dimension=getattr(embedder, "dimension", 0),
    )

    write_cfg = provider_cfg.get("write", {})
    extractor = HeuristicFactExtractor(min_score=write_cfg.get("min_message_score", 25.0))

    # Process each file
    users_processed: set[str] = set()
    total_written = 0
    total_skipped_safety = 0
    total_skipped_score = 0

    for log_path in log_files:
        messages = _parse_log_file(log_path)
        if not messages:
            logger.warning(f"No parseable messages in {log_path}")
            continue

        # Group by user
        by_user: dict[str, list[dict]] = {}
        for msg in messages:
            by_user.setdefault(msg["username"], []).append(msg)

        print(f"\nProcessing {log_path.name} — {len(messages):,} messages, {len(by_user):,} users")

        for user, user_msgs in by_user.items():
            users_processed.add(user)
            facts = await extractor.extract(user_msgs, user)

            # Filter to safe facts first
            safe_facts = []
            for fact in facts:
                if not is_safe_message(fact.summary):
                    total_skipped_safety += 1
                    continue
                fact.source = "seed"
                fact.evidence["log_file"] = str(log_path.name)
                safe_facts.append(fact)

            if not safe_facts:
                continue

            if not args.dry_run:
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc).isoformat()
                # Batch embed all facts for this user in a single call
                summaries = [f.summary for f in safe_facts]
                all_vectors = await embedder.embed(summaries)
                for fact, vector in zip(safe_facts, all_vectors):
                    await vector_store.upsert(
                        ids=[stable_fact_id(fact.user, fact.summary)],
                        vectors=[vector],
                        metadatas=[
                            {
                                "user": fact.user,
                                "category": fact.category,
                                "source": "seed",
                                "created_at": now,
                                "score": fact.score,
                                "evidence": str(fact.evidence.get("message", ""))[:200],
                            }
                        ],
                        documents=[fact.summary],
                    )
                total_written += len(safe_facts)
                print(f"  {user}: {len(safe_facts)} fact(s) written")
            else:
                for fact in safe_facts:
                    logger.info(
                        f"[dry-run] Would store: [{fact.category}] {fact.summary} "
                        f"(user={fact.user}, score={fact.score:.1f})"
                    )
                total_written += len(safe_facts)
                print(f"  {user}: {len(safe_facts)} fact(s) (dry run)")

    # GUD-003: Summary output
    print(
        f"\nSeeding {'(dry run) ' if args.dry_run else ''}complete:\n"
        f"  Users processed : {len(users_processed)}\n"
        f"  Facts written   : {total_written}\n"
        f"  Skipped (safety): {total_skipped_safety}\n"
        f"  Skipped (score) : {total_skipped_score}"
    )


async def cmd_memory_forget(args: argparse.Namespace, config) -> None:
    """Delete all facts for a user (CON-003, REQ-042)."""
    logger = logging.getLogger(__name__)
    provider_cfg = _find_ltm_provider_cfg(config)
    if provider_cfg is None:
        logger.error("No 'long_term_memory' provider found in config.")
        sys.exit(1)

    from kryten_llm.components.memory.embedder import build_embedder
    from kryten_llm.components.memory.vector_store import build_vector_store

    emb_cfg = provider_cfg.get("embedder", {"type": "onnx"})
    embedder = build_embedder(emb_cfg)
    store_cfg = provider_cfg.get(
        "store", {"backend": "chroma", "path": "./data/chroma", "collection": "user_facts"}
    )
    store = build_vector_store(
        store_cfg,
        embedder_id=embedder.id,
        dimension=getattr(embedder, "dimension", 0),
    )

    count_before = await store.count(where={"user": args.user})
    await store.delete(where={"user": args.user})
    print(f"Deleted {count_before} fact(s) for user '{args.user}'.")


async def cmd_memory_recall(args: argparse.Namespace, config) -> None:
    """Simulate the provider read path and show what facts would be surfaced."""
    from kryten_llm.components.memory.embedder import build_embedder
    from kryten_llm.components.memory.vector_store import build_vector_store

    provider_cfg = _find_ltm_provider_cfg(config)
    if provider_cfg is None:
        print("No 'long_term_memory' provider found in config.")
        sys.exit(1)

    emb_cfg = provider_cfg.get("embedder", {"type": "onnx", "model": "all-MiniLM-L6-v2"})
    embedder = build_embedder(emb_cfg)
    store_cfg = provider_cfg.get(
        "store", {"backend": "chroma", "path": "./data/chroma", "collection": "user_facts"}
    )
    store = build_vector_store(
        store_cfg,
        embedder_id=embedder.id,
        dimension=getattr(embedder, "dimension", 0),
    )

    query_text = args.query if args.query else args.user
    top_k = args.top_k
    min_sim = (
        args.min_similarity
        if args.min_similarity is not None
        else provider_cfg.get("min_similarity", 0.25)
    )
    max_distance = 1.0 - min_sim

    total_for_user = await store.count(where={"user": args.user})
    print(f"\nUser          : {args.user}")
    print(f"Query         : {query_text!r}")
    print(f"Stored facts  : {total_for_user}")
    print(
        f"top_k         : {top_k}  |  min_similarity: {min_sim}  (max_distance: {max_distance:.3f})"
    )

    vectors = await embedder.embed([query_text])
    if not vectors:
        print("Embedding failed — nothing to query.")
        return

    results = await store.query(vector=vectors[0], k=top_k, where={"user": args.user})
    if not results:
        print("\nNo results returned from vector store.")
        return

    filtered = [r for r in results if r.get("distance", 1.0) <= max_distance]
    excluded = [r for r in results if r.get("distance", 1.0) > max_distance]

    print(f"\nResults before similarity gate : {len(results)}")
    print(f"Passed gate (distance <= {max_distance:.3f}) : {len(filtered)}")
    if excluded:
        print(f"Excluded by gate               : {len(excluded)}")

    if filtered:
        print("\n-- Surfaced facts " + "-" * 38)
        for i, r in enumerate(filtered, 1):
            meta = r.get("metadata", {})
            dist = r.get("distance", float("nan"))
            sim = 1.0 - dist
            cat = meta.get("category", "?")
            score = meta.get("score", "?")
            doc = r.get("document", "")
            print(f"  {i:2}. sim={sim:.3f}  [{cat}]  score={score}")
            print(f"      {doc}")
    else:
        print("\nNo facts passed the similarity gate for this query.")
        if excluded:
            print("\n-- Closest excluded facts (distance > gate) " + "-" * 12)
            for i, r in enumerate(excluded[:5], 1):
                meta = r.get("metadata", {})
                dist = r.get("distance", float("nan"))
                sim = 1.0 - dist
                cat = meta.get("category", "?")
                doc = r.get("document", "")
                print(f"  {i:2}. sim={sim:.3f}  [{cat}]  {doc}")
            print("  (lower --min-similarity to include these)")


async def cmd_memory_stats(args: argparse.Namespace, config) -> None:
    """Print memory statistics (REQ-042)."""
    logger = logging.getLogger(__name__)
    provider_cfg = _find_ltm_provider_cfg(config)
    if provider_cfg is None:
        logger.error("No 'long_term_memory' provider found in config.")
        sys.exit(1)

    from kryten_llm.components.memory.embedder import build_embedder
    from kryten_llm.components.memory.vector_store import build_vector_store

    emb_cfg = provider_cfg.get("embedder", {"type": "onnx"})
    embedder = build_embedder(emb_cfg)
    store_cfg = provider_cfg.get(
        "store", {"backend": "chroma", "path": "./data/chroma", "collection": "user_facts"}
    )
    store = build_vector_store(
        store_cfg,
        embedder_id=embedder.id,
        dimension=getattr(embedder, "dimension", 0),
    )

    total = await store.count()
    print(f"Long-term memory stats:\n  Total facts: {total}")


def _find_ltm_provider_cfg(config) -> dict | None:
    """Return the long_term_memory provider config dict, or None."""
    providers = getattr(config.context, "providers", None) or []
    for p in providers:
        cfg = p if isinstance(p, dict) else (p.model_dump() if hasattr(p, "model_dump") else {})
        if cfg.get("type") == "long_term_memory":
            return cfg
    return None


# ---------------------------------------------------------------------------
# Service startup
# ---------------------------------------------------------------------------


async def main_async() -> None:
    """Main async entry point."""
    args = parse_args()
    setup_logging(args.log_level)

    logger = logging.getLogger(__name__)

    # Phase 7: memory subcommands
    if args.subcommand == "memory":
        try:
            config = load_config(args.config)
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            sys.exit(1)

        if args.memory_cmd == "seed":
            await cmd_memory_seed(args, config)
        elif args.memory_cmd == "forget":
            await cmd_memory_forget(args, config)
        elif args.memory_cmd == "stats":
            await cmd_memory_stats(args, config)
        elif args.memory_cmd == "recall":
            await cmd_memory_recall(args, config)
        else:
            print("Usage: kryten-llm memory {seed|forget|recall|stats} [options]")
            sys.exit(1)
        return

    # Validate config mode
    if args.validate_config:
        logger.info(f"Validating configuration: {args.config}")
        is_valid, errors = validate_config_file(args.config)

        if is_valid:
            logger.info("✓ Configuration is valid")
            sys.exit(0)
        else:
            logger.error("✗ Configuration validation failed:")
            for error in errors:
                logger.error(f"  {error}")
            sys.exit(1)

    # Load configuration
    try:
        config = load_config(args.config)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

    # Override dry-run from CLI
    if args.dry_run:
        config.testing.dry_run = True
        config.testing.send_to_chat = False
        logger.info("Dry-run mode enabled via --dry-run flag")

    logger.info("Starting Kryten LLM Service")

    # Initialize service
    service = LLMService(config=config)

    # Phase 6: Setup config reloader for hot-reload support
    config_reloader = ConfigReloader(
        config_path=args.config, on_reload=service.reload_config, current_config=config
    )
    service.set_config_reload_callback(config_reloader.reload_config)

    # Setup signal handlers
    loop = asyncio.get_event_loop()

    def signal_handler(sig: int) -> None:
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(service.stop())

    # add_signal_handler is not supported on Windows, use signal.signal instead
    if platform.system() != "Windows":
        for sig in (signal.SIGTERM, signal.SIGINT):

            def _make_handler(sig_num: int) -> Callable[[], None]:
                return lambda: signal_handler(sig_num)

            loop.add_signal_handler(sig, _make_handler(sig))

        # Phase 6: Setup SIGHUP handler for config reload (POSIX only)
        if hasattr(signal, "SIGHUP"):

            def sighup_handler() -> None:
                logger.info("Received SIGHUP, reloading configuration...")
                asyncio.create_task(config_reloader.reload_config())

            loop.add_signal_handler(signal.SIGHUP, sighup_handler)
            logger.info("SIGHUP handler registered for config hot-reload")
    else:
        # Windows: Use signal.signal() for SIGINT/SIGTERM
        def _signal_handler(sig_num: int, frame) -> None:
            signal_handler(sig_num)

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
        logger.info("Signal handlers registered (Windows mode)")

    try:
        await service.start()
        await service.wait_for_shutdown()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Service error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await service.stop()


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
