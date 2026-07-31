# SPEC-Sortie-1: Log Date Reconstructor

**Sprint**: 20.5 — Temporal-Accurate Bulk Import
**PRD**: [PRD-temporal-bulk-import.md](PRD-temporal-bulk-import.md)
**Status**: Planned
**Estimate**: 2h
**Depends on**: Nothing (pure utility module)
**Requirements**: REQ-445 – REQ-449

---

## 1. Overview

Create `kryten_llm/components/memory/log_date_utils.py` — an isolated, fully-tested
utility that assigns calendar dates to log lines given only time-of-day (`HH:MM:SS`)
values and a known end-date anchor.

No other code is modified in this sortie. The module is the foundation for Sortie 2.

---

## 2. Scope and Non-Goals

**In scope**: `log_date_utils.py`; unit tests in `tests/test_log_date_utils.py`.

**Non-goals**: wiring into `_parse_log_file` (Sortie 2); CLI changes (Sortie 3);
any interaction with the vector store.

---

## 3. Requirements

- **REQ-445** — `detect_midnight_crossings(times: list[int | None]) -> list[int]`
  returns a list of line indices where the time-of-day value at that index is more than
  3 600 seconds (1 hour) less than the preceding non-`None` value. Each index in the
  result marks the first line of a new day.
- **REQ-446** — `assign_dates(times: list[int | None], end_date: date) -> list[date]`
  uses the output of `detect_midnight_crossings` to assign a `date` to every line.
  Lines before the first crossing get `end_date - (crossing_count) days`; lines after the
  last crossing get `end_date`.
- **REQ-447** — Lines whose `time` is `None` (non-chat lines, blank lines) inherit the
  date of the nearest earlier line that has a non-`None` time; if no earlier line exists,
  they inherit `end_date - crossing_count` (the earliest assigned date).
- **REQ-448** — `time_str_to_seconds(t: str) -> int | None` converts `"HH:MM:SS"` to
  total seconds since midnight. Returns `None` for malformed input (no exception raised).
- **REQ-449** — All functions are pure (no I/O, no side effects). The module imports only
  the standard library (`datetime`).

---

## 4. Design

### 4.1 Module: `kryten_llm/components/memory/log_date_utils.py`

```python
"""
Assign calendar dates to chat-log lines that carry only HH:MM:SS timestamps.

Algorithm
---------
The file's modification time provides the date of the *last* line (end anchor).
Scanning forward, whenever a time-of-day value drops by more than 3 600 s relative
to the previous value a midnight crossing is detected.  Working backward from
end_date through the detected crossings assigns a date to every line.
"""
from __future__ import annotations

from datetime import date, timedelta

# Threshold in seconds: a backward jump larger than this is a midnight crossing.
_MIDNIGHT_THRESHOLD_S: int = 3_600  # 1 hour


def time_str_to_seconds(t: str) -> int | None:
    """Convert "HH:MM:SS" to seconds since midnight, or None on parse failure."""
    parts = t.split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59):
        return None
    return h * 3600 + m * 60 + s


def detect_midnight_crossings(times: list[int | None]) -> list[int]:
    """Return indices where a midnight crossing occurs (start of a new, earlier day).

    A crossing is detected when times[i] < (previous non-None value) - threshold.
    The returned index is *i* — the first line of the new day.
    """
    crossings: list[int] = []
    prev: int | None = None
    for i, t in enumerate(times):
        if t is None:
            continue
        if prev is not None and t < prev - _MIDNIGHT_THRESHOLD_S:
            crossings.append(i)
        prev = t
    return crossings


def assign_dates(times: list[int | None], end_date: date) -> list[date]:
    """Assign a calendar date to every line index.

    Parameters
    ----------
    times:    Per-line seconds-since-midnight values (None for non-chat lines).
    end_date: The calendar date of the last line in the file (mtime anchor).

    Returns
    -------
    A list of `date` objects, one per element of *times*.
    """
    crossings = detect_midnight_crossings(times)
    n = len(times)
    result: list[date] = [end_date] * n

    # crossings[k] is the first index of a day that is (k+1) days before end_date.
    # Everything from crossings[-1] to n-1 → end_date (day 0 from the end).
    # Everything from crossings[-2] to crossings[-1]-1 → end_date - 1, etc.
    # Everything from 0 to crossings[0]-1 → end_date - len(crossings).
    num_crossings = len(crossings)
    for k, cross_idx in enumerate(crossings):
        # Lines *before* this crossing belong to day = end_date - (num_crossings - k)
        days_back = num_crossings - k
        earlier_date = end_date - timedelta(days=days_back)
        # Fill from the previous crossing (or 0) up to (but not including) cross_idx
        start = crossings[k - 1] if k > 0 else 0
        for i in range(start, cross_idx):
            result[i] = earlier_date

    # Lines before the first crossing fill from 0 already handled above;
    # lines at/after the last crossing already default to end_date.

    # Forward-fill None-time lines: they inherit the date of the nearest earlier
    # timed line. Lines before *any* timed line keep their assigned date.
    last_date = end_date - timedelta(days=num_crossings)  # earliest assigned
    for i in range(n):
        if times[i] is not None:
            last_date = result[i]
        else:
            result[i] = last_date

    return result
```

