"""Fact and FactExtractor interface definitions.

Phase 7b: REQ-030 through REQ-033.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

#: Stable category labels mirroring the factfinder.py prototype.
FACT_CATEGORIES = frozenset(
    {
        "preference",
        "habit",
        "past",
        "life_context",
        "self_description",
        "misc",
    }
)


@dataclass
class Fact:
    """A single durable fact extracted from a user message.

    All fact records MUST carry the metadata fields listed in REQ-016.
    """

    user: str
    """Canonical username this fact belongs to (the memory key)."""

    category: str
    """One of: preference | habit | past | life_context | self_description | misc."""

    summary: str
    """Short, paraphrased statement suitable for injection into a prompt."""

    evidence: dict[str, Any] = field(default_factory=dict)
    """Provenance info: ``{line, time, message}`` (REQ-016)."""

    score: float = 0.0
    """Relevance / quality score from the extractor.

    Used by the provider when applying the ``write.min_message_score`` gate.
    """

    source: str = "live"
    """``"live"`` for messages observed in real-time; ``"seed"`` for bulk imports."""

    created_at: str = ""
    """ISO-8601 timestamp string; filled in by the provider before upsert."""


@dataclass
class ExtractedFact:
    """Pure output of an extractor for one candidate fact (Phase 7f).

    Distinct from :class:`Fact`: this carries the LLM-emitted scoring signals
    (``confidence``, ``sentiment``) but **no datastore state** — ``novelty`` and
    ``importance`` are computed/owned by the provider, never the extractor
    (REQ-010, side-effect free).
    """

    target_user: str
    """Username the fact is about (attribution target)."""

    category: str
    """One of the :data:`FACT_CATEGORIES`."""

    summary: str
    """Short paraphrased fact (≤ ~120 chars, GUD-002)."""

    confidence: float
    """0..1 attribution certainty that the fact is about ``target_user`` (REQ-030)."""

    sentiment: float
    """0..1 affect (1 positive, 0 negative, 0.5 neutral); metadata only (REQ-031)."""

    evidence: dict[str, Any] = field(default_factory=dict)
    """Provenance: ``{index, time, message}`` into the supplied window (REQ-012)."""


class FactExtractor(Protocol):
    """Interface every fact extractor must satisfy.

    REQ-030: Pure transform — no side-effects.
    REQ-033: Persistence is the provider's responsibility, not the extractor's.
    """

    async def extract(self, messages: list[dict[str, Any]], user: str) -> list[Fact]:
        """Extract candidate facts from *messages* attributed to *user*.

        Args:
            messages: List of ``{"username": ..., "message": ...}`` dicts.
            user: The username whose facts are being extracted.

        Returns:
            List of :class:`Fact` records (may be empty).
        """
        ...


# ---------------------------------------------------------------------------
# Extractor registry (spec §4.3)
# ---------------------------------------------------------------------------

#: Registry: config ``extractor.type`` → extractor class.  Populated by the
#: ``@register_extractor`` decorator when each extractor module is imported.
#: Mirrors ``EMBEDDER_REGISTRY`` / ``VECTOR_STORE_REGISTRY``.  Construction still
#: happens in ``LongTermMemoryProvider`` because extractors have different
#: dependency shapes (heuristic ← write config; llm ← a dedicated ``LLMManager``).
EXTRACTOR_REGISTRY: dict[str, type] = {}


def register_extractor(type_key: str):
    """Class decorator that registers an extractor under *type_key*."""

    def _decorator(cls: type) -> type:
        EXTRACTOR_REGISTRY[type_key] = cls
        return cls

    return _decorator
