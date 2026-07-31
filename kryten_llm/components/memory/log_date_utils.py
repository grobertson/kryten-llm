"""Sprint 20.5, Sortie 1 — Log date reconstruction utility (REQ-445–449).

Assigns calendar dates to chat-log lines that carry only HH:MM:SS timestamps.
The file's modification time provides the anchor date for the *last* line.
Scanning forward, a backward time-of-day jump > 3600 s indicates a midnight crossing.
"""
from __future__ import annotations

from datetime import date, timedelta

# Threshold in seconds: a backward jump larger than this is a midnight crossing.
_MIDNIGHT_THRESHOLD_S: int = 3_600  # 1 hour


def time_str_to_seconds(t: str) -> int | None:
    """Convert ``"HH:MM:SS"`` to seconds since midnight, or ``None`` on parse failure."""
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
    """Return indices where a midnight crossing occurs (start of an earlier day).

    A crossing is detected when ``times[i] < previous_non_None_value - threshold``.
    The returned index *i* is the first line of the new (earlier) day.
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
    times:
        Per-line seconds-since-midnight values (``None`` for non-chat lines).
    end_date:
        The calendar date of the last line in the file (mtime anchor).

    Returns
    -------
    A list of :class:`date` objects, one per element of *times*.
    """
    crossings = detect_midnight_crossings(times)
    n = len(times)
    num_crossings = len(crossings)
    result: list[date] = [end_date] * n

    # Fill day-bands between consecutive crossings.
    # Lines from crossings[k] up to (but not including) crossings[k+1] are all one day.
    # Lines before crossings[0] are `end_date - num_crossings` days earlier.
    # Lines from crossings[-1] onwards are `end_date`.
    for k, cross_idx in enumerate(crossings):
        days_back = num_crossings - k
        earlier_date = end_date - timedelta(days=days_back)
        start = crossings[k - 1] if k > 0 else 0
        for i in range(start, cross_idx):
            result[i] = earlier_date

    # Forward-fill None-time lines from the nearest earlier timed line.
    if num_crossings > 0:
        earliest = end_date - timedelta(days=num_crossings)
    else:
        earliest = end_date
    last_date = earliest
    for i in range(n):
        if times[i] is not None:
            last_date = result[i]
        else:
            result[i] = last_date

    return result
