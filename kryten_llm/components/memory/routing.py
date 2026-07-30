"""Memory-aware model routing signal (Sprint 15, Sortie 1).

Computes a per-turn ContextSignal in [0, 1] from memory richness,
fact confidence, budget usage, and trigger priority.  The signal is
consumed by LLMManager.route() to select a provider tier.

REQ-310 – REQ-314.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kryten_llm.models.config import SignalWeightsConfig

logger = logging.getLogger(__name__)


@dataclass
class ContextSignal:
    """Per-turn routing signal aggregated from the context pipeline (REQ-310).

    All components are in [0, 1].  Missing or disabled signals default to
    neutral values so compute_signal() degrades gracefully (REQ-311).
    """

    fragment_count: int = 0
    """Number of non-empty memory text fragments in the built context."""

    budget_fraction: float = 0.0
    """Fraction of the context window budget used by memory text (0–1)."""

    avg_confidence: float = 0.5
    """Average fact confidence proxy — populated from EngagementSignals.max_importance
    (Sprint 13 attribution; 0.5 when signals are absent, REQ-311)."""

    trigger_priority: float = 0.0
    """Trigger priority normalised to [0, 1] (trigger.priority / 10)."""


def compute_signal(cs: ContextSignal, weights: "SignalWeightsConfig") -> float:
    """Return a normalised routing signal in [0, 1] (REQ-310 – REQ-314).

    Each component is weighted individually.  The denominator is always the
    *total configured weight* so that absent signals degrade gracefully without
    artificially inflating the result (REQ-311).

    Args:
        cs:      Populated ContextSignal for this turn.
        weights: Per-component weights from ``routing.signal`` config.

    Returns:
        A float in [0.0, 1.0].
    """
    frag_max = max(int(weights.fragment_count_max), 1)
    fragment_score = min(cs.fragment_count / frag_max, 1.0)
    confidence_score = float(cs.avg_confidence)  # already in [0, 1]
    budget_score = float(cs.budget_fraction)  # already in [0, 1]
    trigger_score = float(cs.trigger_priority)  # already in [0, 1]

    w_f = float(weights.fragment_count)
    w_c = float(weights.avg_confidence)
    w_b = float(weights.budget_fraction)
    w_t = float(weights.trigger_priority)

    total_weight = w_f + w_c + w_b + w_t
    if total_weight <= 0.0:
        return 0.0

    raw = w_f * fragment_score + w_c * confidence_score + w_b * budget_score + w_t * trigger_score
    return max(0.0, min(1.0, raw / total_weight))
