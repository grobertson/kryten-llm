"""Main entry point for kryten-llm service."""

import argparse
import asyncio
import json
import logging
import os
import platform
import re
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

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


def _add_log_level(parser: argparse.ArgumentParser) -> None:
    """Add --log-level to *parser* using SUPPRESS as default.

    SUPPRESS means the attribute is only written when the flag is explicitly
    given, so it will never overwrite a value already set by a parent parser.
    """
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=argparse.SUPPRESS,
        help="Logging level (overrides a value set on any parent command)",
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
    _add_log_level(mem_parser)
    mem_sub = mem_parser.add_subparsers(dest="memory_cmd")

    seed_p = mem_sub.add_parser("seed", help="Seed long-term memory from historical chat logs")
    _add_log_level(seed_p)
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
    seed_p.add_argument(
        "--log-end-date",
        metavar="YYYY-MM-DD",
        default=None,
        help=(
            "Explicit end-date anchor for midnight-crossing detection (Sprint 20.5, REQ-457). "
            "Overrides file mtime. Use when the log file is still being written to."
        ),
    )
    seed_p.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Path to checkpoint file for stop/resume support (Sprint 25, REQ-501). "
            "Created after each batch; ignored when absent."
        ),
    )
    seed_p.add_argument(
        "--resume",
        action="store_true",
        help="Resume from an existing --checkpoint file, skipping already-completed batches",
    )
    seed_p.add_argument(
        "--reset-checkpoint",
        action="store_true",
        dest="reset_checkpoint",
        help="Delete the --checkpoint file and start seeding from scratch",
    )
    seed_p.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Number of concurrent LLM extraction workers (Sprint 25, REQ-510). "
            "Default 1 (sequential). Recommended max: 8."
        ),
    )

    forget_p = mem_sub.add_parser("forget", help="Delete all stored facts for a user")
    _add_log_level(forget_p)
    forget_p.add_argument("user", help="Username whose facts should be deleted")

    stats_p = mem_sub.add_parser("stats", help="Show long-term memory statistics")
    _add_log_level(stats_p)

    recall_p = mem_sub.add_parser(
        "recall", help="Show facts that would be surfaced for a user given a query"
    )
    _add_log_level(recall_p)
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

    # Sprint 12: memory eval subcommand (REQ-270–274)
    eval_p = mem_sub.add_parser(
        "eval", help="Run memory-quality evaluation suite (no live services needed)"
    )
    _add_log_level(eval_p)
    eval_p.add_argument(
        "--fixture-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="Directory containing eval fixture JSONL files (default: tests/eval/fixtures)",
    )
    eval_p.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit machine-readable JSON instead of a Markdown table (REQ-274)",
    )

    # Sprint 19: memory compact subcommand (REQ-390–394)
    compact_p = mem_sub.add_parser(
        "compact", help="Merge near-duplicate facts in the memory store (Sprint 19)"
    )
    _add_log_level(compact_p)
    compact_p.add_argument("--user", default=None, help="Compact only this user's facts")
    compact_p.add_argument(
        "--dry-run", action="store_true", help="Show what would be merged without writing"
    )
    compact_p.add_argument(
        "--threshold",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Override merge_threshold for this run (default: from config, 0.85)",
    )

    # Sprint 20, Sortie 3: backfill-last-seen subcommand (REQ-415–419)
    backfill_p = mem_sub.add_parser(
        "backfill-last-seen",
        help="Set last_seen=created_at for facts that are missing last_seen (Sprint 20)",
    )
    _add_log_level(backfill_p)
    backfill_p.add_argument(
        "--dry-run", action="store_true", help="Report what would be backfilled without writing"
    )

    # Sprint 20.5, Sortie 3: memory reset subcommand (REQ-459)
    reset_p = mem_sub.add_parser(
        "reset", help="Delete all facts from the memory store (irreversible without backup)"
    )
    _add_log_level(reset_p)
    reset_p.add_argument(
        "--confirm",
        action="store_true",
        help="Required to actually delete. Without this flag only the count is shown.",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Memory CLI commands (Phase 7c — REQ-040 through REQ-042)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Seed progress tracker
# ---------------------------------------------------------------------------


class _SeedProgress:
    """Time-aware progress reporter for the memory seed command.

    Emits a single log line every REPORT_INTERVAL seconds showing global
    read/remaining counts, elapsed time, ETA, and the log date currently
    being consumed.
    """

    REPORT_INTERVAL: float = 10.0  # seconds between automatic reports

    def __init__(self, total_messages: int) -> None:
        self.total = total_messages
        self.done = 0
        self._start = time.monotonic()
        # Initialise to (now - interval) so the first qualifying report fires
        # immediately after REPORT_INTERVAL seconds of real work.
        self._last_report: float = self._start

    def advance(self, n: int) -> None:
        """Record *n* messages as processed."""
        self.done += n

    def should_report(self) -> bool:
        """Return True (and reset the clock) if it is time to emit a line."""
        now = time.monotonic()
        if now - self._last_report >= self.REPORT_INTERVAL:
            self._last_report = now
            return True
        return False

    def format(self, log_date: str | None = None) -> str:
        """Return a human-readable progress string."""
        elapsed = time.monotonic() - self._start
        remaining = self.total - self.done
        pct = 100.0 * self.done / self.total if self.total else 0.0
        rate = self.done / elapsed if elapsed > 0 else 0.0

        if rate > 0 and remaining > 0:
            eta_s = remaining / rate
            if eta_s >= 3600:
                eta_str = f"{eta_s / 3600:.1f}h"
            elif eta_s >= 60:
                eta_str = f"{eta_s / 60:.1f}m"
            else:
                eta_str = f"{eta_s:.0f}s"
        else:
            eta_str = "?"

        if elapsed >= 3600:
            elapsed_str = f"{elapsed / 3600:.1f}h"
        elif elapsed >= 60:
            elapsed_str = f"{elapsed / 60:.1f}m"
        else:
            elapsed_str = f"{elapsed:.0f}s"

        date_part = f"  log date ~{log_date}" if log_date else ""
        return (
            f"[{self.done:,}/{self.total:,} msgs  {pct:.1f}%"
            f"  elapsed {elapsed_str}  ETA {eta_str}{date_part}]"
        )


@dataclass
class SeedCheckpoint:
    """Per-batch checkpoint for stop/resume support (REQ-501–509)."""

    version: int = 1
    file: str = ""
    batch_size: int = 0
    exclude_users: list[str] = field(default_factory=list)
    completed_offsets: set[int] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> "SeedCheckpoint":
        """Load from JSON; return a fresh instance on missing file or parse error."""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                version=raw.get("version", 1),
                file=raw.get("file", ""),
                batch_size=raw.get("batch_size", 0),
                exclude_users=raw.get("exclude_users", []),
                completed_offsets=set(raw.get("completed_offsets", [])),
            )
        except FileNotFoundError:
            return cls()
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Checkpoint %s is malformed (%s); starting fresh.", path, exc
            )
            return cls()

    def save(self, path: Path) -> None:
        """Write atomically: write to .tmp then os.replace (REQ-504)."""
        data = {
            "version": self.version,
            "file": self.file,
            "batch_size": self.batch_size,
            "exclude_users": self.exclude_users,
            "completed_offsets": sorted(self.completed_offsets),
        }
        tmp = path.with_suffix(".seed-checkpoint.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def mark_done(self, offset: int) -> None:
        """Record *offset* as completed (REQ-505)."""
        self.completed_offsets.add(offset)

    def is_done(self, offset: int) -> bool:
        """Return True if *offset* has already been completed (REQ-506)."""
        return offset in self.completed_offsets


@dataclass
class _SeedWorkerStats:
    """Aggregated counters across all concurrent seed workers (REQ-514)."""

    batches: int = 0
    facts: int = 0
    excluded: int = 0


# Chat-log line pattern: "HH:MM:SS <username>: message"
_LINE_RE = re.compile(r"^(?P<time>\d{2}:\d{2}:\d{2})\s+" r"<(?P<user>[^>]+)>:\s*" r"(?P<msg>.+)$")
# Server / status lines to ignore: "HH:MM:SS <[server]>: ..." or "HH:MM:SS ***"
_SERVER_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\s+(?:<\[[^\]]+\]>|(?:\*\*\*))")


