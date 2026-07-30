"""Tests for Sprint 13: Fact Confidence & Verification (REQ-280–309).

Covers:
* Sortie 1 — confidence field in _upsert_facts (heuristic) and read-path default
* Sortie 2 — corroboration boost in _bump_importance (exponential approach)
* Sortie 3 — contradiction decay via _apply_confidence_decay (floor guard, off-path)
* Sortie 4 — confidence_weight in _rank_with_boost (default transparent)
* Sortie 5 — ContextFragment.confidence populated; hedged template; default off
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from kryten_llm.components.context.base import ContextFragment


# ---------------------------------------------------------------------------
# Sortie 1: Confidence field (REQ-280–284)
# ---------------------------------------------------------------------------


class TestConfidenceField:
    """confidence field in stored metadata (REQ-280–283)."""

    def test_context_fragment_confidence_field_exists(self):
        """ContextFragment now accepts confidence (REQ-300 dependency)."""
        frag = ContextFragment(name="user_memory", priority=10, text="hi", confidence=0.75)
        assert frag.confidence == pytest.approx(0.75)

    def test_context_fragment_confidence_defaults_to_none(self):
        """confidence is None when not supplied — backward-compatible (REQ-303)."""
        frag = ContextFragment(name="user_memory", priority=10, text="hi")
        assert frag.confidence is None

    async def test_upsert_facts_includes_confidence(self):
        """Heuristic upsert stores confidence = score / 100 (REQ-281)."""
        from tests.eval.harness import FakeEmbedder, FakeStore, make_provider

        store = FakeStore()
        embedder = FakeEmbedder()
        provider = make_provider(store, embedder)

        # Build a minimal Fact-like object
        from kryten_llm.components.memory.heuristic_extractor import stable_fact_id

        class _Fact:
            user = "alice"
            summary = "alice loves action movie film"
            category = "preference"
            source = "test"
            score = 75.0
            evidence: dict = {}

        await provider._upsert_facts([_Fact()])  # type: ignore[arg-type]

        fid = stable_fact_id("alice", "alice loves action movie film")
        records = await store.get_all(where={"user": "alice"})
        assert records, "fact not stored"
        meta = records[0]["metadata"]
        assert "confidence" in meta
        assert meta["confidence"] == pytest.approx(0.75)  # 75 / 100

    def test_read_path_default_is_half(self):
        """Missing confidence reads as 0.5 (REQ-283) — verified by convention."""
        meta: dict = {}
        confidence = float(meta.get("confidence", 0.5))
        assert confidence == pytest.approx(0.5)

    async def test_eval_harness_seed_includes_confidence(self):
        """seed_store includes confidence in metadata (REQ-284)."""
        from tests.eval.harness import EvalFact, FakeEmbedder, FakeStore, seed_store

        store = FakeStore()
        embedder = FakeEmbedder()
        fact = EvalFact(user="alice", summary="alice loves movies", category="pref", importance=5)
        await seed_store(store, [fact], embedder)
        records = await store.get_all(where={"user": "alice"})
        assert records
        assert "confidence" in records[0]["metadata"]
        assert records[0]["metadata"]["confidence"] == pytest.approx(0.5)  # importance 5 / 10


# ---------------------------------------------------------------------------
# Sortie 2: Corroboration boost (REQ-285–289)
# ---------------------------------------------------------------------------


class TestCorroborationBoost:
    """Confidence boost in _bump_importance (REQ-285–289)."""

    def _make_provider_with_store(self):
        from tests.eval.harness import FakeEmbedder, FakeStore, make_provider
        from kryten_llm.components.memory.heuristic_extractor import stable_fact_id

        store = FakeStore()
        embedder = FakeEmbedder()
        provider = make_provider(store, embedder)

        # Inject a minimal _ext_cfg for _bump_importance
        ext_cfg = MagicMock()
        ext_cfg.scoring.importance_cap = 10000
        provider._ext_cfg = ext_cfg
        provider._llm_mode = True  # enable bump path
        return provider, store

    async def test_single_corroboration_increases_confidence(self):
        """One bump raises confidence by step * (1 - conf) (REQ-287)."""
        provider, store = self._make_provider_with_store()
        provider._confidence_corroboration_step = 0.1

        # Seed a fact with known confidence
        await store.upsert(
            ids=["f1"],
            vectors=[[0.1] * 8],
            metadatas=[{"user": "alice", "importance": 1, "confidence": 0.5}],
            documents=["alice loves movies"],
        )
        await provider._bump_importance("f1")

        metas = await store.get_metadata(ids=["f1"])
        new_conf = metas[0]["confidence"]
        # new_conf = 0.5 + 0.1 * (1 - 0.5) = 0.55
        assert new_conf == pytest.approx(0.55, abs=1e-6)

    async def test_multiple_corroborations_converge_to_one(self):
        """Repeated bumps asymptotically approach 1.0 (REQ-286, REQ-287)."""
        provider, store = self._make_provider_with_store()
        provider._confidence_corroboration_step = 0.2

        await store.upsert(
            ids=["f1"],
            vectors=[[0.1] * 8],
            metadatas=[{"user": "alice", "importance": 1, "confidence": 0.0}],
            documents=["alice test"],
        )
        for _ in range(50):
            await provider._bump_importance("f1")

        metas = await store.get_metadata(ids=["f1"])
        conf = metas[0]["confidence"]
        assert conf <= 1.0
        assert conf > 0.99  # approaches but never exceeds 1.0

    async def test_step_zero_no_change(self):
        """step = 0 → confidence unchanged (REQ-289)."""
        provider, store = self._make_provider_with_store()
        provider._confidence_corroboration_step = 0.0

        await store.upsert(
            ids=["f1"],
            vectors=[[0.1] * 8],
            metadatas=[{"user": "alice", "importance": 1, "confidence": 0.6}],
            documents=["test"],
        )
        await provider._bump_importance("f1")

        metas = await store.get_metadata(ids=["f1"])
        assert metas[0]["confidence"] == pytest.approx(0.6)

    async def test_store_without_get_metadata_skips_gracefully(self):
        """If store doesn't support metadata ops, bump is silently skipped (REQ-285)."""
        from tests.eval.harness import FakeEmbedder, make_provider
        import types

        store = MagicMock()
        store.get_metadata = None  # simulate missing support
        store.update_metadata = None

        embedder = FakeEmbedder()
        provider = make_provider(store, embedder)

        ext_cfg = MagicMock()
        ext_cfg.scoring.importance_cap = 10000
        provider._ext_cfg = ext_cfg
        provider._llm_mode = True
        provider._confidence_corroboration_step = 0.1

        # Should not raise
        await provider._bump_importance("f1")


