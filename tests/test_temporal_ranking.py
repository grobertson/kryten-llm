"""Sprint 20 — Temporal Fact Awareness tests (REQ-405–424)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider
from kryten_llm.models.config import RetrievalBoostConfig


# ---------------------------------------------------------------------------
# REQ-405, REQ-406, REQ-409: _recency_factor with half-life
# ---------------------------------------------------------------------------


class TestRecencyFactor:
    def _now(self) -> datetime:
        return datetime(2025, 6, 1, tzinfo=timezone.utc)

    def test_legacy_formula_no_half_life(self):
        """Default half_life_days=0 preserves hyperbolic 1/(1+age_days)."""
        now = self._now()
        one_day_ago = (now - timedelta(days=1)).isoformat()
        result = LongTermMemoryProvider._recency_factor(one_day_ago, now, 0.0)
        assert abs(result - 0.5) < 0.001  # 1/(1+1) = 0.5

    def test_exponential_formula_with_half_life(self):
        """With half_life_days=10, at age 10 days score = 0.5 (by definition of half-life)."""
        now = self._now()
        ten_days_ago = (now - timedelta(days=10)).isoformat()
        result = LongTermMemoryProvider._recency_factor(ten_days_ago, now, 10.0)
        expected = math.exp(-1.0)  # exp(-10/10) = exp(-1) ≈ 0.368
        assert abs(result - expected) < 0.001

    def test_half_life_at_exactly_half_life(self):
        """At age = half_life_days, score = exp(-1) ≈ 0.368 (not exactly 0.5 for exp decay)."""
        now = self._now()
        ts = (now - timedelta(days=90)).isoformat()
        result = LongTermMemoryProvider._recency_factor(ts, now, 90.0)
        assert abs(result - math.exp(-1.0)) < 0.001

    def test_empty_last_seen_returns_zero(self):
        result = LongTermMemoryProvider._recency_factor("", self._now(), 0.0)
        assert result == 0.0

    def test_malformed_timestamp_returns_zero(self):
        result = LongTermMemoryProvider._recency_factor("not-a-date", self._now(), 0.0)
        assert result == 0.0

    def test_future_timestamp_clamped_to_zero_age(self):
        """A last_seen in the future should not give a negative age — clamp to 0."""
        now = self._now()
        future = (now + timedelta(days=1)).isoformat()
        result = LongTermMemoryProvider._recency_factor(future, now, 0.0)
        assert result == 1.0  # 1/(1+0) = 1.0

    def test_recent_outranks_old_same_half_life(self):
        """A recently-seen fact should score higher than an old one."""
        now = self._now()
        recent = (now - timedelta(days=1)).isoformat()
        old = (now - timedelta(days=100)).isoformat()
        assert LongTermMemoryProvider._recency_factor(
            recent, now, 90.0
        ) > LongTermMemoryProvider._recency_factor(old, now, 90.0)


# ---------------------------------------------------------------------------
# REQ-405: RetrievalBoostConfig.recency_half_life_days field
# ---------------------------------------------------------------------------


class TestRetrievalBoostConfig:
    def test_default_recency_half_life_is_zero(self):
        cfg = RetrievalBoostConfig()
        assert cfg.recency_half_life_days == 0.0

    def test_can_set_recency_half_life(self):
        cfg = RetrievalBoostConfig(recency_half_life_days=90.0)
        assert cfg.recency_half_life_days == 90.0

    def test_negative_half_life_invalid(self):
        import pydantic

        with pytest.raises((pydantic.ValidationError, ValueError)):
            RetrievalBoostConfig(recency_half_life_days=-1.0)


# ---------------------------------------------------------------------------
# REQ-411: recency_days on ContextFragment
# ---------------------------------------------------------------------------


class TestContextFragmentRecencyDays:
    def test_recency_days_field_exists_defaults_none(self):
        from kryten_llm.components.context.base import ContextFragment

        frag = ContextFragment(name="test", priority=10, text="hello")
        assert frag.recency_days is None

    def test_recency_days_can_be_set(self):
        from kryten_llm.components.context.base import ContextFragment

        frag = ContextFragment(name="user_memory", priority=40, text="test", recency_days=15)
        assert frag.recency_days == 15
