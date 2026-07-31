# SPEC-Sortie-3: CLI Enhancements — `--log-end-date` and `memory reset`

**Sprint**: 20.5 — Temporal-Accurate Bulk Import
**PRD**: [PRD-temporal-bulk-import.md](PRD-temporal-bulk-import.md)
**Status**: Planned
**Estimate**: 2h
**Depends on**: Sortie 2 (date reconstruction wired into seed paths)
**Requirements**: REQ-457 – REQ-460

---

## 1. Overview

Two CLI additions that complete the operator workflow:

1. `--log-end-date YYYY-MM-DD` on `memory seed` — explicit end-date anchor that overrides
   the file's mtime when the log is still being appended to (or mtime is untrustworthy).
2. `memory reset [--confirm]` — drops and recreates the configured store so stale
   incorrectly-timestamped data can be cleared before re-seeding.

---

## 2. Scope and Non-Goals

**In scope**: `parse_args()` in `__main__.py`; `_seed_via_heuristic` / `_seed_via_llm`
consuming `args.log_end_date`; new `cmd_memory_reset` function and its `argparse` entry;
`CHANGELOG.md` update.

**Non-goals**: Changes to the date reconstruction algorithm (Sortie 1). Changes to the
upsert metadata schema (Sortie 2). Any UI beyond the CLI.

---

## 3. Requirements

- **REQ-457** — `memory seed` gains `--log-end-date DATE` (string, optional). When
  provided, it is parsed as `date.fromisoformat(DATE)` and passed as `log_end_date` to
  `_parse_log_file`. If parsing fails, the command exits with a clear error message before
  any processing begins.
- **REQ-458** — When `--log-end-date` is not provided, `_parse_log_file` uses the file's
  `st_mtime` as the end-date anchor (automatic behaviour from Sortie 2, REQ-451). No
  opt-in flag is required; date reconstruction is always attempted.
- **REQ-459** — New subcommand: `kryten-llm memory reset [--confirm]`.
  - Without `--confirm`: prints the current document count and the message
    `"Rerun with --confirm to permanently delete all {count} documents."` Then exits 0.
  - With `--confirm`: clears the store (backend-specific implementation below), then
    prints `"Store cleared. {count} documents deleted."`.
  - Requires the same `long_term_memory` provider config as `seed`.
- **REQ-460** — `CHANGELOG.md` entry under `[Unreleased]` documents Sprint 20.5 changes:
  date reconstruction, `--log-end-date`, `memory reset`, `historical_ts` on
  `ExtractedFact`, `last_seen` written in heuristic seed path.

---

## 4. Design

### 4.1 `parse_args` additions

```python
seed_p.add_argument(
    "--log-end-date",
    metavar="YYYY-MM-DD",
    default=None,
    help=(
        "Explicit end-date anchor for midnight-crossing detection "
        "(overrides file mtime). Use when the log file is still being written to."
    ),
)

# New reset subcommand
reset_p = mem_sub.add_parser(
    "reset",
    help="Delete all stored facts from the memory store (irreversible without backup)",
)
reset_p.add_argument(
    "--confirm",
    action="store_true",
    help="Required to actually delete. Without this flag, only the current count is shown.",
)
```

### 4.2 `--log-end-date` validation and threading

In `main()` / wherever `cmd_memory_seed` is dispatched:

```python
if args.memory_cmd == "seed":
    log_end_date: date | None = None
    if args.log_end_date:
        try:
            log_end_date = date.fromisoformat(args.log_end_date)
        except ValueError:
            print(
                f"Error: --log-end-date '{args.log_end_date}' is not a valid ISO date "
                f"(expected YYYY-MM-DD).",
                file=sys.stderr,
            )
            sys.exit(1)
    args.log_end_date_parsed = log_end_date
    await cmd_memory_seed(args, config)
```

Pass `args.log_end_date_parsed` into `_parse_log_file` calls inside `_seed_via_heuristic`
and `_seed_via_llm`.

### 4.3 `cmd_memory_reset`

