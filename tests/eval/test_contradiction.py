"""Contradiction detector quality evaluation (Sprint 12, Sortie 3, REQ-260–264).

Run with:  pytest -m eval -k contradiction

Tests the heuristic contradiction detector against the labeled contradiction.jsonl
corpus.  Measures precision and recall; fails if they fall below baselines.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.eval.harness import FakeEmbedder, FakeStore, FixtureLoader, make_provider
from tests.eval.scorers import ContradictionReport, score_contradictions

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Unit tests for ContradictionReport
# ---------------------------------------------------------------------------


class TestContradictionReport:
    def test_perfect_recall(self):
        r = ContradictionReport(
            precision=1.0, recall=1.0, method="heuristic", n_scenarios=10, tp=10, fp=0, tn=0, fn=0
        )
        assert r.passes_baseline is True

    def test_low_recall_fails_heuristic_baseline(self):
        r = ContradictionReport(
            precision=1.0, recall=0.5, method="heuristic", n_scenarios=10, tp=5, fp=0, tn=0, fn=5
        )
        # heuristic baseline is recall >= 0.70
        assert r.passes_baseline is False

    def test_summary_contains_status(self):
        r = ContradictionReport(precision=0.9, recall=0.8, method="heuristic", n_scenarios=20)
        assert "PASS" in r.summary() or "FAIL" in r.summary()


# ---------------------------------------------------------------------------
# Corpus eval — @pytest.mark.eval
# ---------------------------------------------------------------------------


@pytest.mark.eval
class TestContradictionEval:
    """Contradiction detector precision/recall over contradiction.jsonl (REQ-260–264)."""

    async def _make_provider_for_heuristic(self) -> object:
        """Build a minimal provider with heuristic contradiction method."""
        store = FakeStore()
        embedder = FakeEmbedder()
        provider = make_provider(store, embedder)
        provider._contradiction_method = "heuristic"
        provider._novelty_enabled = True
        provider._novelty_max_similarity = 0.35
        provider._contradiction_min_similarity = 0.80
        return provider

    async def test_heuristic_recall_meets_baseline(self):
        """Heuristic detector recall ≥ 0.70 (REQ-263)."""
        scenarios = FixtureLoader.load(_FIXTURE_DIR / "contradiction.jsonl")
        provider = await self._make_provider_for_heuristic()
        report = await score_contradictions(scenarios, provider, method="heuristic")
        print(f"\n{report.summary()}")
        assert report.passes_baseline, (
            f"Heuristic recall={report.recall:.2%} is below baseline 70%.\n" f"{report.summary()}"
        )

    async def test_min_20_labeled_pairs(self):
        """Corpus must contain at least 20 labeled pairs (REQ-264)."""
        scenarios = FixtureLoader.load(_FIXTURE_DIR / "contradiction.jsonl")
        assert (
            len(scenarios) >= 20
        ), f"contradiction.jsonl must have ≥ 20 scenarios, got {len(scenarios)}"

    async def test_balanced_labels(self):
        """At least 8 true-contradiction and 8 non-contradiction examples (REQ-264)."""
        scenarios = FixtureLoader.load(_FIXTURE_DIR / "contradiction.jsonl")
        positives = sum(1 for s in scenarios if s.contradicts)
        negatives = sum(1 for s in scenarios if not s.contradicts)
        assert positives >= 8, f"Too few positive contradiction examples: {positives}"
        assert negatives >= 8, f"Too few negative examples: {negatives}"

    async def test_heuristic_reports_tp_and_tn(self):
        """The scorer produces non-trivial counts (not all zeros or all same)."""
        scenarios = FixtureLoader.load(_FIXTURE_DIR / "contradiction.jsonl")
        provider = await self._make_provider_for_heuristic()
        report = await score_contradictions(scenarios, provider, method="heuristic")
        assert report.tp + report.fn > 0, "No positive examples scored"
        assert report.tn + report.fp > 0, "No negative examples scored"

    async def test_no_positive_examples_precision_defaults_to_one(self):
        """Precision defaults to 1.0 when there are no positive predictions."""
        scenarios = [
            type(
                "S",
                (),
                {
                    "message": "I love movies",
                    "fact_text": "I love movies",
                    "contradicts": False,
                    "method": "heuristic",
                },
            )()
        ]
        store = FakeStore()
        embedder = FakeEmbedder()
        provider = make_provider(store, embedder)
        provider._contradiction_method = "heuristic"
        report = await score_contradictions(scenarios, provider, method="heuristic")
        # When all are TN, TP+FP == 0, so precision defaults to 1.0
        assert report.precision == pytest.approx(1.0)