### 4.2 Edge cases

| Situation | Behaviour |
|-----------|-----------|
| No crossings detected | All lines → `end_date` |
| All times are `None` | All lines → `end_date - 0` (end_date) |
| Duplicate/identical consecutive times | No crossing (Δ = 0) |
| Sub-hour within-day restart (time goes back < 1h) | No crossing (treated as same day) |
| Multi-day gap (no messages for > 24h) | One crossing detected; count off by # silent days (documented limitation) |

---

## 5. Tests: `tests/test_log_date_utils.py`

```python
from datetime import date, timedelta
from kryten_llm.components.memory.log_date_utils import (
    assign_dates, detect_midnight_crossings, time_str_to_seconds,
)

ANCHOR = date(2025, 3, 15)  # a Saturday

def secs(*hms): return [time_str_to_seconds(t) for t in hms]

class TestTimeStrToSeconds:
    def test_normal(self):        assert time_str_to_seconds("00:00:00") == 0
    def test_noon(self):          assert time_str_to_seconds("12:00:00") == 43200
    def test_end_of_day(self):    assert time_str_to_seconds("23:59:59") == 86399
    def test_malformed(self):     assert time_str_to_seconds("bad") is None
    def test_out_of_range(self):  assert time_str_to_seconds("25:00:00") is None

class TestDetectMidnightCrossings:
    def test_no_crossing(self):
        assert detect_midnight_crossings(secs("10:00:00", "10:30:00", "11:00:00")) == []

    def test_single_crossing(self):
        t = secs("23:59:00", "00:00:30")
        assert detect_midnight_crossings(t) == [1]

    def test_small_backward_jump_ignored(self):
        # 30-minute back-jump (server restart noise): no crossing
        t = secs("10:30:00", "10:00:00")
        assert detect_midnight_crossings(t) == []

    def test_nones_skipped(self):
        t = [time_str_to_seconds("23:59:00"), None, time_str_to_seconds("00:01:00")]
        assert detect_midnight_crossings(t) == [2]

class TestAssignDates:
    def test_single_day(self):
        times = secs("10:00:00", "10:30:00", "11:00:00")
        result = assign_dates(times, ANCHOR)
        assert all(d == ANCHOR for d in result)

    def test_two_days(self):
        # midnight crossing at index 2
        times = secs("23:00:00", "23:59:00", "00:01:00", "01:00:00")
        result = assign_dates(times, ANCHOR)
        yesterday = ANCHOR - timedelta(days=1)
        assert result[0] == yesterday
        assert result[1] == yesterday
        assert result[2] == ANCHOR
        assert result[3] == ANCHOR

    def test_none_line_inherits(self):
        t = [time_str_to_seconds("23:59:00"), None, time_str_to_seconds("00:01:00")]
        result = assign_dates(t, ANCHOR)
        yesterday = ANCHOR - timedelta(days=1)
        assert result[0] == yesterday
        assert result[1] == yesterday  # inherited from line 0
        assert result[2] == ANCHOR
```

---

## 6. Acceptance Criteria

- All tests in `test_log_date_utils.py` pass.
- `mypy` reports no errors in `log_date_utils.py` (strict mode compatible).
- `ruff` and `black` report clean.
- `log_date_utils.py` has zero imports outside `datetime` (standard library only).