def _parse_log_file(path: Path, *, log_end_date: date | None = None) -> list[dict]:
    """Parse a single chat log file and return message dicts.

    Returns ``[{"username", "message", "time"}]``.
    When *log_end_date* is provided (or derivable from file mtime), each dict
    also gains a ``"date"`` key (``"YYYY-MM-DD"`` ISO string) computed by the
    midnight-crossing algorithm (Sprint 20.5, REQ-450–451).
    """
    messages: list[dict] = []
    all_times: list[int | None] = []
    msg_line_indices: list[int | None] = []  # per file-line: index in messages, or None

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        logging.getLogger(__name__).warning(f"Could not parse log file {path}: {exc}")
        return []

    for raw in lines:
        if _SERVER_RE.match(raw):
            all_times.append(None)
            msg_line_indices.append(None)
            continue
        m = _LINE_RE.match(raw)
        if m:
            t_str = m.group("time").strip()
            from kryten_llm.components.memory.log_date_utils import time_str_to_seconds

            all_times.append(time_str_to_seconds(t_str))
            idx = len(messages)
            msg_line_indices.append(idx)
            messages.append(
                {
                    "username": m.group("user").strip(),
                    "message": m.group("msg").strip(),
                    "time": t_str,
                }
            )
        else:
            all_times.append(None)
            msg_line_indices.append(None)

    # Date reconstruction (REQ-450, REQ-451)
    end_anchor: date | None = log_end_date
    if end_anchor is None:
        try:
            import os as _os

            end_anchor = date.fromtimestamp(_os.stat(path).st_mtime)
        except Exception:
            end_anchor = None

    if end_anchor is not None:
        from kryten_llm.components.memory.log_date_utils import assign_dates

        dates = assign_dates(all_times, end_anchor)
        for line_idx, msg_idx in enumerate(msg_line_indices):
            if msg_idx is not None:
                messages[msg_idx]["date"] = dates[line_idx].isoformat()

    return messages


