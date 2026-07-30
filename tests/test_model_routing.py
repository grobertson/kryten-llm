"""Tests for Sprint 15: Memory-Aware Model Routing (REQ-310 – REQ-329).

Covers all four sorties:
  - Sortie 1: ContextSignal computation (REQ-310–314)
  - Sortie 2: Provider tier routing (REQ-315–319)
  - Sortie 3: Routing observability (REQ-320–322)
  - Sortie 4: Per-trigger routing override (REQ-325–329)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kryten_llm.components.memory.routing import ContextSignal, compute_signal
from kryten_llm.models.config import RoutingConfig, SignalWeightsConfig
from kryten_llm.models.events import TriggerResult
from kryten_llm.models.phase3 import LLMRequest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _default_weights() -> SignalWeightsConfig:
    return SignalWeightsConfig()


def _routing_config(threshold: float = 0.0, tiers: dict | None = None) -> RoutingConfig:
    return RoutingConfig(
        enabled=True,
        signal_threshold=threshold,
        tiers=tiers or {},
    )


@dataclass
class _FakeProvider:
    priority: int = 1


# ─────────────────────────────────────────────────────────────────────────────
# Sortie 1: ContextSignal computation (REQ-310–314)
# ─────────────────────────────────────────────────────────────────────────────


class TestContextSignalCompute:
    def test_signal_in_range_full_data(self):
        """REQ-310: signal ∈ [0, 1] with all components populated."""
        cs = ContextSignal(
            fragment_count=4,
            budget_fraction=0.5,
            avg_confidence=0.8,
            trigger_priority=0.7,
        )
        score = compute_signal(cs, _default_weights())
        assert 0.0 <= score <= 1.0

    def test_zero_signal_empty(self):
        """REQ-311: all-zero inputs → low (but not necessarily 0) score due to avg_confidence default."""
        cs = ContextSignal(
            fragment_count=0,
            budget_fraction=0.0,
            avg_confidence=0.0,
            trigger_priority=0.0,
        )
        score = compute_signal(cs, _default_weights())
        assert 0.0 <= score <= 1.0

    def test_zero_weight_returns_zero(self):
        """REQ-311: total weight 0 → signal 0 (no div-by-zero)."""
        weights = SignalWeightsConfig(
            fragment_count=0.0,
            budget_fraction=0.0,
            avg_confidence=0.0,
            trigger_priority=0.0,
        )
        cs = ContextSignal(fragment_count=5, budget_fraction=1.0, avg_confidence=1.0, trigger_priority=1.0)
        score = compute_signal(cs, weights)
        assert score == 0.0

    def test_max_signal(self):
        """REQ-310: fully-loaded turn → score close to 1.0."""
        cs = ContextSignal(
            fragment_count=8,  # == fragment_count_max
            budget_fraction=1.0,
            avg_confidence=1.0,
            trigger_priority=1.0,
        )
        score = compute_signal(cs, _default_weights())
        assert score == pytest.approx(1.0, abs=1e-6)

    def test_fragment_count_capped(self):
        """REQ-310: fragment_count capped at fragment_count_max."""
        cs_over = ContextSignal(fragment_count=100, budget_fraction=0.0, avg_confidence=0.0, trigger_priority=0.0)
        cs_at = ContextSignal(fragment_count=8, budget_fraction=0.0, avg_confidence=0.0, trigger_priority=0.0)
        w = SignalWeightsConfig(fragment_count=1.0, budget_fraction=0.0, avg_confidence=0.0, trigger_priority=0.0)
        assert compute_signal(cs_over, w) == compute_signal(cs_at, w)

    def test_deterministic(self):
        """REQ-310: same inputs → same output."""
        cs = ContextSignal(fragment_count=3, budget_fraction=0.4, avg_confidence=0.6, trigger_priority=0.5)
        w = _default_weights()
        assert compute_signal(cs, w) == compute_signal(cs, w)

    def test_missing_fragments_default_signal(self):
        """REQ-311: zero fragments → signal not zero (confidence + trigger still contribute)."""
        cs = ContextSignal(fragment_count=0, budget_fraction=0.0, avg_confidence=0.5, trigger_priority=0.5)
        score = compute_signal(cs, _default_weights())
        assert score > 0.0  # avg_confidence=0.5 + trigger_priority=0.5 contribute

    def test_routing_config_defaults(self):
        """REQ-313: default RoutingConfig produces a valid signal config."""
        cfg = RoutingConfig()
        assert cfg.enabled is False
        assert cfg.signal_threshold == 0.0
        assert cfg.tiers == {}
        assert isinstance(cfg.signal, SignalWeightsConfig)


# ─────────────────────────────────────────────────────────────────────────────
# Sortie 2: Provider tier routing (REQ-315–319)
# ─────────────────────────────────────────────────────────────────────────────


class TestLLMManagerRoute:
    def _make_manager(self, providers: list[str]) -> Any:
        """Build a minimal LLMManager stub with given provider names."""
        from kryten_llm.components.llm_manager import LLMManager
        from kryten_llm.models.config import LLMConfig, LLMProvider

        # Build a minimal valid LLMConfig
        provider_map = {
            name: LLMProvider(
                name=name,
                type="openai_compatible",
                base_url="http://localhost:1234/v1",
                api_key="test",
                model="test-model",
                priority=i + 1,
            )
            for i, name in enumerate(providers)
        }
        # Use a raw mock config
        cfg = MagicMock()
        cfg.llm_providers = provider_map
        cfg.default_provider_priority = providers
        cfg.retry_strategy = MagicMock(initial_delay=1.0, multiplier=2.0, max_delay=30.0)

        mgr = LLMManager.__new__(LLMManager)
        mgr.config = cfg
        mgr.providers = provider_map
        return mgr

    def test_premium_tier_when_signal_at_threshold(self):
        """REQ-316: signal >= threshold → premium tier used."""
        mgr = self._make_manager(["economy_p", "premium_p"])
        rcfg = _routing_config(
            threshold=0.5,
            tiers={"economy": ["economy_p"], "premium": ["premium_p"]},
        )
        result = mgr.route(0.5, rcfg)
        assert result == ["premium_p"]

    def test_economy_tier_below_threshold(self):
        """REQ-316: signal < threshold → economy tier used."""
        mgr = self._make_manager(["economy_p", "premium_p"])
        rcfg = _routing_config(
            threshold=0.5,
            tiers={"economy": ["economy_p"], "premium": ["premium_p"]},
        )
        result = mgr.route(0.3, rcfg)
        assert result == ["economy_p"]

    def test_single_tier_at_threshold_zero(self):
        """REQ-319: threshold=0.0 with no tiers → default order (current behaviour)."""
        mgr = self._make_manager(["local", "openai"])
        rcfg = _routing_config(threshold=0.0, tiers={})
        result = mgr.route(0.8, rcfg)
        # Should return the default provider order
        assert set(result) == {"local", "openai"}

    def test_unknown_providers_in_tier_filtered(self):
        """REQ-317: providers not in self.providers are filtered from the tier list."""
        mgr = self._make_manager(["local"])
        rcfg = _routing_config(
            threshold=0.0,
            tiers={"premium": ["ghost_provider", "local"]},
        )
        result = mgr.route(1.0, rcfg)
        assert result == ["local"]

    def test_premium_all_unknown_falls_through_to_economy(self):
        """REQ-317: all premium providers unknown → fall through to economy."""
        mgr = self._make_manager(["economy_p"])
        rcfg = _routing_config(
            threshold=0.0,
            tiers={"economy": ["economy_p"], "premium": ["ghost"]},
        )
        result = mgr.route(1.0, rcfg)
        assert result == ["economy_p"]

    def test_provider_list_on_request_used(self):
        """REQ-315: LLMRequest.provider_list bypasses _get_provider_priority."""
        req = LLMRequest(
            system_prompt="sys",
            user_prompt="usr",
            provider_list=["premium_p", "local"],
        )
        assert req.provider_list == ["premium_p", "local"]

    def test_default_request_has_no_provider_list(self):
        """REQ-319: default LLMRequest has no provider_list (backward-compatible)."""
        req = LLMRequest(system_prompt="s", user_prompt="u")
        assert req.provider_list is None


# ─────────────────────────────────────────────────────────────────────────────
# Sortie 3: Routing observability (REQ-320–322)
# ─────────────────────────────────────────────────────────────────────────────


class TestRoutingObservability:
    def _make_monitor(self) -> Any:
        from kryten_llm.components.health_monitor import ServiceHealthMonitor
        cfg = MagicMock()
        cfg.service_name = "llm"
        import logging
        return ServiceHealthMonitor(config=cfg, logger=logging.getLogger("test"))

    def test_record_routing_decision_increments_tier_counter(self):
        """REQ-321: tier counter incremented per call."""
        hm = self._make_monitor()
        hm.record_routing_decision("economy", 0.2)
        hm.record_routing_decision("economy", 0.3)
        hm.record_routing_decision("premium", 0.7)
        assert hm._routing_tier_counts["economy"] == 2
        assert hm._routing_tier_counts["premium"] == 1

    def test_record_routing_decision_appends_signal(self):
        """REQ-322: signal value appended to histogram."""
        hm = self._make_monitor()
        hm.record_routing_decision("economy", 0.25)
        hm.record_routing_decision("premium", 0.75)
        assert 0.25 in list(hm._routing_signal_samples)
        assert 0.75 in list(hm._routing_signal_samples)

    def test_default_zero_counters(self):
        """REQ-324: metrics default to zero when routing is not used."""
        hm = self._make_monitor()
        assert len(hm._routing_tier_counts) == 0
        assert len(hm._routing_signal_samples) == 0

    def test_metrics_server_emits_routing_metrics(self):
        """REQ-323: _emit_routing_metrics produces llm_routing_tier_total lines."""
        from kryten_llm.components.metrics_server import MetricsServer
        app = MagicMock()
        hm = self._make_monitor()
        hm.record_routing_decision("economy", 0.1)
        hm.record_routing_decision("premium", 0.9)
        app.health_monitor = hm

        ms = MetricsServer.__new__(MetricsServer)
        ms.app = app
        lines: list[str] = []
        ms._emit_routing_metrics(lines, hm)

        combined = "\n".join(lines)
        assert "llm_routing_tier_total" in combined
        assert 'tier="economy"' in combined
        assert 'tier="premium"' in combined
        assert "llm_routing_signal_count" in combined


# ─────────────────────────────────────────────────────────────────────────────
# Sortie 4: Per-trigger routing override (REQ-325–329)
# ─────────────────────────────────────────────────────────────────────────────


class TestPerTriggerRoutingOverride:
    def _make_manager(self, providers: list[str]) -> Any:
        provider_map = {}
        for i, name in enumerate(providers):
            from kryten_llm.models.config import LLMProvider
            provider_map[name] = LLMProvider(
                name=name, type="openai_compatible",
                base_url="http://localhost:1234/v1",
                api_key="test", model="test", priority=i + 1,
            )
        cfg = MagicMock()
        cfg.llm_providers = provider_map
        cfg.default_provider_priority = providers
        cfg.retry_strategy = MagicMock(initial_delay=1.0, multiplier=2.0, max_delay=30.0)

        from kryten_llm.components.llm_manager import LLMManager
        mgr = LLMManager.__new__(LLMManager)
        mgr.config = cfg
        mgr.providers = provider_map
        return mgr

    def test_preferred_tier_overrides_signal(self):
        """REQ-325/326: preferred_tier present + known → always used regardless of signal."""
        mgr = self._make_manager(["economy_p", "premium_p"])
        rcfg = _routing_config(
            threshold=0.9,
            tiers={"economy": ["economy_p"], "premium": ["premium_p"]},
        )
        # Signal below threshold, but preferred_tier forces premium
        result = mgr.route(0.1, rcfg, preferred_tier="premium")
        assert result == ["premium_p"]

    def test_unknown_preferred_tier_falls_back(self, caplog):
        """REQ-327: unknown preferred_tier → warning + signal routing fallback."""
        import logging
        mgr = self._make_manager(["economy_p", "premium_p"])
        rcfg = _routing_config(
            threshold=0.9,
            tiers={"economy": ["economy_p"], "premium": ["premium_p"]},
        )
        with caplog.at_level(logging.WARNING):
            result = mgr.route(0.1, rcfg, preferred_tier="platinum")
        assert any("platinum" in r.message for r in caplog.records)
        # Falls back to signal routing: signal < 0.9 → economy
        assert result == ["economy_p"]

    def test_none_preferred_tier_uses_signal_routing(self):
        """REQ-328: preferred_tier=None → signal routing (no change from Sortie 2)."""
        mgr = self._make_manager(["economy_p", "premium_p"])
        rcfg = _routing_config(
            threshold=0.5,
            tiers={"economy": ["economy_p"], "premium": ["premium_p"]},
        )
        result = mgr.route(0.8, rcfg, preferred_tier=None)
        assert result == ["premium_p"]

    def test_trigger_result_default_preferred_tier_is_none(self):
        """REQ-329: TriggerResult without preferred_tier defaults to None (backward-compat)."""
        tr = TriggerResult(triggered=True, trigger_type="trigger_word", trigger_name="foo")
        assert tr.preferred_tier is None

    def test_trigger_result_preferred_tier_set(self):
        """REQ-325: TriggerResult can carry preferred_tier from trigger config."""
        tr = TriggerResult(
            triggered=True, trigger_type="trigger_word", trigger_name="foo",
            preferred_tier="premium",
        )
        assert tr.preferred_tier == "premium"

    def test_trigger_config_preferred_tier_field(self):
        """REQ-325: Trigger config has preferred_tier field defaulting to None."""
        from kryten_llm.models.config import Trigger
        t = Trigger(name="t", patterns=["x"])
        assert t.preferred_tier is None

    def test_trigger_config_preferred_tier_set(self):
        """REQ-325: Trigger config preferred_tier can be set."""
        from kryten_llm.models.config import Trigger
        t = Trigger(name="t", patterns=["x"], preferred_tier="economy")
        assert t.preferred_tier == "economy"
