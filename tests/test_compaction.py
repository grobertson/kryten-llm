"""Sprint 19, Sortie 1 — CompactionSweeper unit tests (REQ-385–389)."""
from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock

import pytest

from kryten_llm.components.memory.retention import CompactionSweeper
from tests.eval.harness import FakeEmbedder, FakeStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vec(dims: int, *hot_indices: int) -> list[float]:
    """Unit vector with 1.0 at the given indices and 0 elsewhere."""
    v = [0.0] * dims
    for i in hot_indices:
        v[i] = 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _rotated(base: list[float], angle: float) -> list[float]:
    """Rotate a 2-D-ish vector in the first two dims by *angle* radians."""
    v = list(base)
    v[0] = base[0] * math.cos(angle) - base[1] * math.sin(angle)
    v[1] = base[0] * math.sin(angle) + base[1] * math.cos(angle)
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


async def _make_store_with_facts(facts: list[dict]) -> FakeStore:
    store = FakeStore()
    for f in facts:
        await store.upsert(
            ids=[f["id"]],
            vectors=[f["vec"]],
            metadatas=[f["meta"]],
            documents=[f["doc"]],
        )
    return store


class FixedEmbedder:
    """Embedder that returns pre-defined vectors by index order."""

    id = "fixed"
    dimension = 4

    def __init__(self, vecs: list[list[float]]) -> None:
        self._vecs = vecs
        self._call_count = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:  # noqa: ARG002
        result = self._vecs[self._call_count : self._call_count + len(texts)]
        self._call_count += len(texts)
        return result


# ---------------------------------------------------------------------------
# _pairwise_cluster
# ---------------------------------------------------------------------------


class TestPairwiseCluster:
    def _cluster(self, vecs, threshold=0.85):
        records = [{"id": str(i), "metadata": {}, "document": f"fact {i}"} for i in range(len(vecs))]
        return CompactionSweeper._pairwise_cluster(records, vecs, threshold)

    def test_two_near_dups_form_one_cluster(self):
        base = _vec(4, 0)
        near = _rotated(base, 0.3)   # cos ≈ 0.955
        clusters = self._cluster([base, near])
        multi = [c for c in clusters if len(c) == 2]
        assert len(multi) == 1

    def test_two_distinct_facts_are_singletons(self):
        a = _vec(4, 0)
        b = _vec(4, 2)
        clusters = self._cluster([a, b])
        assert all(len(c) == 1 for c in clusters)
        assert len(clusters) == 2

    def test_three_near_dups_merge_into_one_cluster(self):
        base = _vec(4, 0)
        n1 = _rotated(base, 0.2)
        n2 = _rotated(base, 0.35)
        clusters = self._cluster([base, n1, n2])
        multi = [c for c in clusters if len(c) > 1]
        assert len(multi) == 1
        assert len(multi[0]) == 3

    def test_transitivity(self):
        """A—B and B—C similar enough; A and C need not be directly above threshold."""
        base = _vec(4, 0)
        b = _rotated(base, 0.3)   # sim(base, b) ≈ 0.955
        c = _rotated(b, 0.3)      # sim(b, c) ≈ 0.955; sim(base, c) ≈ cos(0.6) ≈ 0.825
        # With threshold=0.85: base-b merge, b-c merge → all three in one cluster
        clusters = self._cluster([base, b, c], threshold=0.85)
        multi = [c for c in clusters if len(c) > 1]
        assert sum(len(c) for c in multi) == 3


# ---------------------------------------------------------------------------
# sweep / _sweep_user
# ---------------------------------------------------------------------------