async def cmd_memory_seed(args: argparse.Namespace, config) -> None:
    """Bulk-import facts from historical chat logs (REQ-040, REQ-041, GUD-003).

    Routes to the LLM or heuristic extraction path based on the ``extractor.type``
    setting in config — the same setting used by the live service.
    """
    import glob as _glob

    logger = logging.getLogger(__name__)

    log_files = sorted(Path(p) for p in _glob.glob(args.logs, recursive=True))
    if not log_files:
        logger.error(f"No files matched glob: {args.logs}")
        sys.exit(1)
    logger.info(f"Found {len(log_files)} log file(s)")

    provider_cfg = _find_ltm_provider_cfg(config)
    if provider_cfg is None:
        logger.error(
            "No 'long_term_memory' provider found in config.context.providers. "
            "Add and enable the provider before seeding."
        )
        sys.exit(1)

    ext_type = provider_cfg.get("extractor", {}).get("type", "heuristic")

    # Sprint 20.5 (REQ-457): validate and resolve log_end_date.
    log_end_date = None
    if getattr(args, "log_end_date", None):
        try:
            log_end_date = date.fromisoformat(args.log_end_date)
        except ValueError:
            logger.error("Invalid --log-end-date '%s' (expected YYYY-MM-DD).", args.log_end_date)
            sys.exit(1)
    args._log_end_date_parsed = log_end_date

    if ext_type == "llm":
        await _seed_via_llm(args, config, provider_cfg, log_files, logger)
    else:
        await _seed_via_heuristic(args, provider_cfg, log_files, logger)


async def _preflight_store(store: Any, logger: logging.Logger) -> None:
    """Fail fast (before any extraction work) if the vector store is unreachable.

    A long seed run should not burn LLM calls only to die on the first write.
    """
    try:
        await store.count(where={"user": "__preflight__"})
    except Exception as exc:
        logger.error(
            "Cannot reach the long-term memory store: %s\n"
            "If using the pgvector backend in WSL, make sure the DB is running:\n"
            "  wsl -d kryten-pg -u root /usr/local/bin/start-kryten-pg.sh",
            exc,
        )
        sys.exit(1)


def _init_seed_checkpoint(
    args: argparse.Namespace,
    batch_size: int,
    exclude: set[str],
    logger: logging.Logger,
) -> "SeedCheckpoint | None":
    """Initialise (or load) the checkpoint for this seed run (REQ-507)."""
    checkpoint_path: Path | None = getattr(args, "checkpoint", None)
    if checkpoint_path is None:
        return None

    reset = getattr(args, "reset_checkpoint", False)
    resume = getattr(args, "resume", False)

    if reset:
        checkpoint_path.unlink(missing_ok=True)
        logger.info("Checkpoint reset: deleted %s", checkpoint_path)

    ckpt = SeedCheckpoint.load(checkpoint_path) if resume else SeedCheckpoint()

    if resume and ckpt.completed_offsets:
        logger.info(
            "Resuming from checkpoint: %d batch(es) already completed.",
            len(ckpt.completed_offsets),
        )
        if ckpt.batch_size and ckpt.batch_size != batch_size:
            logger.warning(
                "Checkpoint batch_size %d ≠ current %d; offsets may not align "
                "— consider --reset-checkpoint.",
                ckpt.batch_size,
                batch_size,
            )
        if set(ckpt.exclude_users) != exclude:
            logger.warning(
                "Checkpoint exclude_users differs from current config; "
                "offsets may not align — consider --reset-checkpoint."
            )

    ckpt.batch_size = batch_size
    ckpt.exclude_users = sorted(exclude)
    return ckpt


