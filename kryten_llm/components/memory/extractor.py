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