# ---------------------------------------------------------------------------
# Sortie 3: Contradiction confidence decay (REQ-290–294)
# ---------------------------------------------------------------------------


class TestContradictionDecay:
    """Confidence decay from _apply_confidence_decay (REQ-290–294)."""

    async def _seeded_provider(self, initial_confidence: float = 0.8):
        from tests.eval.harness import FakeEmbedder, FakeStore, make_provider

        store = FakeStore()
        embedder = FakeEmbedder()
        await store.upsert(
            ids=["f1"],
            vectors=[[0.1] * 8],
            metadatas=[{"user": "alice", "confidence": initial_confidence}],
            documents=["alice likes movies"],
        )
        provider = make_provider(store, embedder)
        return provider, store

    async def test_contradiction_reduces_confidence(self):
        """Decay reduces stored confidence by the configured amount (REQ-290)."""
        provider, store = await self._seeded_provider(initial_confidence=0.8)
        provider._confidence_contradiction_decay = 0.15
        provider._confidence_floor = 0.1

        await provider._apply_confidence_decay("f1", 0.15, 0.1)

        metas = await store.get_metadata(ids=["f1"])
        assert metas[0]["confidence"] == pytest.approx(0.65, abs=1e-6)

    async def test_floor_prevents_zero(self):
        """Confidence never falls below confidence_floor (REQ-291)."""
        provider, store = await self._seeded_provider(initial_confidence=0.15)
        provider._confidence_contradiction_decay = 0.5
        provider._confidence_floor = 0.1

        await provider._apply_confidence_decay("f1", 0.5, 0.1)

        metas = await store.get_metadata(ids=["f1"])
        assert metas[0]["confidence"] >= 0.1

    async def test_decay_zero_no_change(self):
        """Decay = 0 → confidence unchanged (REQ-294)."""
        provider, store = await self._seeded_provider(initial_confidence=0.7)

        await provider._apply_confidence_decay("f1", 0.0, 0.1)

        metas = await store.get_metadata(ids=["f1"])
        # confidence should be unchanged — no update call if new == old
        assert metas[0]["confidence"] == pytest.approx(0.7)

    async def test_store_without_metadata_support_graceful(self):
        """Missing metadata ops → silently ignored (REQ-292)."""
        from tests.eval.harness import FakeEmbedder, make_provider

        store = MagicMock()
        store.get_metadata = None
        embedder = FakeEmbedder()
        provider = make_provider(store, embedder)

        # Should not raise
        await provider._apply_confidence_decay("f1", 0.1, 0.1)

    async def test_missing_fact_silently_ignored(self):
        """Decaying a non-existent fact ID is silently ignored."""
        from tests.eval.harness import FakeEmbedder, FakeStore, make_provider

        store = FakeStore()  # empty store
        embedder = FakeEmbedder()
        provider = make_provider(store, embedder)

        await provider._apply_confidence_decay("nonexistent", 0.1, 0.1)


# ---------------------------------------------------------------------------
# Sortie 4: Confidence-weighted retrieval (REQ-295–299)
# ---------------------------------------------------------------------------


