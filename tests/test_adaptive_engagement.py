"""Tests for Sprint 11: Adaptive Engagement (REQ-220–249).

Covers:
* EngagementSignals + compute() — score formula, weights, bias, graceful degradation
* TriggerEngine pre-check — novelty/mood gates, cold-start, no store queries
* TriggerEngine eagerness gate — score threshold, force_interval, default behavior
* Per-user bias — max_bias=1 neutral, depth boost, cap at 1.0
* Service.py forwarding of signals to trigger engine (signal cache update)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kryten_llm.components.memory.engagement import EngagementSignals, EngagementWeights, compute


# ---------------------------------------------------------------------------
# Sortie 1: Engagement score formula (REQ-220–225)
# ---------------------------------------------------------------------------


class TestEngagementScore:
    """compute() — formula, normalization, graceful degradation."""

    def _w(self, **kw) -> EngagementWeights:
        return EngagementWeights(
            **{**dict(novelty=0.5, topical=0.3, mood=0.1, importance=0.1, max_bias=1.0), **kw}
        )

    def test_all_zero_signals_returns_zero(self):
        signals = EngagementSignals()
        assert compute(signals, self._w()) == 0.0

    def test_full_signals_equal_weights_score_in_range(self):
        signals = EngagementSignals(
            novelty=0.8, topical_max_sim=0.6, mood_cosine=0.5, max_importance=0.7
        )
        score = compute(signals, self._w())
        assert 0.0 <= score <= 1.0

    def test_only_novelty_present(self):
        signals = EngagementSignals(novelty=1.0)
        score = compute(signals, self._w(novelty=1.0, topical=0.0, mood=0.0, importance=0.0))
        assert score == pytest.approx(1.0)

    def test_missing_signals_degrade_gracefully(self):
        """Absent topical/mood/importance don't over-inflate score (REQ-222)."""
        signals = EngagementSignals(novelty=0.5)
        score = compute(signals, self._w())
        # Only novelty contributes; other signals = 0 → score should be modest
        assert score < 0.5

    def test_zero_weights_returns_zero(self):
        """No divide-by-zero when all weights are 0."""
        signals = EngagementSignals(novelty=1.0, topical_max_sim=1.0)
        score = compute(signals, self._w(novelty=0, topical=0, mood=0, importance=0))
        assert score == 0.0

    def test_score_capped_at_one(self):
        signals = EngagementSignals(
            novelty=1.0, topical_max_sim=1.0, mood_cosine=1.0, max_importance=1.0
        )
        score = compute(signals, self._w(novelty=1.0, topical=1.0, mood=1.0, importance=1.0))
        assert score <= 1.0

    def test_score_floor_is_zero(self):
        signals = EngagementSignals(novelty=-5.0)  # invalid but shouldn't go negative
        score = compute(signals, self._w(novelty=1.0, topical=0.0, mood=0.0, importance=0.0))
        assert score >= 0.0


# ---------------------------------------------------------------------------
# Sortie 4: Per-user bias (REQ-245–249)
# ---------------------------------------------------------------------------


class TestPerUserBias:
    """Multiplicative bias from user_depth (REQ-245–249)."""

    def test_max_bias_one_no_change(self):
        """max_bias=1.0 → score unchanged regardless of user_depth (REQ-247)."""
        signals = EngagementSignals(novelty=0.5, user_depth=1.0)
        w = EngagementWeights(novelty=1.0, topical=0.0, mood=0.0, importance=0.0, max_bias=1.0)
        score_biased = compute(signals, w)
        signals_no_depth = EngagementSignals(novelty=0.5, user_depth=0.0)
        score_plain = compute(signals_no_depth, w)
        assert score_biased == pytest.approx(score_plain)

    def test_max_bias_boosts_known_user(self):
        """Known user (user_depth > 0) gets a higher final score (REQ-245)."""
        base_signals = EngagementSignals(novelty=0.5)
        biased_signals = EngagementSignals(novelty=0.5, user_depth=1.0)
        w = EngagementWeights(novelty=1.0, topical=0.0, mood=0.0, importance=0.0, max_bias=2.0)
        assert compute(biased_signals, w) > compute(base_signals, w)

    def test_unknown_user_no_bias(self):
        """user_depth=0 → bias = 1.0 → score unchanged (REQ-249)."""
        signals = EngagementSignals(novelty=0.5, user_depth=0.0)
        w = EngagementWeights(novelty=1.0, topical=0.0, mood=0.0, importance=0.0, max_bias=3.0)
        score = compute(signals, w)
        w_no_bias = EngagementWeights(
            novelty=1.0, topical=0.0, mood=0.0, importance=0.0, max_bias=1.0
        )
        assert score == pytest.approx(compute(signals, w_no_bias))

    def test_biased_score_capped_at_one(self):
        """Even with high bias and full signals, score ≤ 1.0 (REQ-245)."""
        signals = EngagementSignals(novelty=1.0, user_depth=1.0)
        w = EngagementWeights(novelty=1.0, topical=0.0, mood=0.0, importance=0.0, max_bias=5.0)
        assert compute(signals, w) <= 1.0


