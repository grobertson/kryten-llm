"""Engagement score for adaptive auto-participation (Sprint 11, REQ-220–249).

The score aggregates memory signals into a single ``[0, 1]`` float representing
"how much does the bot have to say right now?" — used by the eagerness gate in
``TriggerEngine`` to decide whether to speak on auto-participation turns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class EngagementSignals:
    """Memory signals available after a ``provide()`` call.

    All values are in ``[0, 1]``.  Missing or disabled signals default to 0
    (graceful degradation — REQ-222).  The ``user_depth`` field encodes
    relational familiarity with the current speaker (REQ-246).
    """

    # 1 − top-1 cosine similarity → high when the message is novel relative to known facts.
    novelty: float = 0.0

    # Max similarity among topical_memory candidates (0 when topical scope is off).
    topical_max_sim: float = 0.0

    # Cosine(ambient_mood_vec, current_message_vec); 0 when ambient scope is off.
    mood_cosine: float = 0.0

    # Normalised max importance across speaker scope candidates.
    max_importance: float = 0.0

    # Speaker depth: normalised (fact_count / cap + avg_importance / importance_cap).
    # 0 when the speaker has no stored facts (REQ-249).
    user_depth: float = 0.0


@dataclass
class EngagementWeights:
    """Per-component weights for the engagement score (REQ-225)."""

    novelty: float = 0.5
    topical: float = 0.3
    mood: float = 0.1
    importance: float = 0.1
    # Bias cap — multiplicative factor applied to the raw score (REQ-247).
    # Default 1.0 → no bias (score unchanged).
    max_bias: float = 1.0

    @classmethod
    def from_config(cls, cfg: Any) -> "EngagementWeights":
        """Build from an ``EngagementWeightsConfig`` Pydantic model."""
        return cls(
            novelty=float(getattr(cfg, "novelty", 0.5)),
            topical=float(getattr(cfg, "topical", 0.3)),
            mood=float(getattr(cfg, "mood", 0.1)),
            importance=float(getattr(cfg, "importance", 0.1)),
            max_bias=float(getattr(cfg, "max_bias", 1.0)),
        )


def compute(signals: EngagementSignals, weights: EngagementWeights) -> float:
    """Return a normalised engagement score in ``[0, 1]`` (REQ-220).

    The score is a weighted sum of the four signal components, normalised by
    the total weight so that missing signals degrade gracefully without
    artificially inflating the result.  A multiplicative per-user bias
    (Sortie 4, REQ-245) is applied last.

    Args:
        signals: Memory signals collected during the previous ``provide()`` call.
        weights: Per-component weights from config.

    Returns:
        Normalised engagement score in ``[0.0, 1.0]``.
    """
    w_total = weights.novelty + weights.topical + weights.mood + weights.importance
    if w_total <= 0.0:
        return 0.0

    raw = (
        weights.novelty * signals.novelty
        + weights.topical * signals.topical_max_sim
        + weights.mood * signals.mood_cosine
        + weights.importance * signals.max_importance
    )
    base_score = max(0.0, min(1.0, raw / w_total))

    # Per-user depth bias (REQ-245): bias ∈ [1.0, max_bias].
    if weights.max_bias > 1.0 and signals.user_depth > 0.0:
        bias = 1.0 + (weights.max_bias - 1.0) * signals.user_depth
        base_score = min(1.0, base_score * bias)

    return base_score
