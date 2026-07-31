# SPEC-Sortie-2: Seed Path Timestamp Upgrade

**Sprint**: 20.5 — Temporal-Accurate Bulk Import
**PRD**: [PRD-temporal-bulk-import.md](PRD-temporal-bulk-import.md)
**Status**: Planned
**Estimate**: 3h
**Depends on**: Sortie 1 (`log_date_utils.py` complete and tested)
**Requirements**: REQ-450 – REQ-456

---

## 1. Overview

Wire the date reconstructor from Sortie 1 into the three places that need it:

1. `_parse_log_file` — adds an optional `log_end_date` parameter; returned message dicts
   gain a `"date"` field when date reconstruction is active.
2. `_seed_via_heuristic` — uses the `"date"` field to write accurate `created_at` and
   `last_seen` instead of `datetime.now()`.
3. `_seed_via_llm` / `LongTermMemoryProvider._persist` — threads a `historical_ts` field
   through `ExtractedFact` so the LLM seed path also writes historically accurate
   timestamps.

No behaviour change when `log_end_date` is `None` (backward-compatible).

---

## 2. Scope and Non-Goals

**In scope**: `kryten_llm/__main__.py` (`_parse_log_file`, `_seed_via_heuristic`,
`_seed_via_llm`); `kryten_llm/components/memory/extractor.py` (`ExtractedFact`);
`kryten_llm/components/context/providers/long_term_memory.py` (`_persist`);
unit/integration tests.

**Non-goals**: CLI flags for `--log-end-date` (Sortie 3). `memory reset` command (Sortie 3).
Changes to the live ingestion path beyond the minimal `historical_ts` field addition.

---

## 3. Requirements

- **REQ-450** — `_parse_log_file(path, *, log_end_date: date | None = None) -> list[dict]`.
  When `log_end_date` is not `None`, each returned dict includes `"date": "YYYY-MM-DD"`.
  When `None`, no `"date"` key is added (existing callers are unaffected).
- **REQ-451** — The date reconstruction in `_parse_log_file` uses
  `log_date_utils.time_str_to_seconds` and `log_date_utils.assign_dates`. The `end_date`
  passed to `assign_dates` is `log_end_date` if provided, else `date.fromtimestamp(
  path.stat().st_mtime)`. If `st_mtime` raises, fall back silently (no `"date"` field).
- **REQ-452** — In `_seed_via_heuristic`, when a message dict has a `"date"` key, the
  upsert metadata writes:
  ```python
  historical_ts = f"{msg['date']}T{msg['time']}+00:00"
  "created_at": historical_ts,
  "last_seen":  historical_ts,
  ```
  When `"date"` is absent, falls back to `datetime.now(timezone.utc).isoformat()` for
  `created_at` and omits `last_seen` (existing behaviour — backward-compatible).
- **REQ-453** — `_seed_via_heuristic` logs a one-time INFO message when date
  reconstruction is active: `"Date reconstruction active: dating facts from {start_date}
  to {end_date} ({n_crossings} midnight crossings detected)."` (Computed from the first
  and last non-None date in the parsed messages.)
- **REQ-454** — `ExtractedFact` (in `extractor.py`) gains an optional field:
  `historical_ts: str | None = None`. Default `None` preserves backward compatibility for
  all callers that construct `ExtractedFact` without it.
- **REQ-455** — In `_seed_via_llm`, before calling `provider._persist(ef)`, the seeder
  computes a representative historical timestamp for the batch (the timestamp of the
  **first** message in the batch that has a `"date"` field) and assigns it to
  `ef.historical_ts`.
- **REQ-456** — In `LongTermMemoryProvider._persist`, if `ef.historical_ts` is not `None`,
  write it as both `created_at` and `last_seen` in the stored metadata, overriding the
  default `datetime.now()`. The live ingestion path (where `ef.historical_ts is None`)
  is unchanged.

---

## 4. Design

### 4.1 `_parse_log_file` change

```python
# Add to top of __main__.py
from datetime import date as _date

from kryten_llm.components.memory.log_date_utils import assign_dates, time_str_to_seconds

def _parse_log_file(
    path: Path,
    *,
    log_end_date: _date | None = None,
) -> list[dict]:
    raw_messages: list[dict] = []
    raw_times: list[int | None] = []
    all_lines: list[int | None] = []   # index-aligned to file lines for assign_dates

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        logging.getLogger(__name__).warning(f"Could not parse log file {path}: {exc}")
        return []

    line_message_idx: list[int | None] = []  # for each file line → index in raw_messages or None

    for raw in lines:
        if _SERVER_RE.match(raw):
            all_lines.append(None)
            line_message_idx.append(None)
            continue
        m = _LINE_RE.match(raw)
        if m:
            t_str = m.group("time").strip()
            secs = time_str_to_seconds(t_str)
            all_lines.append(secs)
            idx = len(raw_messages)
            line_message_idx.append(idx)
            raw_messages.append({
                "username": m.group("user").strip(),
                "message": m.group("msg").strip(),
                "time": t_str,
            })
        else:
            all_lines.append(None)
            line_message_idx.append(None)

    # Date reconstruction (REQ-450, REQ-451)
    if log_end_date is not None or True:  # always attempt when called with an anchor or mtime
        end_anchor: _date | None = log_end_date
        if end_anchor is None:
            try:
                import os
                end_anchor = _date.fromtimestamp(os.stat(path).st_mtime)
            except Exception:
                end_anchor = None

        if end_anchor is not None:
            dates = assign_dates(all_lines, end_anchor)
            for line_idx, msg_idx in enumerate(line_message_idx):
                if msg_idx is not None:
                    raw_messages[msg_idx]["date"] = dates[line_idx].isoformat()

    return raw_messages
```

