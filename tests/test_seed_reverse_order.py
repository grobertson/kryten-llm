"""Sprint 24, REQ-496 — _seed_via_llm processes newest file / newest batches first."""

from __future__ import annotations

import time
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
        self._extractor = _FakeExtractor()
        self._ext_cfg = MagicMock()
        self._ext_cfg.cadence.batch_max_size = 2
        self._observe_exclude: set[str] = set()
        self._store = AsyncMock()
        self._store.count = AsyncMock(return_value=0)

    async def _persist(self, ef: _FakeExtractedFact) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_messages(n: int, date_str: str) -> list[dict]:
    """Build *n* dummy message dicts tagged with *date_str*."""
    return [
        {
            "username": "user",
            "message": f"msg{i}",
            "time": f"10:{i % 60:02d}:00",
            "date": date_str,
        }
        for i in range(n)
    ]


def _make_args(**kwargs) -> MagicMock:
    args = MagicMock()
    args.dry_run = False
    args._log_end_date_parsed = None
    for k, v in kwargs.items():
        setattr(args, k, v)
    return args


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_newest_file_processed_first(tmp_path: Path) -> None:
    """Files with a later mtime must be processed before files with an earlier mtime.

    REQ-491.
    """
    old_file = tmp_path / "old.log"
    new_file = tmp_path / "new.log"
    old_file.write_text("placeholder")
    time.sleep(0.05)  # ensure distinct mtimes
    new_file.write_text("placeholder")
    # new_file.stat().st_mtime > old_file.stat().st_mtime

    old_msgs = _make_messages(4, "2024-01-01")
    new_msgs = _make_messages(4, "2024-06-01")
    file_map = {old_file: old_msgs, new_file: new_msgs}

    fake_provider = _FakeProvider()

    with patch(
        "kryten_llm.__main__._parse_log_file",
        side_effect=lambda path, **_kw: list(file_map[path]),
    ):
        with patch(
            "kryten_llm.components.context.providers.long_term_memory"
            ".LongTermMemoryProvider.from_config",
            return_value=fake_provider,
        ):
            # Pass files in old-first order; _seed_via_llm must re-sort.
            await _seed_via_llm(_make_args(), MagicMock(), {}, [old_file, new_file], MagicMock())

    # 4 messages / batch_size 2 = 2 batches per file → 4 total extractor calls.
    assert (
        len(fake_provider._extractor.calls) == 4
    ), f"Expected 4 extractor calls, got {len(fake_provider._extractor.calls)}"

    # First two calls must come from the new (2024-06-01) file.
    for call in fake_provider._extractor.calls[:2]:
        assert all(
            m["date"] == "2024-06-01" for m in call
        ), f"Expected newest-file batches first; got dates: {[m['date'] for m in call]}"

    # Last two calls must come from the old (2024-01-01) file.
    for call in fake_provider._extractor.calls[2:]:
        assert all(
            m["date"] == "2024-01-01" for m in call
        ), f"Expected oldest-file batches last; got dates: {[m['date'] for m in call]}"


@pytest.mark.asyncio
async def test_newest_batch_within_file_processed_first(tmp_path: Path) -> None:
    """Within a single file the highest-indexed batch must be extracted first.

    REQ-492.
    """
    log_file = tmp_path / "test.log"
    log_file.write_text("placeholder")

    # 6 messages, batch_size=2 → batches [0:2], [2:4], [4:6].
    # Expected extraction order: [4:6] → [2:4] → [0:2].
    msgs = [
        {"username": "u", "message": f"m{i}", "time": f"10:0{i}:00", "date": "2024-03-01"}
        for i in range(6)
    ]

    fake_provider = _FakeProvider()

    with patch("kryten_llm.__main__._parse_log_file", return_value=msgs):
        with patch(
            "kryten_llm.components.context.providers.long_term_memory"
            ".LongTermMemoryProvider.from_config",
            return_value=fake_provider,
        ):
            await _seed_via_llm(_make_args(), MagicMock(), {}, [log_file], MagicMock())

    calls = fake_provider._extractor.calls
    assert len(calls) == 3, f"Expected 3 extractor calls, got {len(calls)}"

    # First extracted batch: messages m4 and m5 (newest window).
    assert calls[0][0]["message"] == "m4", f"Expected m4 first; got {calls[0][0]['message']}"
    assert calls[0][1]["message"] == "m5", f"Expected m5 second; got {calls[0][1]['message']}"

    # Last extracted batch: messages m0 and m1 (oldest window).
    assert (
        calls[2][0]["message"] == "m0"
    ), f"Expected m0 in last batch; got {calls[2][0]['message']}"
    assert (
        calls[2][1]["message"] == "m1"
    ), f"Expected m1 in last batch; got {calls[2][1]['message']}"


@pytest.mark.asyncio
async def test_each_batch_is_internally_chronological(tmp_path: Path) -> None:
    """Each batch passed to the extractor must be in forward (chronological) order.

    REQ-492: batches are reversed in submission order but each window stays chronological
    so the LLM extractor receives natural conversation context.
    """
    log_file = tmp_path / "test.log"
    log_file.write_text("placeholder")

    msgs = [
        {"username": "u", "message": f"m{i}", "time": f"10:{i:02d}:00", "date": "2024-03-01"}
        for i in range(8)
    ]

    fake_provider = _FakeProvider()

    with patch("kryten_llm.__main__._parse_log_file", return_value=msgs):
        with patch(
            "kryten_llm.components.context.providers.long_term_memory"
            ".LongTermMemoryProvider.from_config",
            return_value=fake_provider,
        ):
            await _seed_via_llm(_make_args(), MagicMock(), {}, [log_file], MagicMock())

    for idx, call in enumerate(fake_provider._extractor.calls):
        times = [m["time"] for m in call]
        assert times == sorted(times), f"Batch {idx} was not in chronological order: {times}"