# ---------------------------------------------------------------------------
# Sortie 2: TriggerEngine pre-check (REQ-230–235)
# ---------------------------------------------------------------------------


def _make_trigger_config(
    *,
    ap_enabled: bool = True,
    precheck_enabled: bool = True,
    min_novelty: float = 0.0,
    min_mood: float = 0.0,
    eagerness: float = 0.0,
    force_interval: int = 0,
    base_interval: int = 1,
):
    """Build a minimal config MagicMock for TriggerEngine tests."""
    from kryten_llm.models.config import AutoParticipationConfig

    cfg = MagicMock()
    cfg.personality.name_variations = []
    cfg.personality.character_name = "Bot"
    cfg.triggers = []
    cfg.context.chat_history_size = 10
    cfg.context.max_chat_history_in_prompt = 5

    ap = MagicMock()
    ap.enabled = ap_enabled
    ap.base_message_interval = base_interval
    ap.probability_range = 0.0
    ap.eagerness = eagerness
    ap.force_interval = force_interval
    ap.precheck.enabled = precheck_enabled
    ap.precheck.min_novelty = min_novelty
    ap.precheck.min_mood_cosine = min_mood
    ap.engagement.novelty = 0.5
    ap.engagement.topical = 0.3
    ap.engagement.mood = 0.1
    ap.engagement.importance = 0.1
    ap.engagement.max_bias = 1.0
    cfg.auto_participation = ap
    return cfg


def _make_engine(config):
    from kryten_llm.components.trigger_engine import TriggerEngine

    return TriggerEngine(config)


def _msg(text: str = "hello") -> dict:
    return {"username": "testuser", "msg": text, "time": 1000, "meta": {"rank": 1}}


class TestPrecheck:
    """Silent-path pre-check (REQ-230–235)."""

    def test_precheck_disabled_always_passes(self):
        engine = _make_engine(_make_trigger_config(precheck_enabled=False, min_novelty=0.9))
        # Even with high novelty threshold, disabled → pass
        engine._last_memory_signals = EngagementSignals(novelty=0.0)
        assert engine._precheck_passes() is True

    def test_cold_start_no_signals_passes(self):
        """No cached signals → pre-check passes (REQ-233)."""
        engine = _make_engine(_make_trigger_config(precheck_enabled=True, min_novelty=0.9))
        assert engine._last_memory_signals is None
        assert engine._precheck_passes() is True

    def test_low_novelty_fails_precheck(self):
        engine = _make_engine(_make_trigger_config(precheck_enabled=True, min_novelty=0.5))
        engine._last_memory_signals = EngagementSignals(novelty=0.2)
        assert engine._precheck_passes() is False

    def test_high_novelty_passes_precheck(self):
        engine = _make_engine(_make_trigger_config(precheck_enabled=True, min_novelty=0.5))
        engine._last_memory_signals = EngagementSignals(novelty=0.8)
        assert engine._precheck_passes() is True

    def test_low_mood_fails_precheck(self):
        engine = _make_engine(_make_trigger_config(precheck_enabled=True, min_mood=0.5))
        engine._last_memory_signals = EngagementSignals(mood_cosine=0.1)
        assert engine._precheck_passes() is False

    def test_min_thresholds_zero_always_passes(self):
        """Both thresholds = 0 → any signal value passes (current behavior, REQ-232)."""
        engine = _make_engine(
            _make_trigger_config(precheck_enabled=True, min_novelty=0.0, min_mood=0.0)
        )
        engine._last_memory_signals = EngagementSignals(novelty=0.0, mood_cosine=0.0)
        assert engine._precheck_passes() is True

    async def test_failed_precheck_no_trigger(self):
        """When pre-check fails, auto-participation does NOT fire (REQ-230)."""
        engine = _make_engine(
            _make_trigger_config(precheck_enabled=True, min_novelty=0.8, base_interval=1)
        )
        engine._last_memory_signals = EngagementSignals(novelty=0.1)  # below threshold
        result = await engine.check_triggers(_msg())
        assert result.triggered is False

    async def test_passed_precheck_allows_trigger(self):
        """When pre-check passes on a count-threshold turn, auto-participation fires."""
        engine = _make_engine(
            _make_trigger_config(precheck_enabled=True, min_novelty=0.3, base_interval=1)
        )
        engine._last_memory_signals = EngagementSignals(novelty=0.9)  # above threshold
        result = await engine.check_triggers(_msg())
        assert result.triggered is True
        assert result.trigger_type == "auto_participant"


# ---------------------------------------------------------------------------
# Sortie 3: Eagerness gate (REQ-240–244)
# ---------------------------------------------------------------------------


