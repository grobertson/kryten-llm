"""Scoring functions for the memory-quality evaluation harness.

Sprint 12:
- Sortie 2 (REQ-255–259): precision@k + MRR for retrieval quality.
- Sortie 3 (REQ-260–264): precision/recall for the contradiction detector.

Sprint 18:
- Sortie 1 (REQ-370–374): confidence calibration scorer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Sortie 2: Retrieval quality scorers (REQ-255–256)
# ---------------------------------------------------------------------------


def precision_at_k(retrieved_ids: list[str], expected_ids: set[str], k: int) -> float:
    """Fraction of the top-k retrieved IDs that appear in *expected_ids* (REQ-255).

    Returns 0.0 when *k* ≤ 0 or *retrieved_ids* is empty.
    """
    if k <= 0 or not retrieved_ids:
        return 0.0
    top = retrieved_ids[:k]
    return sum(1 for rid in top if rid in expected_ids) / k


def recall_at_k(retrieved_ids: list[str], expected_ids: set[str], k: int) -> float:
    """Fraction of *expected_ids* that appear in the top-k retrieved results.

    This is the primary aggregate metric: with a single expected ID, recall@k is
    1.0 if the expected item is found in top-k and 0.0 otherwise — a meaningful
    signal for single-expected-ID fixture scenarios.
    """
    if not expected_ids:
        return 0.0
    top = set(retrieved_ids[:k])
    return len(top & expected_ids) / len(expected_ids)


def mean_reciprocal_rank(retrieved_ids: list[str], expected_ids: set[str]) -> float:
    """Mean reciprocal rank of the first expected ID in *retrieved_ids* (REQ-256).

    Returns 0.0 if no expected ID appears in the result list.
    """
    for rank, rid in enumerate(retrieved_ids, 1):
        if rid in expected_ids:
            return 1.0 / rank
    return 0.0


@dataclass
class RetrievalReport:
    """Aggregated retrieval-quality metrics over a scenario set (REQ-258).

    The primary metric is ``recall_at_k`` (fraction of expected IDs found in top-k).
    ``precision_at_k`` is also reported; for single-expected-ID scenarios it equals
    ``recall_at_k / k`` and is informational only.
    """

    recall_at_k: float  # mean recall@k across scenarios (primary metric)
    precision_at_k: float  # mean precision@k (informational)
    mean_reciprocal_rank: float  # mean MRR across scenarios
    k: int
    n_scenarios: int
    baseline_recall: float = 0.6  # fail threshold on recall@k (REQ-258)

    @property
    def passes_baseline(self) -> bool:
        """True if recall@k ≥ baseline_recall (REQ-258)."""
        return self.recall_at_k >= self.baseline_recall

    def summary(self) -> str:
        status = "PASS" if self.passes_baseline else "FAIL"
        return (
            f"Retrieval [{status}]  recall@{self.k}={self.recall_at_k:.2%}  "
            f"precision@{self.k}={self.precision_at_k:.2%}  "
            f"MRR={self.mean_reciprocal_rank:.3f}  "
            f"(baseline recall ≥ {self.baseline_recall:.0%}, n={self.n_scenarios})"
        )


async def score_retrieval(
    scenarios: list[Any],
    store: Any,
    embedder: Any,
    k: int = 5,
    baseline_precision: float = 0.6,
) -> RetrievalReport:
    """Score retrieval quality for all *scenarios* using *store* + *embedder*.

    For each scenario: embed the query, query the store, compare top-k IDs to
    ``expected_ids``.  When ``expected_ids`` is empty, the scenario is skipped in
    the recall/MRR calculation (it still exercises the pipeline path).

    The primary aggregate metric is ``recall@k`` (fraction of expected IDs found
    in top-k); ``precision@k`` is also collected as an informational metric.

    Returns a ``RetrievalReport`` with aggregated metrics (REQ-258).
    """
    from kryten_llm.components.memory.heuristic_extractor import stable_fact_id

    recall_values: list[float] = []
    p_values: list[float] = []
    mrr_values: list[float] = []

    for sc in scenarios:
        fact_ids = {stable_fact_id(f.user, f.summary): f for f in sc.facts}

        if sc.expected_ids:
            expected = set(sc.expected_ids)
        else:
            q_words = set(sc.query.lower().split())
            best_id: str | None = None
            best_overlap = -1
            for fid, fact in fact_ids.items():
                overlap = len(q_words & set(fact.summary.lower().split()))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_id = fid
            expected = {best_id} if best_id else set()

        query_vecs = await embedder.embed([sc.query])
        if not query_vecs:
            continue
        first_user = sc.facts[0].user if sc.facts else None
        where = {"user": first_user} if "speaker" in sc.tags and first_user else None
        results = await store.query(vector=query_vecs[0], k=k, where=where)
        retrieved = [r["id"] for r in results]

        if expected:
            recall_values.append(recall_at_k(retrieved, expected, k))
            p_values.append(precision_at_k(retrieved, expected, k))
            mrr_values.append(mean_reciprocal_rank(retrieved, expected))

    mean_recall = sum(recall_values) / len(recall_values) if recall_values else 0.0
    mean_p = sum(p_values) / len(p_values) if p_values else 0.0
    mean_mrr = sum(mrr_values) / len(mrr_values) if mrr_values else 0.0

    return RetrievalReport(
        recall_at_k=mean_recall,
        precision_at_k=mean_p,
        mean_reciprocal_rank=mean_mrr,
        k=k,
        n_scenarios=len(scenarios),
        baseline_recall=baseline_precision,
    )


# ---------------------------------------------------------------------------
# Sortie 3: Contradiction detector scorer (REQ-260–264)
# ---------------------------------------------------------------------------


@dataclass
class ContradictionReport:
    """Precision and recall for the contradiction detector (REQ-262)."""

    precision: float  # TP / (TP + FP) — don't over-detect
    recall: float  # TP / (TP + FN) — don't miss real contradictions
    method: str
    n_scenarios: int
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0
    baseline_recall: float = 0.70  # heuristic baseline (REQ-263)
    baseline_precision: float = 0.65  # embedding baseline (REQ-263)

    @property
    def passes_baseline(self) -> bool:
        """True if the method's key baseline is met (REQ-263)."""
        if self.method == "heuristic":
            return self.recall >= self.baseline_recall
        return self.precision >= self.baseline_precision

    def summary(self) -> str:
        status = "PASS" if self.passes_baseline else "FAIL"
        return (
            f"Contradiction/{self.method} [{status}]  "
            f"precision={self.precision:.2%}  recall={self.recall:.2%}  "
            f"TP={self.tp} FP={self.fp} TN={self.tn} FN={self.fn}  "
            f"(n={self.n_scenarios})"
        )