def _build_worker_extractors(
    ext_cfg: Any,
    provider_cfg: dict,
    n_workers: int,
    logger: logging.Logger,
) -> list[Any]:
    """Build N LLMFactExtractor instances for the seed worker pool (REQ-512).

    Workers are assigned providers round-robin from ``seed.worker_providers`` if
    configured; otherwise all workers share the full provider chain.
    """
    from kryten_llm.components.llm_manager import LLMManager
    from kryten_llm.components.memory.llm_extractor import LLMFactExtractor

    _ext_raw: dict = provider_cfg.get("extractor", {})
    # Accept seed config at either extractor.seed or extractor.llm.seed (REQ-511).
    seed_cfg: dict = _ext_raw.get("seed") or _ext_raw.get("llm", {}).get("seed", {})
    worker_provider_names: list[str] = seed_cfg.get("worker_providers", [])
    all_providers = ext_cfg.llm.providers

    workers: list[Any] = []
    for i in range(n_workers):
        if worker_provider_names:
            name = worker_provider_names[i % len(worker_provider_names)]
            if name not in all_providers:
                raise ValueError(
                    f"seed.worker_providers entry '{name}' not found in "
                    f"extractor.llm.providers. Available: {list(all_providers.keys())}"
                )
            providers = {name: all_providers[name]}
            priority = [name]
        else:
            providers = dict(all_providers)
            priority = list(ext_cfg.llm.provider_priority or providers.keys())

        manager = LLMManager.for_extractor(
            providers=providers,
            provider_priority=priority,
            retry_strategy=ext_cfg.llm.retry_strategy,
        )
        workers.append(LLMFactExtractor(manager, ext_cfg, logging.getLogger(__name__)))

    return workers


async def _seed_worker_task(
    worker_id: int,
    extractor: Any,
    queue: asyncio.Queue,
    provider: Any,
    args: argparse.Namespace,
    exclude: set[str],
    progress: _SeedProgress,
    checkpoint: "SeedCheckpoint | None",
    ckpt_lock: asyncio.Lock,
    stats: _SeedWorkerStats,
) -> None:
    """One concurrent seed worker coroutine (REQ-513)."""
    _log = logging.getLogger(__name__)
    while True:
        item = await queue.get()
        if item is None:  # sentinel — this worker is done
            break
        start, batch, batch_ts = item

        try:
            extracted = await extractor.extract(batch, "")
        except Exception as exc:
            _log.warning("Seed worker %d: extract failed at offset %d: %s", worker_id, start, exc)
            extracted = []

        batch_facts = 0
        batch_excluded = 0
        for ef in extracted:
            if ef.target_user.lower() in exclude:  # REQ-498: safety net
                batch_excluded += 1
                continue
            ef.historical_ts = batch_ts  # REQ-455
            if args.dry_run:
                _log.info(
                    "[dry-run] Would store: [%s] %s (user=%s, conf=%.2f)",
                    ef.category,
                    ef.summary,
                    ef.target_user,
                    ef.confidence,
                )
                batch_facts += 1
            else:
                try:
                    await provider._persist(ef)
                    batch_facts += 1
                except Exception as exc:
                    _log.warning(
                        "Seed worker %d: persist failed for %s: %s",
                        worker_id,
                        ef.target_user,
                        exc,
                    )

        # All shared-state updates in one lock acquisition per batch (REQ-514).
        async with ckpt_lock:
            stats.batches += 1
            stats.facts += batch_facts
            stats.excluded += batch_excluded
            progress.advance(len(batch))
            if checkpoint:
                checkpoint.mark_done(start)
                checkpoint.save(args.checkpoint)
            if progress.should_report():
                log_date = batch_ts.split("T")[0] if batch_ts else None
                _log.info(progress.format(log_date))


