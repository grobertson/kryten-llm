# SPEC-Sortie-1: Reverse-Chronological LLM Seed

**Sprint**: 24 — Reverse-Chronological Memory Seed
**PRD**: [PRD-reverse-seed.md](PRD-reverse-seed.md)
**Status**: Planned
**Estimate**: 2h
**Depends on**: Nothing — contained change in `_seed_via_llm`
**Requirements**: REQ-491 – REQ-496

---

## 1. Overview

Invert the processing order in `_seed_via_llm` so that:

1. Log files are processed newest-first (by `st_mtime` descending).
2. Within each file, batches are submitted to the LLM extractor newest-first, with
   each batch's messages still in forward chronological order internally.

No other files change. The heuristic path is untouched. All Sprint 20.5 timestamp
behaviour is preserved.

---

## 2. Requirements

- **REQ-491** — After the pre-parse loop in `_seed_via_llm`, `all_file_data` is
  re-sorted by `item[0].stat().st_mtime` descending before any extraction begins.
  If `stat()` raises for an entry, that entry is sorted last (fallback key = 0.0).
- **REQ-492** — The batch loop iterates over `reversed(list(range(0, len(messages),
  batch_size)))`. Each batch slice `messages[start : start + batch_size]` is in forward
  (chronological) order. The loop body is otherwise unchanged.
- **REQ-493** — `batch_ts` continues to anchor to the first dated message in the batch
  (the earliest timestamp in the window). No change to the `batch_ts` computation.
- **REQ-494** — `_parse_log_file` and all of `log_date_utils.py` are unmodified.
  Date reconstruction operates on the full forward message list before any batching.
- **REQ-495** — `_SeedProgress.advance(len(batch))` is called once per batch as before.
  The total message count, ETA, and elapsed-time logic are unaffected by processing order.
- **REQ-496** — A new test (`tests/test_seed_reverse_order.py`) verifies reverse ordering
  end-to-end using a mock LLM provider and a two-file fixture (one "old" file, one "new"
  file with a later mtime). The test asserts that:
  (a) batches from the newer file are extracted before batches from the older file, and
  (b) within each file, the highest-indexed batch is extracted before the lowest-indexed
  batch.

---

## 3. Implementation

### 3.1 File: `kryten_llm/__main__.py`

#### 3.1.1 File sort — add after the pre-parse loop

Find the block ending with:

```python
    total_messages = sum(len(msgs) for _, msgs in all_file_data)
    logger.info(
        f"Total: {total_messages:,} messages across {len(all_file_data)} file(s) — starting LLM seed"
    )
```

Insert **before** the `logger.info(...)` call:

```python
    # Sort newest file first so the most recent facts reach the store immediately.
    all_file_data.sort(
        key=lambda item: _mtime_or_zero(item[0]),
        reverse=True,
    )
```

Add the helper near `_build_store_and_embedder`:

```python
def _mtime_or_zero(path: Path) -> float:
    """Return path mtime as a float, or 0.0 if stat() fails."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
```

#### 3.1.2 Batch loop — reverse batch order

Replace:

```python
        # Slide a window of batch_size through all messages in the file.
        for i in range(0, len(messages), batch_size):
            batch = messages[i : i + batch_size]
```

With:

```python
        # Process newest batch first; each batch is internally chronological so
        # the LLM extractor receives natural conversation context.
        batch_starts = list(range(0, len(messages), batch_size))
        for start in reversed(batch_starts):
            batch = messages[start : start + batch_size]
```

No other changes to the loop body.

---

### 3.2 File: `tests/test_seed_reverse_order.py` (new)

