"""Tests for Sprint 18: Confidence Calibration & Decay Hardening (REQ-370 – REQ-384).

Covers all three sorties:
  - Sortie 1: Calibration metric (REQ-370–374)
  - Sortie 2: Importance-gated contradiction decay (REQ-375–379)
  - Sortie 3: Temporal confidence drift sweep (REQ-380–384)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.eval.harness import EvalFact, FakeEmbedder, FakeStore, make_provider, seed_store
from tests.eval.scorers import CalibrationReport, score_calibration


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _ts(days_ago: float) -> str:
    """Return an ISO timestamp *days_ago* days before now."""
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return ts.isoformat()


def _record(fact_id: str, confidence: float, importance: int, last_seen_days: float = 0.0) -> dict:
    """Build a minimal fake store record."""
    return {
        "id": fact_id,
        "document": f"fact about {fact_id}",
        "metadata": {
            "confidence": confidence,
            "importance": importance,
            "user": "alice",
            "last_seen": _ts(last_seen_days),
            "created_at": _ts(last_seen_days + 1),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Sortie 1: Calibration metric (REQ-370–374)
# ─────────────────────────────────────────────────────────────────────────────


class TestCalibrationScorer:
    def test_well_calibrated_passes_baseline(self):
        """REQ-373: high-confidence facts have higher mean importance → passes."""
        records = [
            _record("h1", confidence=0.9, importance=8),
            _record("h2", confidence=0.85, importance=7),
            _record("m1", confidence=0.6, importance=3),
            _record("m2", confidence=0.55, importance=2),
            _record("l1", confidence=0.3, importance=1),
            _record("l2", confidence=0.2, importance=1),
        ]
        report = score_calibration(records)
        assert report.passes_baseline, f"Well-calibrated fixture should pass: {report.summary()}"
        assert report.n_facts == 6

    def test_inverted_calibration_fails_baseline(self):
        """REQ-373: high-confidence facts have LOWER importance → fails."""
        records = [
            _record("h1", confidence=0.9, importance=1),  # high conf, low imp
            _record("h2", confidence=0.85, importance=1),
            _record("l1", confidence=0.2, importance=8),  # low conf, high imp
            _record("l2", confidence=0.2, importance=7),
        ]
        report = score_calibration(records)
        assert not report.passes_baseline, f"Inverted calibration should fail: {report.summary()}"

    def test_tier_stats_correct(self):
        """REQ-371: tier statistics computed correctly."""
        records = [
            _record("h1", confidence=0.9, importance=10),
            _record("m1", confidence=0.6, importance=4),
            _record("l1", confidence=0.3, importance=2),
        ]
        report = score_calibration(records)
        assert "high" in report.tiers
        assert "mid" in report.tiers
        assert "low" in report.tiers
        assert report.tiers["high"]["count"] == 1.0
        assert report.tiers["high"]["mean_importance"] == pytest.approx(10.0)
        assert report.tiers["mid"]["mean_importance"] == pytest.approx(4.0)
        assert report.tiers["low"]["mean_importance"] == pytest.approx(2.0)

    def test_monotonic_three_tiers(self):
        """REQ-372: monotonic=True when high≥mid≥low."""
        records = [
            _record("h1", confidence=0.9, importance=9),
            _record("m1", confidence=0.6, importance=5),
            _record("l1", confidence=0.3, importance=1),
        ]
        report = score_calibration(records)
        assert report.monotonic is True
        assert report.calibration_score == pytest.approx(1.0)

    def test_non_monotonic_mid_out_of_order(self):
        """REQ-372: monotonic=False but passes_baseline still true if high≥low."""
        records = [
            _record("h1", confidence=0.9, importance=9),
            _record("m1", confidence=0.6, importance=1),  # mid dips below low
            _record("l1", confidence=0.3, importance=5),
        ]
        report = score_calibration(records)
        assert report.monotonic is False
        # High (9) ≥ Low (5) → passes baseline even though mid is out of order.
        assert report.passes_baseline is True

    def test_empty_records_no_exception(self):
        """REQ-374: empty input → graceful return."""
        report = score_calibration([])
        assert report.n_facts == 0
        assert report.calibration_score == pytest.approx(1.0)
        assert report.passes_baseline is True  # vacuously (no tiers populated)

    def test_single_tier_populated(self):
        """REQ-374: only one tier populated → monotonic vacuously True."""
        records = [_record("h1", confidence=0.9, importance=5)]
        report = score_calibration(records)
        assert report.monotonic is True
        assert report.passes_baseline is True

    def test_missing_confidence_defaults_to_mid(self):
        """REQ-374: missing confidence defaults to 0.5 → lands in mid tier."""
        r = {"id": "x", "document": "fact", "metadata": {"importance": 3}}
        report = score_calibration([r])
        assert "mid" in report.tiers

    def test_missing_importance_defaults_to_one(self):
        """REQ-374: missing importance defaults to 1."""
        r = {"id": "x", "document": "fact", "metadata": {"confidence": 0.9}}
        report = score_calibration([r])
        assert report.tiers["high"]["mean_importance"] == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Sortie 2: Importance-gated contradiction decay (REQ-375–379)
# ─────────────────────────────────────────────────────────────────────────────


class TestImportanceGatedDecay:
    async def _provider_with_fact(self, importance: int, confidence: float, gated: bool = True):
        """Build a provider with a single fact at the given importance/confidence."""
        store = FakeStore()
        embedder = FakeEmbedder()
        provider = make_provider(store, embedder)
        provider._confidence_importance_gated_decay = gated
        # Insert fact directly.
        await store.upsert(
            ids=["fact1"],
            vectors=[[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]],
            metadatas=[{"user": "alice", "importance": importance, "confidence": confidence}],
            documents=["loves action movies"],
        )
        return provider, store

    async def test_gated_importance_1_full_decay(self):
        """REQ-376: importance=1 → effective decay = decay/1 = decay (unchanged)."""
        provider, store = await self._provider_with_fact(importance=1, confidence=0.8)
        await provider._apply_confidence_decay("fact1", decay=0.1, floor=0.0)
        metas = await store.get_metadata(["fact1"])
        assert metas[0]["confidence"] == pytest.approx(0.7, abs=1e-6)

    async def test_gated_importance_5_reduced_decay(self):
        """REQ-376: importance=5 → effective decay = 0.1/5 = 0.02."""
        provider, store = await self._provider_with_fact(importance=5, confidence=0.8)
        await provider._apply_confidence_decay("fact1", decay=0.1, floor=0.0)
        metas = await store.get_metadata(["fact1"])
        assert metas[0]["confidence"] == pytest.approx(0.78, abs=1e-4)

    async def test_gated_importance_10_very_slow_decay(self):
        """REQ-376: importance=10 → effective decay = 0.1/10 = 0.01."""
        provider, store = await self._provider_with_fact(importance=10, confidence=0.8)
        await provider._apply_confidence_decay("fact1", decay=0.1, floor=0.0)
        metas = await store.get_metadata(["fact1"])
        assert metas[0]["confidence"] == pytest.approx(0.79, abs=1e-4)

    async def test_floor_respected_after_gating(self):
        """REQ-378: floor still applied even after gating reduces effective decay."""
        provider, store = await self._provider_with_fact(importance=1, confidence=0.15)
        await provider._apply_confidence_decay("fact1", decay=0.5, floor=0.1)
        metas = await store.get_metadata(["fact1"])
        assert metas[0]["confidence"] == pytest.approx(0.1, abs=1e-6)

    async def test_ungated_decay_unchanged(self):
        """REQ-379: importance_gated_decay=False → standard decay (backward-compat)."""
        provider, store = await self._provider_with_fact(importance=10, confidence=0.8, gated=False)
        await provider._apply_confidence_decay("fact1", decay=0.1, floor=0.0)
        metas = await store.get_metadata(["fact1"])
        # Full decay applied regardless of importance.
        assert metas[0]["confidence"] == pytest.approx(0.7, abs=1e-6)

    def test_default_is_false(self):
        """REQ-379: default config has importance_gated_decay=False."""
        store = FakeStore()
        embedder = FakeEmbedder()
        provider = make_provider(store, embedder)
        assert provider._confidence_importance_gated_decay is False


# ─────────────────────────────────────────────────────────────────────────────
# Sortie 3: Temporal confidence drift sweep (REQ-380–384)
# ─────────────────────────────────────────────────────────────────────────────


class TestConfidenceDriftSweeper:
    def _make_sweeper(self, store: FakeStore, **kw):
        from kryten_llm.components.memory.retention import ConfidenceDriftSweeper

        return ConfidenceDriftSweeper(
            store=store,
            interval_hours=kw.get("interval_hours", 24.0),
            drift_after_days=kw.get("drift_after_days", 30.0),
            drift_rate_per_day=kw.get("drift_rate_per_day", 0.01),
            floor=kw.get("floor", 0.1),
        )

    async def test_dormant_fact_gets_drifted(self):
        """REQ-380: fact dormant > drift_after_days → confidence reduced."""
        store = FakeStore()
        await store.upsert(
            ids=["f1"],
            vectors=[[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]],
            metadatas=[
                {
                    "user": "alice",
                    "confidence": 0.8,
                    "importance": 1,
                    "last_seen": _ts(60),  # 60 days dormant
                    "created_at": _ts(61),
                }
            ],
            documents=["loves movies"],
        )
        sweeper = self._make_sweeper(store, drift_after_days=30.0, drift_rate_per_day=0.01)
        count = await sweeper.sweep()
        assert count == 1
        metas = await store.get_metadata(["f1"])
        assert metas[0]["confidence"] < 0.8, "Confidence should decrease after drift."

    async def test_recent_fact_not_drifted(self):
        """REQ-380: fact last seen 5 days ago (threshold=30) → no drift."""
        store = FakeStore()
        await store.upsert(
            ids=["f1"],
            vectors=[[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]],
            metadatas=[
                {
                    "user": "alice",
                    "confidence": 0.8,
                    "importance": 1,
                    "last_seen": _ts(5),  # recent
                    "created_at": _ts(6),
                }
            ],
            documents=["loves movies"],
        )
        sweeper = self._make_sweeper(store, drift_after_days=30.0)
        count = await sweeper.sweep()
        assert count == 0
        metas = await store.get_metadata(["f1"])
        assert metas[0]["confidence"] == pytest.approx(0.8)

    async def test_floor_respected(self):
        """REQ-381: confidence never drops below floor."""
        store = FakeStore()
        await store.upsert(
            ids=["f1"],
            vectors=[[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]],
            metadatas=[
                {
                    "user": "alice",
                    "confidence": 0.12,  # close to floor
                    "importance": 1,
                    "last_seen": _ts(365),  # very old
                    "created_at": _ts(366),
                }
            ],
            documents=["loves movies"],
        )
        sweeper = self._make_sweeper(store, drift_after_days=1.0, drift_rate_per_day=0.1, floor=0.1)
        await sweeper.sweep()
        metas = await store.get_metadata(["f1"])
        assert metas[0]["confidence"] >= 0.1, "Must not drop below floor."

    async def test_already_at_floor_skipped(self):
        """REQ-381: fact already at floor → skipped (count=0)."""
        store = FakeStore()
        await store.upsert(
            ids=["f1"],
            vectors=[[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]],
            metadatas=[
                {
                    "user": "alice",
                    "confidence": 0.1,  # exactly at floor
                    "importance": 1,
                    "last_seen": _ts(90),
                    "created_at": _ts(91),
                }
            ],
            documents=["loves movies"],
        )
        sweeper = self._make_sweeper(store, drift_after_days=1.0, floor=0.1)
        count = await sweeper.sweep()
        assert count == 0

    async def test_empty_store_no_exception(self):
        """REQ-383: empty store → sweep returns 0, no exception."""
        store = FakeStore()
        sweeper = self._make_sweeper(store)
        count = await sweeper.sweep()
        assert count == 0

    def test_config_defaults_disabled(self):
        """REQ-382: ConfidenceDriftConfig defaults to disabled."""
        from kryten_llm.models.config import ConfidenceDriftConfig

        cfg = ConfidenceDriftConfig()
        assert cfg.enabled is False
        assert cfg.drift_after_days == pytest.approx(30.0)
        assert cfg.drift_rate_per_day == pytest.approx(0.001)
        assert cfg.confidence_floor == pytest.approx(0.1)