async def _seed_via_llm(
    args: argparse.Namespace,
    config: Any,
    provider_cfg: dict,
    log_files: list[Path],
    logger: logging.Logger,
) -> None:
    """LLM-mode seed: builds the full LTM provider and uses ``_persist`` so that
    dedup, cap enforcement, and the LLM metadata schema (confidence/importance/…)
    are all applied identically to the live path.
    """
    from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider

    provider = LongTermMemoryProvider.from_config(provider_cfg, config, {})
    assert provider._ext_cfg is not None, "Provider was not built in LLM mode"

    # Fail fast if the store is down, before spending any LLM calls.
    await _preflight_store(provider._store, logger)

    batch_size = provider._ext_cfg.cadence.batch_max_size
    exclude: set[str] = provider._observe_exclude  # already lowercased

    n_workers = max(1, getattr(args, "workers", 1))
    if n_workers > 8:
        logger.warning(
            "--workers %d exceeds 8; hardware limits may throttle performance.", n_workers
        )

    # Build worker extractor(s) for the configured provider routing (REQ-512/516).
    worker_extractors = _build_worker_extractors(provider._ext_cfg, provider_cfg, n_workers, logger)

    total_batches = 0
    total_facts = 0
    total_excluded = 0

    # Pre-parse all files so we know the global total and can report accurate progress.
    all_file_data: list[tuple[Path, list[dict]]] = []
    for log_path in log_files:
        messages = _parse_log_file(
            log_path, log_end_date=getattr(args, "_log_end_date_parsed", None)
        )
        if not messages:
            logger.warning(f"No parseable messages in {log_path}")
        else:
            all_file_data.append((log_path, messages))

    # Sort newest file first (REQ-491, Sprint 24).
    all_file_data.sort(key=lambda item: _mtime_or_zero(item[0]), reverse=True)

    # REQ-497: count only human messages; bots will be pre-filtered per file.
    total_messages = sum(
        sum(1 for m in msgs if m["username"].lower() not in exclude) for _, msgs in all_file_data
    )
    logger.info(
        "Total: %s human messages across %d file(s) — starting LLM seed%s",
        f"{total_messages:,}",
        len(all_file_data),
        f" ({n_workers} workers)" if n_workers > 1 else "",
    )
    progress = _SeedProgress(total_messages)

    # Sortie 2: initialise checkpoint (REQ-507).
    checkpoint: SeedCheckpoint | None = _init_seed_checkpoint(args, batch_size, exclude, logger)

    for log_path, messages in all_file_data:
        if checkpoint:
            checkpoint.file = str(log_path.resolve())

        # REQ-497: filter excluded users so every batch slot is a human message.
        human_messages = [m for m in messages if m["username"].lower() not in exclude]
        bot_count = len(messages) - len(human_messages)
        print(
            f"\nProcessing {log_path.name} — {len(human_messages):,} human messages"
            + (
                f"\n    ({bot_count:,} bot messages filtered from {len(messages):,} total)"
                if bot_count
                else ""
            )
        )

        # Batches built from human_messages (REQ-492, Sprint 24 still applies).
        batch_starts = list(range(0, len(human_messages), batch_size))

        if n_workers <= 1:
            # ----------------------------------------------------------
            # Sequential path (REQ-516) — identical to pre-Sprint-25
            # with pre-filter and checkpoint applied.
            # ----------------------------------------------------------
            file_facts = 0
            for start in reversed(batch_starts):
                batch_len = min(batch_size, len(human_messages) - start)
                if checkpoint and checkpoint.is_done(start):
                    progress.advance(batch_len)
                    total_batches += 1
                    continue

                batch = human_messages[start : start + batch_size]
                total_batches += 1

                # REQ-455 (Sprint 20.5): batch historical timestamp.
                batch_ts: str | None = next(
                    (f"{m['date']}T{m['time']}+00:00" for m in batch if m.get("date")),
                    None,
                )

                extracted = await worker_extractors[0].extract(batch, "")
                for ef in extracted:
                    if ef.target_user.lower() in exclude:  # REQ-498: safety net
                        total_excluded += 1
                        continue
                    ef.historical_ts = batch_ts
                    if args.dry_run:
                        logger.info(
                            f"[dry-run] Would store: [{ef.category}] {ef.summary} "
                            f"(user={ef.target_user}, conf={ef.confidence:.2f})"
                        )
                    else:
                        await provider._persist(ef)
                    file_facts += 1
                    total_facts += 1

                progress.advance(len(batch))
                if checkpoint:
                    checkpoint.mark_done(start)
                    checkpoint.save(args.checkpoint)
                if progress.should_report():
                    log_date = batch_ts.split("T")[0] if batch_ts else None
                    logger.info(progress.format(log_date))

            print(
                f"  {file_facts} fact(s) {'(dry run) ' if args.dry_run else ''}from {log_path.name}"
            )

        else:
            # ----------------------------------------------------------
            # Concurrent path (REQ-515).
            # ----------------------------------------------------------
            queue: asyncio.Queue = asyncio.Queue()
            ckpt_lock = asyncio.Lock()
            stats = _SeedWorkerStats()

            # Enqueue pending batches; skip already-completed ones.
            skipped = 0
            for start in reversed(batch_starts):
                batch_len = min(batch_size, len(human_messages) - start)
                if checkpoint and checkpoint.is_done(start):
                    progress.advance(batch_len)
                    skipped += 1
                    continue
                batch = human_messages[start : start + batch_size]
                batch_ts_val: str | None = next(
                    (f"{m['date']}T{m['time']}+00:00" for m in batch if m.get("date")),
                    None,
                )
                await queue.put((start, batch, batch_ts_val))

            if skipped:
                logger.info("Skipped %d already-completed batch(es) (checkpoint resume).", skipped)

            # One sentinel per worker to drain the queue cleanly.
            for _ in worker_extractors:
                await queue.put(None)

            tasks = [
                asyncio.create_task(
                    _seed_worker_task(
                        i,
                        worker_extractors[i],
                        queue,
                        provider,
                        args,
                        exclude,
                        progress,
                        checkpoint,
                        ckpt_lock,
                        stats,
                    )
                )
                for i in range(n_workers)
            ]
            await asyncio.gather(*tasks)

            total_batches += stats.batches + skipped
            total_facts += stats.facts
            total_excluded += stats.excluded
            print(
                f"  {stats.facts} fact(s) {'(dry run) ' if args.dry_run else ''}from {log_path.name}"
            )

    if checkpoint and getattr(args, "checkpoint", None):
        print(
            f"\nSeed complete. Checkpoint at {args.checkpoint} may be removed "
            "or kept for re-run safety."
        )

    print(
        f"\nSeeding {'(dry run) ' if args.dry_run else ''}complete (LLM extractor):\n"
        f"  Batches processed : {total_batches}\n"
        f"  Facts written     : {total_facts}\n"
        f"  Skipped (excluded): {total_excluded}"
    )