```python
"""REQ-496 — _seed_via_llm processes newest file / newest batches first."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from kryten_llm.__main__ import _seed_via_llm


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

class _FakeExtractedFact:
    def __init__(self) -> None:
        self.target_user = "alice"
        self.category = "test"
        self.summary = "stub fact"
        self.confidence = 0.9
        self.historical_ts: str | None = None


class _FakeExtractor:
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    async def extract(self, batch: list[dict], _context: str) -> list[_FakeExtractedFact]:
        self.calls.append(list(batch))
        return [_FakeExtractedFact()]


class _FakeProvider:
    def __init__(self) -> None:
        self.extractor = _FakeExtractor()
        self._ext_cfg = MagicMock()
        self._ext_cfg.cadence.batch_max_size = 2
        self._observe_exclude: set[str] = set()
        self._store = AsyncMock()
        self._store.count = AsyncMock(return_value=1)

    async def _persist(self, ef: _FakeExtractedFact) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_messages(n: int, date_str: str) -> list[dict]:
    """Build *n* dummy message dicts tagged with *date_str*."""
    return [
        {"username": "user", "message": f"msg{i}", "time": f"10:0{i%10}:00", "date": date_str}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_newest_file_processed_first(tmp_path: Path) -> None:
    """Files with a later mtime should be processed before files with an earlier mtime."""
    import time

    old_file = tmp_path / "old.log"
    new_file = tmp_path / "new.log"
    old_file.write_text("placeholder")
    time.sleep(0.05)
    new_file.write_text("placeholder")
    # new_file.mtime > old_file.mtime

    old_msgs = _make_messages(4, "2024-01-01")
    new_msgs = _make_messages(4, "2024-06-01")

    # all_file_data is pre-parsed; pass it in alphabetical order (old first).
    # _seed_via_llm must re-sort to process new_file first.
    fake_provider = _FakeProvider()

    args = MagicMock()
    args.dry_run = False
    args._log_end_date_parsed = None

    # Patch _parse_log_file so it returns our canned messages per file.
    _file_map = {old_file: old_msgs, new_file: new_msgs}

    def _fake_parse(path: Path, *, log_end_date=None) -> list[dict]:
        return list(_file_map[path])

    with patch("kryten_llm.__main__._parse_log_file", side_effect=_fake_parse):
        with patch(
            "kryten_llm.components.context.providers.long_term_memory"
            ".LongTermMemoryProvider.from_config",
            return_value=fake_provider,
        ):
            # Call the internal function directly with a pre-built log_files list.
            # We need to exercise the sort, so we patch all_file_data construction.
            # Simplest: call _seed_via_llm with both files listed old-first.
            log_files = [old_file, new_file]
            await _seed_via_llm(args, MagicMock(), {}, log_files, MagicMock())

    # All batches are of size 2; 4 messages → 2 batches per file → 4 total calls.
    assert len(fake_provider.extractor.calls) == 4

    # First two calls must be from the new file (date "2024-06-01").
    for call in fake_provider.extractor.calls[:2]:
        assert all(m["date"] == "2024-06-01" for m in call), (
            "Expected newest file's batches to be extracted first"
        )

    # Last two calls must be from the old file.
    for call in fake_provider.extractor.calls[2:]:
        assert all(m["date"] == "2024-01-01" for m in call), (
            "Expected oldest file's batches to be extracted last"
        )


@pytest.mark.asyncio
async def test_newest_batch_within_file_processed_first(tmp_path: Path) -> None:
    """Within a single file, the highest-indexed batch should be extracted first."""
    log_file = tmp_path / "test.log"
    log_file.write_text("placeholder")

    # 6 messages, batch_size=2 → batches [0:2], [2:4], [4:6]
    # Expected extraction order: [4:6] first, then [2:4], then [0:2].
    msgs = [
        {"username": "u", "message": f"m{i}", "time": f"10:0{i}:00", "date": "2024-03-01"}
        for i in range(6)
    ]

    fake_provider = _FakeProvider()

    args = MagicMock()
    args.dry_run = False
    args._log_end_date_parsed = None

    with patch("kryten_llm.__main__._parse_log_file", return_value=msgs):
        with patch(
            "kryten_llm.components.context.providers.long_term_memory"
            ".LongTermMemoryProvider.from_config",
            return_value=fake_provider,
        ):
            await _seed_via_llm(args, MagicMock(), {}, [log_file], MagicMock())

    calls = fake_provider.extractor.calls
    assert len(calls) == 3

    # First extracted batch should contain messages m4 and m5 (newest).
    assert calls[0][0]["message"] == "m4"
    assert calls[0][1]["message"] == "m5"

    # Last extracted batch should contain messages m0 and m1 (oldest).
    assert calls[2][0]["message"] == "m0"
    assert calls[2][1]["message"] == "m1"


@pytest.mark.asyncio
async def test_each_batch_is_internally_chronological(tmp_path: Path) -> None:
    """Each batch passed to the extractor must be in forward (chronological) order."""
    log_file = tmp_path / "test.log"
    log_file.write_text("placeholder")

    msgs = [
        {"username": "u", "message": f"m{i}", "time": f"10:{i:02d}:00", "date": "2024-03-01"}
        for i in range(8)
    ]

    fake_provider = _FakeProvider()
    args = MagicMock()
    args.dry_run = False
    args._log_end_date_parsed = None

    with patch("kryten_llm.__main__._parse_log_file", return_value=msgs):
        with patch(
            "kryten_llm.components.context.providers.long_term_memory"
            ".LongTermMemoryProvider.from_config",
            return_value=fake_provider,
        ):
            await _seed_via_llm(args, MagicMock(), {}, [log_file], MagicMock())

    for call in fake_provider.extractor.calls:
        times = [m["time"] for m in call]
        assert times == sorted(times), f"Batch was not in chronological order: {times}"
```

---

## 4. Acceptance Checklist

- [ ] `uv run black .` — no changes
- [ ] `uv run ruff check --fix .` — no issues
- [ ] `uv run mypy kryten_llm` — no issues
- [ ] `uv run pytest` — all tests pass (including the 3 new tests in `test_seed_reverse_order.py`)
- [ ] Manual smoke-test: run `kryten-llm --log-level DEBUG memory seed --logs "logs/*.log"` against
      at least 2 log files; confirm the INFO line `Total: … — starting LLM seed` is followed
      immediately by processing the file with the most recent mtime, and that the first reported
      `log date ~` value is the most recent date in that file
- [ ] CHANGELOG `[Unreleased]` block updated with the reverse-seed change under `### Changed`
- [ ] `pyproject.toml` version bumped to `0.10.3`

---

## 5. Deferred

- `--forward` flag to opt back in to chronological order — not needed for this corpus;
  defer until a concrete use case is raised.
- Heuristic path reverse ordering — explicitly out of scope (user request).
- Per-batch `batch_ts` anchoring to the batch's *last* message rather than first —
  would give a slightly more accurate `last_seen` for the final message in a window;
  low priority given the approximate nature of log-date reconstruction.