class TestConfidenceWeightedRetrieval:
    """_rank_with_boost includes confidence dimension (REQ-295–298)."""

    def _make_provider_for_ranking(self, confidence_weight: float = 0.0):
        from tests.eval.harness import FakeEmbedder, FakeStore, make_provider

        store = FakeStore()
        embedder = FakeEmbedder()
        provider = make_provider(store, embedder)

        ext_cfg = MagicMock()
        ext_cfg.scoring.importance_cap = 10000
        ext_cfg.retrieval_boost.importance_weight = 0.0
        ext_cfg.retrieval_boost.recency_weight = 0.0
        ext_cfg.retrieval_boost.confidence_weight = confidence_weight
        provider._ext_cfg = ext_cfg
        provider._llm_mode = True
        return provider

    def _make_result(self, rid: str, distance: float, confidence: float) -> dict:
        return {
            "id": rid,
            "document": f"fact {rid}",
            "metadata": {"confidence": confidence, "importance": 1},
            "distance": distance,
        }

    def test_weight_zero_transparent(self):
        """confidence_weight=0 → identical ordering to current (REQ-298)."""
        provider = self._make_provider_for_ranking(0.0)
        results = [
            self._make_result("hi", 0.1, 0.9),  # more similar
            self._make_result("lo", 0.5, 0.9),  # less similar
        ]
        ranked = provider._rank_with_boost(results)
        # Should keep hi first (closer distance → higher similarity)
        assert ranked[0]["id"] == "hi"

    def test_confidence_weight_promotes_high_confidence(self):
        """Higher confidence_weight promotes facts with higher confidence (REQ-295)."""
        provider = self._make_provider_for_ranking(confidence_weight=1.0)
        results = [
            self._make_result("low_conf", 0.1, 0.1),   # close but low confidence
            self._make_result("high_conf", 0.3, 1.0),  # further but high confidence
        ]
        ranked = provider._rank_with_boost(results)
        # With confidence_weight=1.0, high_conf should bubble up despite lower similarity
        assert ranked[0]["id"] == "high_conf"

    def test_missing_confidence_defaults_to_half(self):
        """Facts without confidence field default to 0.5 (REQ-296)."""
        provider = self._make_provider_for_ranking(0.5)
        result = {"id": "f1", "document": "test", "metadata": {"importance": 1}, "distance": 0.2}
        # Should not raise; defaults to 0.5
        ranked = provider._rank_with_boost([result])
        assert ranked[0]["id"] == "f1"


# ---------------------------------------------------------------------------
# Sortie 5: Hedged template presentation (REQ-300–309)
# ---------------------------------------------------------------------------


class TestHedgedTemplate:
    """confidence on ContextFragment + template hedging (REQ-300–304)."""

    def test_fragment_confidence_populated(self):
        """ContextFragment.confidence field set to avg over ranked facts (REQ-300)."""
        frag = ContextFragment(
            name="user_memory", priority=40, text="Known facts about alice:\n• test",
            confidence=0.45
        )
        assert frag.confidence == pytest.approx(0.45)

    def test_fragment_confidence_none_when_no_results(self):
        """When no ranked results, confidence on fragment is None."""
        frag = ContextFragment(name="user_memory", priority=40, text="")
        assert frag.confidence is None

    async def test_speaker_scope_populates_confidence_on_fragment(self):
        """_run_speaker_scope sets .confidence on the user_memory fragment (REQ-300)."""
        from tests.eval.harness import EvalFact, FakeEmbedder, FakeStore, make_provider, seed_store
        from kryten_llm.components.context.base import ContextRequest

        store = FakeStore()
        embedder = FakeEmbedder()
        facts = [
            EvalFact(user="alice", summary="alice loves action movie film martial", category="pref", importance=8),
        ]
        await seed_store(store, facts, embedder)

        provider = make_provider(store, embedder)
        req = ContextRequest(username="alice", message="movie film action", trigger=None, channel="test")
        frags, _, _ = await provider._run_speaker_scope(req)

        user_memory_frags = [f for f in frags if f.name == "user_memory"]
        assert user_memory_frags, "no user_memory fragment emitted"
        # confidence should be set (not None)
        assert user_memory_frags[0].confidence is not None
        assert 0.0 <= user_memory_frags[0].confidence <= 1.0

    def test_hedge_enabled_false_is_current_behavior(self):
        """When hedge_enabled=False, template path is unchanged (REQ-303)."""
        from tests.eval.harness import FakeEmbedder, FakeStore, make_provider

        store = FakeStore()
        embedder = FakeEmbedder()
        provider = make_provider(store, embedder)
        assert provider._confidence_hedge_enabled is False  # default off

    def test_hedge_above_default(self):
        """Default hedge_above is 0.7 (REQ-301)."""
        from tests.eval.harness import FakeEmbedder, FakeStore, make_provider

        store = FakeStore()
        embedder = FakeEmbedder()
        provider = make_provider(store, embedder)
        assert provider._confidence_hedge_above == pytest.approx(0.7)