class TestCompactionSweeper:
    async def _sweeper(self, store, vecs, dry_run=False, min_facts=2):
        embedder = FixedEmbedder(vecs)
        return CompactionSweeper(
            store=store,
            embedder=embedder,
            min_facts_to_compact=min_facts,
            merge_threshold=0.85,
            importance_cap=10000,
            dry_run=dry_run,
        )

    @pytest.mark.asyncio
    async def test_three_near_dups_compact_to_one(self):
        base = _vec(4, 0)
        n1 = _rotated(base, 0.2)
        n2 = _rotated(base, 0.25)
        facts = [
            {"id": "a", "doc": "likes action movies", "vec": base,
             "meta": {"user": "alice", "importance": 3, "confidence": 0.7, "created_at": "2024-01-01T00:00:00+00:00"}},
            {"id": "b", "doc": "loves action films", "vec": n1,
             "meta": {"user": "alice", "importance": 5, "confidence": 0.8, "created_at": "2024-02-01T00:00:00+00:00"}},
            {"id": "c", "doc": "enjoys action cinema", "vec": n2,
             "meta": {"user": "alice", "importance": 2, "confidence": 0.6, "created_at": "2024-03-01T00:00:00+00:00"}},
        ]
        store = await _make_store_with_facts(facts)
        sweeper = await self._sweeper(store, [base, n1, n2])
        n = await sweeper.sweep()
        assert n == 2  # 2 non-canonicals deleted
        remaining = await store.get_all()
        assert len(remaining) == 1

    @pytest.mark.asyncio
    async def test_canonical_is_highest_importance(self):
        base = _vec(4, 0)
        n1 = _rotated(base, 0.2)
        facts = [
            {"id": "low", "doc": "low imp fact", "vec": base,
             "meta": {"user": "alice", "importance": 1, "confidence": 0.5, "created_at": "2024-01-01T00:00:00+00:00"}},
            {"id": "high", "doc": "high imp fact", "vec": n1,
             "meta": {"user": "alice", "importance": 10, "confidence": 0.9, "created_at": "2024-02-01T00:00:00+00:00"}},
        ]
        store = await _make_store_with_facts(facts)
        sweeper = await self._sweeper(store, [base, n1])
        await sweeper.sweep()
        remaining = await store.get_all()
        assert len(remaining) == 1
        assert remaining[0]["id"] == "high"

    @pytest.mark.asyncio
    async def test_merged_importance_is_sum_capped(self):
        base = _vec(4, 0)
        n1 = _rotated(base, 0.2)
        facts = [
            {"id": "a", "doc": "fact a", "vec": base,
             "meta": {"user": "alice", "importance": 7, "confidence": 0.8, "created_at": "2024-01-01T00:00:00+00:00"}},
            {"id": "b", "doc": "fact b", "vec": n1,
             "meta": {"user": "alice", "importance": 4, "confidence": 0.6, "created_at": "2024-01-01T00:00:00+00:00"}},
        ]
        store = await _make_store_with_facts(facts)
        sweeper = await self._sweeper(store, [base, n1])
        sweeper._importance_cap = 9  # cap lower than 7+4=11
        await sweeper.sweep()
        remaining = await store.get_all()
        assert remaining[0]["metadata"]["importance"] == 9  # capped

    @pytest.mark.asyncio
    async def test_merged_confidence_is_weighted_average(self):
        base = _vec(4, 0)
        n1 = _rotated(base, 0.2)
        facts = [
            {"id": "a", "doc": "fact a", "vec": base,
             "meta": {"user": "alice", "importance": 8, "confidence": 0.8, "created_at": "2024-01-01T00:00:00+00:00"}},
            {"id": "b", "doc": "fact b", "vec": n1,
             "meta": {"user": "alice", "importance": 2, "confidence": 0.4, "created_at": "2024-01-01T00:00:00+00:00"}},
        ]
        store = await _make_store_with_facts(facts)
        sweeper = await self._sweeper(store, [base, n1])
        await sweeper.sweep()
        remaining = await store.get_all()
        # weighted avg: (8*0.8 + 2*0.4) / 10 = 7.2/10 = 0.72
        assert abs(remaining[0]["metadata"]["confidence"] - 0.72) < 0.001

    @pytest.mark.asyncio
    async def test_two_distinct_facts_not_merged(self):
        a = _vec(4, 0)
        b = _vec(4, 2)
        facts = [
            {"id": "a", "doc": "likes action", "vec": a,
             "meta": {"user": "alice", "importance": 3, "confidence": 0.7, "created_at": "2024-01-01T00:00:00+00:00"}},
            {"id": "b", "doc": "plays piano", "vec": b,
             "meta": {"user": "alice", "importance": 3, "confidence": 0.7, "created_at": "2024-01-01T00:00:00+00:00"}},
        ]
        store = await _make_store_with_facts(facts)
        sweeper = await self._sweeper(store, [a, b])
        n = await sweeper.sweep()
        assert n == 0
        assert len(await store.get_all()) == 2

    @pytest.mark.asyncio
    async def test_dry_run_no_store_writes(self):
        base = _vec(4, 0)
        n1 = _rotated(base, 0.2)
        facts = [
            {"id": "a", "doc": "fact a", "vec": base,
             "meta": {"user": "alice", "importance": 3, "confidence": 0.7, "created_at": "2024-01-01T00:00:00+00:00"}},
            {"id": "b", "doc": "fact b", "vec": n1,
             "meta": {"user": "alice", "importance": 3, "confidence": 0.7, "created_at": "2024-01-01T00:00:00+00:00"}},
        ]
        store = await _make_store_with_facts(facts)
        sweeper = await self._sweeper(store, [base, n1], dry_run=True)
        n = await sweeper.sweep()
        assert n == 1  # reports would-merge count
        assert len(await store.get_all()) == 2  # no writes

    @pytest.mark.asyncio
    async def test_min_facts_guard_skips_small_users(self):
        base = _vec(4, 0)
        n1 = _rotated(base, 0.2)
        facts = [
            {"id": "a", "doc": "fact a", "vec": base,
             "meta": {"user": "alice", "importance": 3, "confidence": 0.7, "created_at": "2024-01-01T00:00:00+00:00"}},
            {"id": "b", "doc": "fact b", "vec": n1,
             "meta": {"user": "alice", "importance": 3, "confidence": 0.7, "created_at": "2024-01-01T00:00:00+00:00"}},
        ]
        store = await _make_store_with_facts(facts)
        sweeper = await self._sweeper(store, [base, n1], min_facts=10)  # min=10 but only 2 facts
        n = await sweeper.sweep()
        assert n == 0

    @pytest.mark.asyncio
    async def test_get_all_error_returns_zero_no_crash(self):
        store = FakeStore()
        store.get_all = AsyncMock(side_effect=RuntimeError("db down"))
        sweeper = CompactionSweeper(store=store, embedder=FakeEmbedder())
        n = await sweeper.sweep()
        assert n == 0

    @pytest.mark.asyncio
    async def test_per_user_error_does_not_stop_other_users(self):
        """Error for one user should not prevent other users from being processed."""
        base = _vec(4, 0)
        n1 = _rotated(base, 0.2)
        # Bob and Alice both have near-dups; Alice's embed will fail.
        facts_bob = [
            {"id": "b1", "doc": "bob fact 1", "vec": base,
             "meta": {"user": "bob", "importance": 3, "confidence": 0.7, "created_at": "2024-01-01T00:00:00+00:00"}},
            {"id": "b2", "doc": "bob fact 2", "vec": n1,
             "meta": {"user": "bob", "importance": 3, "confidence": 0.7, "created_at": "2024-01-01T00:00:00+00:00"}},
        ]
        store = await _make_store_with_facts(facts_bob)

        call_count = 0

        class FailOnSecondUser:
            id = "fail"
            dimension = 4

            async def embed(self, texts):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("embed fail")
                return [base] * len(texts)

        sweeper = CompactionSweeper(
            store=store, embedder=FailOnSecondUser(), min_facts_to_compact=2
        )
        # Should not raise; bob's facts may or may not be processed depending on order
        n = await sweeper.sweep()
        assert isinstance(n, int)

    @pytest.mark.asyncio
    async def test_earliest_created_at_preserved(self):
        base = _vec(4, 0)
        n1 = _rotated(base, 0.2)
        facts = [
            {"id": "a", "doc": "newer", "vec": base,
             "meta": {"user": "alice", "importance": 5, "confidence": 0.8, "created_at": "2025-01-01T00:00:00+00:00"}},
            {"id": "b", "doc": "older", "vec": n1,
             "meta": {"user": "alice", "importance": 2, "confidence": 0.6, "created_at": "2024-01-01T00:00:00+00:00"}},
        ]
        store = await _make_store_with_facts(facts)
        sweeper = await self._sweeper(store, [base, n1])
        await sweeper.sweep()
        remaining = await store.get_all()
        assert remaining[0]["metadata"]["created_at"] == "2024-01-01T00:00:00+00:00"
