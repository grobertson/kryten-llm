"""Sprint 20.5, Sortie 1 — log_date_utils unit tests (REQ-445–449)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from kryten_llm.components.memory.log_date_utils import (
    assign_dates,
    detect_midnight_crossings,
    time_str_to_seconds,
)

ANCHOR = date(2025, 3, 15)  # a Saturday


def secs(*hms: str) -> list[int | None]:
    return [time_str_to_seconds(t) for t in hms]


class TestTimeStrToSeconds:
    def test_midnight(self):
        assert time_str_to_seconds("00:00:00") == 0

    def test_noon(self):
        assert time_str_to_seconds("12:00:00") == 43200

    def test_end_of_day(self):
        assert time_str_to_seconds("23:59:59") == 86399

    def test_malformed(self):
        assert time_str_to_seconds("bad") is None

    def test_out_of_range_hour(self):
        assert time_str_to_seconds("25:00:00") is None

    def test_out_of_range_minute(self):
        assert time_str_to_seconds("01:60:00") is None

    def test_non_integer(self):
        assert time_str_to_seconds("aa:bb:cc") is None


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

    def test_two_crossings(self):
        # Day 1 → Day 2 → Day 3
        t = secs("23:50:00", "00:05:00", "23:55:00", "00:10:00")
        assert detect_midnight_crossings(t) == [1, 3]


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

    def test_none_line_inherits_previous_date(self):
        t = [time_str_to_seconds("23:59:00"), None, time_str_to_seconds("00:01:00")]
        result = assign_dates(t, ANCHOR)
        yesterday = ANCHOR - timedelta(days=1)
        assert result[0] == yesterday
        assert result[1] == yesterday   # inherited from line 0
        assert result[2] == ANCHOR

    def test_none_before_any_time_gets_earliest_date(self):
        t = [None, time_str_to_seconds("23:59:00"), time_str_to_seconds("00:01:00")]
        result = assign_dates(t, ANCHOR)
        yesterday = ANCHOR - timedelta(days=1)
        assert result[0] == yesterday   # no earlier timed line; gets earliest date
        assert result[1] == yesterday
        assert result[2] == ANCHOR

    def test_three_days(self):
        times = secs(
            "23:00:00",  # day -2
            "00:01:00",  # day -1 (crossing 1)
            "23:00:00",  # day -1
            "00:01:00",  # day 0 (crossing 2)
            "12:00:00",  # day 0
        )
        result = assign_dates(times, ANCHOR)
        assert result[0] == ANCHOR - timedelta(days=2)
        assert result[1] == ANCHOR - timedelta(days=1)
        assert result[2] == ANCHOR - timedelta(days=1)
        assert result[3] == ANCHOR
        assert result[4] == ANCHOR

    def test_empty_returns_empty(self):
        assert assign_dates([], ANCHOR) == []
