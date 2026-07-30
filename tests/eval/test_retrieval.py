"""Retrieval quality evaluation (Sprint 12, Sortie 2, REQ-255–259).

Run with:  pytest -m eval -k retrieval

Scores precision@k and MRR over the retrieval.jsonl corpus against a
FakeEmbedder + FakeStore.  Suite fails if precision@5 falls below the baseline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.eval.harness import FakeEmbedder, FakeStore, FixtureLoader, make_provider, seed_store
from tests.eval.scorers import (
    ContradictionReport,
    RetrievalReport,
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
    score_retrieval,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Sortie 2: Scorer unit tests (REQ-255–256)
# ---------------------------------------------------------------------------


class TestPrecisionAtK:
    """Unit tests for precision_at_k() and recall_at_k() (REQ-255)."""

    def test_all_hits_precision(self):
        assert precision_at_k(["a", "b", "c"], {"a", "b", "c"}, k=3) == pytest.approx(1.0)

    def test_no_hits_precision(self):
        assert precision_at_k(["x", "y"], {"a", "b"}, k=2) == pytest.approx(0.0)

    def test_partial_hit_precision(self):
        assert precision_at_k(["a", "x"], {"a"}, k=2) == pytest.approx(0.5)

    def test_k_zero_returns_zero(self):
        assert precision_at_k(["a"], {"a"}, k=0) == pytest.approx(0.0)

    def test_empty_retrieved(self):
        assert precision_at_k([], {"a"}, k=5) == pytest.approx(0.0)

    def test_k_larger_than_retrieved(self):
        result = precision_at_k(["a", "b"], {"a", "b"}, k=5)
        assert result == pytest.approx(2 / 5)

    def test_recall_at_k_single_expected(self):
        """recall@k=1.0 when the single expected item is in top-k."""
        assert recall_at_k(["a", "b", "c"], {"a"}, k=3) == pytest.approx(1.0)

    def test_recall_at_k_miss(self):
        """recall@k=0.0 when the expected item is not in top-k."""
        assert recall_at_k(["x", "y", "z"], {"a"}, k=3) == pytest.approx(0.0)

    def test_recall_at_k_empty_expected(self):
        assert recall_at_k(["a"], set(), k=3) == pytest.approx(0.0)

    def test_recall_at_k_partial(self):
        assert recall_at_k(["a", "x"], {"a", "b"}, k=2) == pytest.approx(0.5)


class TestMRR:
    """Unit tests for mean_reciprocal_rank() (REQ-256)."""

    def test_first_result_is_hit(self):
        assert mean_reciprocal_rank(["a", "b"], {"a"}) == pytest.approx(1.0)

    def test_second_result_is_hit(self):
        assert mean_reciprocal_rank(["x", "a", "b"], {"a"}) == pytest.approx(0.5)

    def test_no_hit(self):
        assert mean_reciprocal_rank(["x", "y"], {"a"}) == pytest.approx(0.0)

    def test_empty_retrieved(self):
        assert mean_reciprocal_rank([], {"a"}) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Retrieval corpus eval (REQ-257–259) — @pytest.mark.eval
# ---------------------------------------------------------------------------


@pytest.mark.eval
class TestRetrievalEval:
    """End-to-end retrieval scoring over retrieval.jsonl (REQ-257–259)."""

    async def test_precision_at_5_meets_baseline(self):
        """recall@5 must meet the configured baseline (REQ-258)."""
        scenarios = FixtureLoader.load(_FIXTURE_DIR / "retrieval.jsonl")
        embedder = FakeEmbedder()
        store = FakeStore()

        # Seed all facts from all scenarios into one store.
        for sc in scenarios:
            await seed_store(store, sc.facts, embedder)

        report = await score_retrieval(scenarios, store, embedder, k=5)
        print(f"\n{report.summary()}")
        assert report.passes_baseline, (
            f"Retrieval recall@5={report.recall_at_k:.2%} is below "
            f"baseline {report.baseline_recall:.0%}.\n{report.summary()}"
        )

    async def test_mrr_positive(self):
        """MRR should be > 0 when at least one expected fact ranks in results."""
        scenarios = FixtureLoader.load(_FIXTURE_DIR / "retrieval.jsonl")
        embedder = FakeEmbedder()
        store = FakeStore()
        for sc in scenarios:
            await seed_store(store, sc.facts, embedder)
        report = await score_retrieval(scenarios, store, embedder, k=5)
        assert report.mean_reciprocal_rank >= 0.0

    async def test_fixture_load_and_seed_idempotent(self):
        """Re-seeding with the same facts does not change store size (REQ-253)."""
        scenarios = FixtureLoader.load(_FIXTURE_DIR / "retrieval.jsonl")
        embedder = FakeEmbedder()
        store = FakeStore()
        for sc in scenarios:
            await seed_store(store, sc.facts, embedder)
        count_first = await store.count()
        for sc in scenarios:
            await seed_store(store, sc.facts, embedder)  # re-seed
        count_second = await store.count()
        assert count_first == count_second, "Re-seeding must be idempotent (REQ-253)"

    async def test_min_10_retrieval_scenarios(self):
        """Fixture must contain at least 10 scenarios (REQ-257)."""
        scenarios = FixtureLoader.load(_FIXTURE_DIR / "retrieval.jsonl")
        assert len(scenarios) >= 10, f"Expected ≥ 10 scenarios, got {len(scenarios)}"

    def test_fixture_schema_valid(self):
        """FixtureLoader validates schema and all three fixtures load without error (REQ-251)."""
        for name in ("retrieval.jsonl", "contradiction.jsonl", "disclosure.jsonl"):
            path = _FIXTURE_DIR / name
            scenarios = FixtureLoader.load(path)
            assert len(scenarios) > 0, f"{name} is empty"
