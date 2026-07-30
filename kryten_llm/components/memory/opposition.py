"""Embedding-based opposition scoring for contradiction detection.

Sprint 9, Sortie 3 (REQ-140/141). A message contradicts a stored fact when it is
*topically close* (already gated by the caller) but *semantically opposed*. We
approximate opposition by asking whether the message aligns more with a
negation-augmented form of the fact ("not {fact}") than with the fact itself —
using the same embedder, no store round-trip, no extra dependency.
"""

from __future__ import annotations

import logging
import math
from typing import Protocol

logger = logging.getLogger(__name__)


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


async def opposition_score(message: str, doc: str, embedder: _Embedder) -> float | None:
    """Return an opposition score in roughly [-1, 1], or ``None`` on failure.

    Positive → the message aligns more with the *negation* of the fact than with
    the fact (a likely contradiction/update). ``None`` signals the caller to fall
    back to the keyword heuristic (REQ-144).
    """
    if not message or not doc:
        return None
    try:
        vecs = await embedder.embed([message, doc, f"not {doc}"])
    except Exception as exc:  # embedder unavailable → caller falls back
        logger.debug(f"opposition_score: embed failed: {exc}")
        return None
    if not vecs or len(vecs) < 3:
        return None
    m, d, nd = vecs[0], vecs[1], vecs[2]
    return _cosine(m, nd) - _cosine(m, d)