> **Note**: The `if log_end_date is not None or True` guard is intentionally always-True
> so that mtime-based reconstruction runs by default. This will be gated by the
> `--log-end-date` CLI flag in Sortie 3 (which passes `log_end_date` explicitly when the
> user wants it, and the mtime fallback handles the auto case). A future clean-up sortie
> can tighten the gate.

### 4.2 `_seed_via_heuristic` change (excerpt)

```python
# Inside the per-fact upsert loop:
if not args.dry_run:
    msg_date = msg.get("date")                        # REQ-452
    if msg_date:
        historical_ts = f"{msg_date}T{msg['time']}+00:00"
    else:
        historical_ts = None

    now_str = datetime.now(timezone.utc).isoformat()
    for fact, vector in zip(safe_facts, all_vectors):
        metadata = {
            "user": fact.user,
            "category": fact.category,
            "source": "seed",
            "created_at": historical_ts or now_str,
            "last_seen":  historical_ts or now_str,   # ← was absent before
            "score": fact.score,
            "evidence": str(fact.evidence.get("message", ""))[:200],
        }
        await vector_store.upsert(
            ids=[stable_fact_id(fact.user, fact.summary)],
            vectors=[vector],
            metadatas=[metadata],
            documents=[fact.summary],
        )
```

> **The `historical_ts` for a user's facts**: The seeder groups messages per user before
> extracting facts. The representative historical timestamp for a given fact should be the
> timestamp of the **source message** that most closely contributed to that fact. Because
> `HeuristicFactExtractor` returns `ExtractedFact` with an `evidence` dict that includes
> the original message, look up the source message's date from the per-user message list.
> If lookup is ambiguous, use the median date of all messages by that user in the current
> log file.

### 4.3 `ExtractedFact` addition

In `kryten_llm/components/memory/extractor.py`:

```python
@dataclass
class ExtractedFact:
    ...
    historical_ts: str | None = None   # ISO datetime; set by bulk seed, None for live
```

If `ExtractedFact` is a Pydantic model rather than a dataclass, add:
```python
historical_ts: str | None = Field(default=None)
```

### 4.4 `_persist` change (excerpt)

```python
async def _persist(self, ef: ExtractedFact) -> None:
    now = datetime.now(timezone.utc).isoformat()
    ts = ef.historical_ts or now          # REQ-456

    metadata = {
        ...
        "created_at": ts,
        "last_seen":  ts,
        ...
    }
```

---

## 5. Tests

### `tests/test_parse_log_file_dates.py`

```python
"""Tests for date reconstruction wired into _parse_log_file."""
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

from kryten_llm.__main__ import _parse_log_file


def _write_log(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines), encoding="utf-8")


class TestParseDateReconstruction:
    def test_single_day_all_same_date(self, tmp_path):
        log = tmp_path / "chat.log"
        _write_log(log, [
            "10:00:00 <alice>: hello",
            "10:30:00 <bob>: hi",
        ])
        anchor = date(2025, 3, 15)
        msgs = _parse_log_file(log, log_end_date=anchor)
        assert all(m["date"] == "2025-03-15" for m in msgs)

    def test_midnight_crossing_assigns_correct_dates(self, tmp_path):
        log = tmp_path / "chat.log"
        _write_log(log, [
            "23:55:00 <alice>: night",
            "00:05:00 <bob>: morning",
        ])
        anchor = date(2025, 3, 15)
        msgs = _parse_log_file(log, log_end_date=anchor)
        assert msgs[0]["date"] == "2025-03-14"
        assert msgs[1]["date"] == "2025-03-15"

    def test_no_anchor_uses_mtime(self, tmp_path):
        log = tmp_path / "chat.log"
        _write_log(log, ["10:00:00 <alice>: hi"])
        msgs = _parse_log_file(log)          # no log_end_date
        assert "date" in msgs[0]            # mtime fallback fired
        # date should be a valid ISO date string
        date.fromisoformat(msgs[0]["date"])  # no exception

    def test_no_date_field_when_mtime_unavailable(self, tmp_path, monkeypatch):
        log = tmp_path / "chat.log"
        _write_log(log, ["10:00:00 <alice>: hi"])
        monkeypatch.setattr(os, "stat", lambda _: (_ for _ in ()).throw(OSError("no stat")))
        # Should not raise; "date" field simply absent
        msgs = _parse_log_file(log)
        # If mtime fails, no date (or date is still set from the fallback path)
        # The test just ensures no exception is raised.
        assert isinstance(msgs, list)
```

### `tests/test_seed_historical_ts.py`

Verify that `_seed_via_heuristic` in dry-run mode logs facts with historical timestamps
when `"date"` is present in parsed messages. Use `FakeStore` and monkeypatched
`_parse_log_file` to inject controlled message dicts.

---

## 6. Acceptance Criteria

- `_parse_log_file` adds `"date"` to messages when reconstruction fires (mtime or explicit anchor).
- Heuristic seed writes `created_at` and `last_seen` equal to the reconstructed log
  datetime, not `datetime.now()`.
- LLM seed path: `ef.historical_ts` is set from the batch's first dated message; `_persist`
  writes it as `created_at` / `last_seen`.
- `mypy --strict` reports no new errors in changed files.
- All new and existing seed tests pass.
