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

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Memory CLI commands (Phase 7c — REQ-040 through REQ-042)
# ---------------------------------------------------------------------------

# Chat-log line pattern (salvaged from factfinder.py prototype)
_LINE_RE = re.compile(
    r"^\[(?P<time>[^\]]+)\]\s+"
    r"(?:\[(?P<channel>[^\]]+)\]\s+)?"
    r"<(?P<user>[^>]+)>\s+"
    r"(?P<msg>.+)$"
)
# Server alias / status lines to ignore
_SERVER_RE = re.compile(r"^\[(?:[^\]]+)\]\s+\*\*\*")


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
            continue

        # Group by user
        by_user: dict[str, list[dict]] = {}
        for msg in messages:
            by_user.setdefault(msg["username"], []).append(msg)

        for user, user_msgs in by_user.items():
            users_processed.add(user)
            facts = await extractor.extract(user_msgs, user)

            for fact in facts:
                # Safety gate
                if not is_safe_message(fact.summary):
                    total_skipped_safety += 1
                    continue

                # Mark as seeded
                fact.source = "seed"
                fact.evidence["log_file"] = str(log_path.name)

                if not args.dry_run:
                    # Embed + upsert one at a time (simpler for CLI; batch in future)
                    vectors = await embedder.embed([fact.summary])
                    if vectors:
                        from datetime import datetime, timezone

                        now = datetime.now(timezone.utc).isoformat()
                        await vector_store.upsert(
                            ids=[stable_fact_id(fact.user, fact.summary)],
                            vectors=vectors,
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
                        total_written += 1
                else:
                    logger.info(
                        f"[dry-run] Would store: [{fact.category}] {fact.summary} "
                        f"(user={fact.user}, score={fact.score:.1f})"
                    )
                    total_written += 1

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
        else:
            print("Usage: kryten-llm memory {seed|forget|stats} [options]")
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