async def score_contradictions(
    scenarios: list[Any],
    provider: Any,
    method: str = "heuristic",
) -> ContradictionReport:
    """Score contradiction detection over labeled *scenarios* (REQ-261).

    Temporarily switches the provider's ``_contradiction_method`` to *method*
    for scoring, then restores the original value.
    """
    original_method = getattr(provider, "_contradiction_method", "heuristic")
    provider._contradiction_method = method

    tp = fp = tn = fn = 0
    scored = 0
    try:
        for sc in scenarios:
            # Filter to scenarios applicable to this method.
            if sc.method not in (method, "both"):
                continue
            scored += 1
            detected = await provider._is_contradiction(sc.message, sc.fact_text, 10)
            if detected and sc.contradicts:
                tp += 1
            elif detected and not sc.contradicts:
                fp += 1
            elif not detected and sc.contradicts:
                fn += 1
            else:
                tn += 1
    finally:
        provider._contradiction_method = original_method

    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0

    return ContradictionReport(
        precision=precision,
        recall=recall,
        method=method,
        n_scenarios=scored,
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
    )


# ---------------------------------------------------------------------------
# Sprint 18 Sortie 1: Confidence calibration scorer (REQ-370–374)
# ---------------------------------------------------------------------------


@dataclass
class CalibrationReport:
    """Confidence calibration report (Sprint 18, REQ-370–374).

    Uses ``importance`` (corroboration count) as a proxy for fact correctness.
    A well-calibrated system should have higher mean importance for facts with
    higher confidence — if the bot is confident about a fact, that fact should
    have been corroborated more often.

    Tiers: ``low`` (conf < 0.5), ``mid`` (0.5 ≤ conf < 0.8), ``high`` (≥ 0.8).
    """

    tiers: dict[str, dict[str, float]]
    """Tier label → {mean_confidence, mean_importance, count}."""

    monotonic: bool
    """True when mean_importance increases monotonically: high ≥ mid ≥ low."""

    calibration_score: float
    """Fraction of adjacent tier pairs that are in the correct order (0–1)."""

    n_facts: int

    @property
    def passes_baseline(self) -> bool:
        """True when high-confidence facts have ≥ mean_importance vs low-confidence (REQ-373)."""
        high = self.tiers.get("high", {}).get("mean_importance", 0.0)
        low = self.tiers.get("low", {}).get("mean_importance", 0.0)
        # If only one tier is populated the constraint is trivially satisfied.
        if "high" not in self.tiers or "low" not in self.tiers:
            return True
        return high >= low

    def summary(self) -> str:
        status = "PASS" if self.passes_baseline else "FAIL"
        parts = []
        for tier in ("low", "mid", "high"):
            t = self.tiers.get(tier)
            if t:
                parts.append(
                    f"{tier}: conf={t.get('mean_confidence', 0.0):.2f} "
                    f"imp={t.get('mean_importance', 0.0):.1f} "
                    f"(n={t.get('count', 0):.0f})"
                )
        return (
            f"Calibration [{status}]  "
            + "  |  ".join(parts)
            + f"  monotonic={self.monotonic}  score={self.calibration_score:.2f}"
        )