```python
async def cmd_memory_reset(args: argparse.Namespace, config: Any) -> None:
    """Delete all facts from the configured store (REQ-459)."""
    logger = logging.getLogger(__name__)
    provider_cfg = _find_ltm_provider_cfg(config)
    if provider_cfg is None:
        logger.error("No 'long_term_memory' provider found in config.")
        sys.exit(1)

    from kryten_llm.components.memory.embedder import build_embedder
    from kryten_llm.components.memory.vector_store import build_vector_store

    emb_cfg = provider_cfg.get("embedder", {"type": "onnx", "model": "all-MiniLM-L6-v2"})
    embedder = build_embedder(emb_cfg)
    store_cfg = provider_cfg.get("store", {})
    store = build_vector_store(
        store_cfg,
        embedder_id=embedder.id,
        dimension=getattr(embedder, "dimension", 0),
    )

    try:
        count = await store.count(where={})
    except Exception as exc:
        logger.error("Cannot reach store: %s", exc)
        sys.exit(1)

    if not args.confirm:
        print(f"Store contains {count} document(s).")
        print(f"Rerun with --confirm to permanently delete all {count} documents.")
        return

    await store.reset()   # see §4.4 below
    print(f"Store cleared. {count} document(s) deleted.")
```

### 4.4 `VectorStore.reset()` method

Both backends need a `reset()` async method:

**Chroma backend** (`vector_store.py` / `chroma_store.py`):
```python
async def reset(self) -> None:
    """Delete and recreate the collection."""
    self._client.delete_collection(self._collection_name)
    self._collection = self._client.get_or_create_collection(
        self._collection_name,
        metadata={"hnsw:space": "cosine"},
    )
```

**pgvector backend**:
```python
async def reset(self) -> None:
    """Truncate the facts table."""
    async with self._pool.acquire() as conn:
        await conn.execute(f'TRUNCATE TABLE "{self._table_name}"')
```

> **Note**: `VectorStore.reset()` is a new method on the abstract base class / protocol.
> If there is no shared base class, add it to both concrete implementations. If adding to
> an abstract class, provide a default `NotImplementedError` body so existing test fakes
> don't break until updated.

### 4.5 `CHANGELOG.md` entry (REQ-460)

Under `## [Unreleased]`:

```markdown
### Added
- `memory reset [--confirm]` CLI subcommand: safely clears the memory store before
  re-seeding (Sprint 20.5, REQ-459).
- `memory seed --log-end-date YYYY-MM-DD`: explicit end-date anchor for log date
  reconstruction when file mtime is unreliable (Sprint 20.5, REQ-457).
- Log date reconstruction: `_parse_log_file` now infers calendar dates from midnight
  crossings in the HH:MM:SS log format, anchored to the file's mtime (Sprint 20.5,
  REQ-450–451).
- `ExtractedFact.historical_ts`: threads historically accurate ISO datetime through the
  LLM seed path and into `_persist` (Sprint 20.5, REQ-454–456).

### Fixed
- Heuristic-mode `memory seed` now writes `last_seen` (was missing) and uses the
  reconstructed historical log date as `created_at`/`last_seen` rather than seeding
  time (Sprint 20.5, REQ-452).
```

---

## 5. Operator Runbook

After all three sorties are complete:

```bash
# 1. (Optional) Check how many facts are currently stored.
python -m kryten_llm --config config.json memory reset

# 2. Clear the store (destructive — ensure no other service is reading).
python -m kryten_llm --config config.json memory reset --confirm

# 3. Re-seed with historically accurate timestamps.
#    Omit --log-end-date to use file mtime as anchor (appropriate for a closed archive).
python -m kryten_llm --config config.json memory seed --logs "chat-messages.log"

#    Or supply an explicit anchor if mtime is unreliable:
python -m kryten_llm --config config.json memory seed \
    --logs "chat-messages.log" \
    --log-end-date 2025-06-01
```

---

## 6. Tests

### `tests/test_memory_reset_cli.py`

```python
"""Integration test for memory reset subcommand."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_reset_without_confirm_prints_count(capsys):
    """Without --confirm, reset prints count and exits cleanly."""
    # ... mock store.count() → 42, assert --confirm absent → prints "42 documents"

@pytest.mark.asyncio
async def test_reset_with_confirm_calls_store_reset(capsys):
    """With --confirm, store.reset() is called."""
    # ... mock store.reset(), assert it was called once

@pytest.mark.asyncio
async def test_log_end_date_invalid_exits(capsys):
    """Invalid --log-end-date causes sys.exit(1) before any processing."""
    # ... pass args.log_end_date = "not-a-date", assert sys.exit(1)
```

---

## 7. Acceptance Criteria

- `kryten-llm memory reset` (no `--confirm`) prints count and exits without modifying store.
- `kryten-llm memory reset --confirm` calls `store.reset()` and confirms deletion.
- `kryten-llm memory seed --log-end-date 2025-01-01 --logs x.log` passes the parsed date
  to `_parse_log_file`; invalid date strings exit with a clear error.
- `CHANGELOG.md` updated.
- `mypy --strict` clean on changed files.
- All existing `memory seed` and `memory stats` tests still pass.