async def _seed_via_heuristic(
    args: argparse.Namespace,
    provider_cfg: dict,
    log_files: list[Path],
    logger: logging.Logger,
) -> None:
    """Heuristic-mode seed: original per-user extraction path."""
    from datetime import datetime, timezone

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
    exclude: set[str] = {u.lower() for u in write_cfg.get("observe_exclude_users", [])}

    # Fail fast if the store is down, before processing any logs.
    await _preflight_store(vector_store, logger)

    users_processed: set[str] = set()
    total_written = 0
    total_skipped_safety = 0

    # Pre-parse all files so we know the global total and can report accurate progress.
    all_file_data_h: list[tuple[Path, list[dict]]] = []
    for log_path in log_files:
        messages = _parse_log_file(
            log_path, log_end_date=getattr(args, "_log_end_date_parsed", None)
        )
        if not messages:
            logger.warning(f"No parseable messages in {log_path}")
        else:
            all_file_data_h.append((log_path, messages))

    total_messages_h = sum(len(msgs) for _, msgs in all_file_data_h)
    logger.info(
        f"Total: {total_messages_h:,} messages across {len(all_file_data_h)} file(s)"
        f" — starting heuristic seed"
    )
    progress = _SeedProgress(total_messages_h)

    for log_path, messages in all_file_data_h:
        by_user: dict[str, list[dict]] = {}
        for msg in messages:
            by_user.setdefault(msg["username"], []).append(msg)

        print(
            f"\nProcessing {log_path.name} — {len(messages):,} messages, "
            f"{len(by_user):,} users (heuristic extractor)"
        )

        for user, user_msgs in by_user.items():
            progress.advance(len(user_msgs))
            if user.lower() in exclude:
                continue
            users_processed.add(user)
            facts = await extractor.extract(user_msgs, user)

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
                now = datetime.now(timezone.utc).isoformat()
                summaries = [f.summary for f in safe_facts]
                all_vectors = await embedder.embed(summaries)
                for fact, vector in zip(safe_facts, all_vectors):
                    # Sprint 20.5 (REQ-452): use historical log date when available.
                    evidence_msg = fact.evidence.get("message", "")
                    # Find the source message in user_msgs to get its date.
                    source_date: str | None = None
                    for umsg in user_msgs:
                        if umsg.get("message", "")[:100] == str(evidence_msg)[:100]:
                            source_date = umsg.get("date")
                            break
                    if source_date is None and user_msgs:
                        # Fallback: median date — use the middle message's date
                        mid = len(user_msgs) // 2
                        source_date = user_msgs[mid].get("date")
                    if source_date:
                        historical_ts = f"{source_date}T00:00:00+00:00"
                    else:
                        historical_ts = now
                    await vector_store.upsert(
                        ids=[stable_fact_id(fact.user, fact.summary)],
                        vectors=[vector],
                        metadatas=[
                            {
                                "user": fact.user,
                                "category": fact.category,
                                "source": "seed",
                                "created_at": historical_ts,
                                "last_seen": historical_ts,  # REQ-452
                                "score": fact.score,
                                "evidence": str(evidence_msg)[:200],
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

            if progress.should_report():
                log_date = next((m["date"] for m in user_msgs if m.get("date")), None)
                logger.info(progress.format(log_date))

    print(
        f"\nSeeding {'(dry run) ' if args.dry_run else ''}complete (heuristic extractor):\n"
        f"  Users processed : {len(users_processed)}\n"
        f"  Facts written   : {total_written}\n"
        f"  Skipped (safety): {total_skipped_safety}"
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


async def cmd_memory_eval(args: argparse.Namespace) -> None:
    """Run memory-quality evaluation suite (Sprint 12, Sortie 5, REQ-270–275).

    Uses FakeEmbedder + FakeStore — no live NATS, Chroma, or pgvector required.
    """
    from kryten_llm.eval_runner import run_eval_suite

    fixture_dir = getattr(args, "fixture_dir", None)
    json_output = getattr(args, "json_output", False)

    print("Running memory-quality evaluation suite …")
    report = await run_eval_suite(fixture_dir=fixture_dir)

    if json_output:
        print(report.to_json())
    else:
        print()
        print(report.to_table())
        print(f"\nElapsed: {report.elapsed_seconds:.2f}s")

    if not report.all_pass:
        sys.exit(1)


def _mtime_or_zero(path: Path) -> float:
    """Return *path* mtime as a float, or 0.0 if stat() raises (REQ-491)."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _find_ltm_provider_cfg(config) -> dict | None:
    """Return the long_term_memory provider config dict, or None."""
    providers = getattr(config.context, "providers", None) or []
    for p in providers:
        cfg = p if isinstance(p, dict) else (p.model_dump() if hasattr(p, "model_dump") else {})
        if cfg.get("type") == "long_term_memory":
            return cfg
    return None


def _build_store_and_embedder(provider_cfg: dict):
    """Shared helper: build and return (embedder, store) from provider config."""
    from kryten_llm.components.memory.embedder import build_embedder
    from kryten_llm.components.memory.vector_store import build_vector_store

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
    return embedder, store


# ---------------------------------------------------------------------------
# Sprint 19, Sortie 2: memory compact (REQ-390–394)
# ---------------------------------------------------------------------------


async def cmd_memory_compact(args: argparse.Namespace, config) -> None:
    """One-shot compaction pass (REQ-390–394)."""
    logger = logging.getLogger(__name__)
    provider_cfg = _find_ltm_provider_cfg(config)
    if provider_cfg is None:
        logger.error("No 'long_term_memory' provider found in config.")
        sys.exit(1)

    embedder, store = _build_store_and_embedder(provider_cfg)
    await _preflight_store(store, logger)

    compaction_cfg = getattr(config, "compaction", None)
    threshold = (
        args.threshold
        if args.threshold is not None
        else (compaction_cfg.merge_threshold if compaction_cfg is not None else 0.85)
    )
    min_facts = compaction_cfg.min_facts_to_compact if compaction_cfg is not None else 10
    importance_cap = compaction_cfg.importance_cap if compaction_cfg is not None else 10000

    from kryten_llm.components.memory.retention import CompactionSweeper

    sweeper = CompactionSweeper(
        store=store,
        embedder=embedder,
        min_facts_to_compact=min_facts,
        merge_threshold=threshold,
        importance_cap=importance_cap,
        dry_run=args.dry_run,
    )

    if args.user:
        try:
            records = await store.get_all(where={"user": args.user})
        except Exception as exc:
            logger.error("Could not fetch facts for user %s: %s", args.user, exc)
            sys.exit(1)
        n = await sweeper._sweep_user(args.user, records)
    else:
        n = await sweeper.sweep()

    dry = " (dry run)" if args.dry_run else ""
    print(f"{'[dry-run] Would compact' if args.dry_run else 'Compacted'} {n} fact(s).{dry}")


# ---------------------------------------------------------------------------
# Sprint 20, Sortie 3: memory backfill-last-seen (REQ-415–419)
# ---------------------------------------------------------------------------


async def cmd_memory_backfill_last_seen(args: argparse.Namespace, config) -> None:
    """Set last_seen=created_at for facts missing last_seen (REQ-415–419)."""
    from datetime import datetime, timezone

    logger = logging.getLogger(__name__)
    provider_cfg = _find_ltm_provider_cfg(config)
    if provider_cfg is None:
        logger.error("No 'long_term_memory' provider found in config.")
        sys.exit(1)

    _embedder, store = _build_store_and_embedder(provider_cfg)
    await _preflight_store(store, logger)

    try:
        records = await store.get_all()
    except Exception as exc:
        logger.error("Could not fetch facts: %s", exc)
        sys.exit(1)

    to_update_ids: list[str] = []
    to_update_metas: list[dict] = []
    already_have = 0

    for r in records:
        meta = dict(r.get("metadata") or {})
        if meta.get("last_seen"):
            already_have += 1
            continue
        rid = r.get("id")
        if rid is None:
            continue
        # Set last_seen = created_at, or now() as fallback
        ts = meta.get("created_at") or datetime.now(timezone.utc).isoformat()
        meta["last_seen"] = ts
        to_update_ids.append(str(rid))
        to_update_metas.append(meta)

    if args.dry_run:
        print(f"[dry-run] Would backfill {len(to_update_ids)} fact(s).")
        return

    if to_update_ids:
        try:
            await store.update_metadata(to_update_ids, to_update_metas)
        except Exception as exc:
            logger.error("update_metadata failed: %s", exc)
            sys.exit(1)

    print(f"Backfilled {len(to_update_ids)} fact(s). {already_have} already had last_seen.")


# ---------------------------------------------------------------------------
# Sprint 20.5, Sortie 3: memory reset (REQ-459)
# ---------------------------------------------------------------------------


async def cmd_memory_reset(args: argparse.Namespace, config) -> None:
    """Delete all facts from the configured store (REQ-459)."""
    logger = logging.getLogger(__name__)
    provider_cfg = _find_ltm_provider_cfg(config)
    if provider_cfg is None:
        logger.error("No 'long_term_memory' provider found in config.")
        sys.exit(1)

    _embedder, store = _build_store_and_embedder(provider_cfg)

    try:
        count = await store.count()
    except Exception as exc:
        logger.error("Cannot reach store: %s", exc)
        sys.exit(1)

    if not args.confirm:
        print(f"Store contains {count} document(s).")
        print(f"Rerun with --confirm to permanently delete all {count} documents.")
        return

    try:
        await store.reset()
    except Exception as exc:
        logger.error("Store reset failed: %s", exc)
        sys.exit(1)

    print(f"Store cleared. {count} document(s) deleted.")


# ---------------------------------------------------------------------------
# Service startup
# ---------------------------------------------------------------------------


async def main_async() -> None:
    """Main async entry point."""
    args = parse_args()
    setup_logging(getattr(args, "log_level", "INFO"))

    logger = logging.getLogger(__name__)

    # Phase 7: memory subcommands
    if args.subcommand == "memory":
        # memory eval does not need a config file (REQ-275)
        if args.memory_cmd == "eval":
            await cmd_memory_eval(args)
            return

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
        elif args.memory_cmd == "compact":
            await cmd_memory_compact(args, config)
        elif args.memory_cmd == "backfill-last-seen":
            await cmd_memory_backfill_last_seen(args, config)
        elif args.memory_cmd == "reset":
            await cmd_memory_reset(args, config)
        else:
            print(
                "Usage: kryten-llm memory "
                "{seed|forget|recall|stats|eval|compact|backfill-last-seen|reset} [options]"
            )
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