def score_calibration(records: list[dict]) -> CalibrationReport:
    """Compute confidence calibration from store records (REQ-370–374).

    Each record must be a dict with a ``metadata`` sub-dict containing at least
    ``confidence`` (float 0–1) and ``importance`` (int ≥ 1).  Records without
    these fields default to ``confidence=0.5`` and ``importance=1``.

    Args:
        records: Store records from ``VectorStore.get_all()`` (or FakeStore).

    Returns:
        A ``CalibrationReport`` with per-tier stats and a monotonicity flag.
    """
    tier_buckets: dict[str, list[tuple[float, int]]] = {"low": [], "mid": [], "high": []}

    for r in records:
        meta = r.get("metadata") or {}
        conf = float(meta.get("confidence", 0.5))
        imp = int(meta.get("importance", 1))
        if conf < 0.5:
            tier_buckets["low"].append((conf, imp))
        elif conf < 0.8:
            tier_buckets["mid"].append((conf, imp))
        else:
            tier_buckets["high"].append((conf, imp))

    tier_stats: dict[str, dict[str, float]] = {}
    for tier_name, items in tier_buckets.items():
        if items:
            n = len(items)
            tier_stats[tier_name] = {
                "mean_confidence": sum(c for c, _ in items) / n,
                "mean_importance": sum(i for _, i in items) / n,
                "count": float(n),
            }

    # Monotonicity: check populated tiers in order low → mid → high (REQ-372).
    populated = [
        (name, tier_stats[name]["mean_importance"])
        for name in ("low", "mid", "high")
        if name in tier_stats
    ]

    monotonic = True
    monotonic_pairs = 0
    total_pairs = max(len(populated) - 1, 0)
    for i in range(total_pairs):
        _, imp_a = populated[i]
        _, imp_b = populated[i + 1]
        if imp_b >= imp_a:
            monotonic_pairs += 1
        else:
            monotonic = False

    calib_score = (monotonic_pairs / total_pairs) if total_pairs > 0 else 1.0

    return CalibrationReport(
        tiers=tier_stats,
        monotonic=monotonic,
        calibration_score=calib_score,
        n_facts=len(records),
    )