class TestEagernessGate:
    """Score-gated auto-participation (REQ-240–244)."""

    async def test_eagerness_zero_default_behavior(self):
        """eagerness=0 → all count-threshold turns fire regardless of score (REQ-241)."""
        engine = _make_engine(_make_trigger_config(eagerness=0.0, base_interval=1))
        engine._last_memory_signals = EngagementSignals(novelty=0.0)  # very low score
        result = await engine.check_triggers(_msg())
        assert result.triggered is True

    async def test_high_eagerness_low_score_silent(self):
        """eagerness=0.9 with score≈0 → stay silent (REQ-240)."""
        engine = _make_engine(_make_trigger_config(eagerness=0.9, base_interval=1))
        engine._last_memory_signals = EngagementSignals(novelty=0.0, topical_max_sim=0.0)
        result = await engine.check_triggers(_msg())
        assert result.triggered is False

    async def test_high_eagerness_high_score_fires(self):
        """eagerness=0.3 with high score → fires (REQ-240)."""
        engine = _make_engine(_make_trigger_config(eagerness=0.3, base_interval=1))
        # novelty=1.0 with novelty_weight=0.5 → score = 0.5 (above 0.3)
        engine._last_memory_signals = EngagementSignals(novelty=1.0)
        result = await engine.check_triggers(_msg())
        assert result.triggered is True

    async def test_force_interval_fires_after_consecutive_misses(self):
        """After force_interval consecutive misses, bot fires regardless of score (REQ-243)."""
        engine = _make_engine(
            _make_trigger_config(eagerness=0.99, force_interval=3, base_interval=1)
        )
        engine._last_memory_signals = EngagementSignals(novelty=0.0)

        # First 2 misses → silent
        for _ in range(2):
            engine.messages_since_last_trigger = 1
            result = await engine.check_triggers(_msg())
            assert result.triggered is False

        # 3rd miss → force fires
        engine.messages_since_last_trigger = 1
        result = await engine.check_triggers(_msg())
        assert result.triggered is True

    async def test_force_interval_zero_never_forces(self):
        """force_interval=0 → no forced speak (REQ-243 disabled path)."""
        engine = _make_engine(
            _make_trigger_config(eagerness=0.99, force_interval=0, base_interval=1)
        )
        engine._last_memory_signals = EngagementSignals(novelty=0.0)
        for _ in range(10):
            engine.messages_since_last_trigger = 1
            result = await engine.check_triggers(_msg())
            assert result.triggered is False

    async def test_score_misses_reset_after_success(self):
        """_score_misses resets to 0 when a turn passes the eagerness gate."""
        engine = _make_engine(
            _make_trigger_config(eagerness=0.3, force_interval=5, base_interval=1)
        )
        # First, accumulate some misses
        engine._last_memory_signals = EngagementSignals(novelty=0.0)
        for _ in range(2):
            engine.messages_since_last_trigger = 1
            await engine.check_triggers(_msg())

        assert engine._score_misses == 2

        # Now supply a high-score signal → should fire and reset misses
        engine._last_memory_signals = EngagementSignals(novelty=1.0)
        engine.messages_since_last_trigger = 1
        result = await engine.check_triggers(_msg())
        assert result.triggered is True
        assert engine._score_misses == 0

    async def test_rate_limits_not_bypassed(self):
        """The score gate never bypasses traditional trigger/rate-limit logic (REQ-242).
        This test verifies that mentions still go through the standard path regardless."""
        from kryten_llm.components.trigger_engine import TriggerEngine

        config = _make_trigger_config(eagerness=0.99)
        config.personality.name_variations = ["bot"]
        engine = TriggerEngine(config)
        engine._last_memory_signals = EngagementSignals(novelty=0.0)  # score would fail

        # A mention should still fire (it's not gated by the score)
        result = await engine.check_triggers(_msg("hey bot, what's up?"))
        assert result.triggered is True
        assert result.trigger_type == "mention"


# ---------------------------------------------------------------------------
# Signal cache (set_memory_signals)
# ---------------------------------------------------------------------------


class TestSignalCache:
    """TriggerEngine.set_memory_signals wiring (REQ-231)."""

    def test_set_and_retrieve_signals(self):
        engine = _make_engine(_make_trigger_config())
        signals = EngagementSignals(novelty=0.7, mood_cosine=0.3)
        engine.set_memory_signals(signals)
        assert engine._last_memory_signals is signals

    def test_set_none_clears_signals(self):
        engine = _make_engine(_make_trigger_config())
        engine._last_memory_signals = EngagementSignals(novelty=0.5)
        engine.set_memory_signals(None)
        assert engine._last_memory_signals is None

    def test_precheck_uses_set_signals(self):
        engine = _make_engine(_make_trigger_config(precheck_enabled=True, min_novelty=0.6))
        engine.set_memory_signals(EngagementSignals(novelty=0.3))
        assert engine._precheck_passes() is False  # below threshold
        engine.set_memory_signals(EngagementSignals(novelty=0.9))
        assert engine._precheck_passes() is True  # above threshold

    def test_health_monitor_records_precheck(self):
        monitor = MagicMock()
        engine = _make_engine(_make_trigger_config(precheck_enabled=True, min_novelty=0.5))
        engine.set_health_monitor(monitor)
        engine.set_memory_signals(EngagementSignals(novelty=0.1))
        engine._precheck_passes()
        monitor.record_engagement_precheck.assert_called_with(False)
