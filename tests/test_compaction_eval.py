"""Sprint 19, Sortie 4 — Compaction eval regression fixture (REQ-400–404)."""

from __future__ import annotations

import math

import pytest

from kryten_llm.components.memory.retention import CompactionSweeper
from tests.eval.harness import FakeEmbedder, FakeStore, seed_store, EvalFact


# ---------------------------------------------------------------------------
# Helpers: construct near-duplicate and distinct vectors deterministically
# ---------------------------------------------------------------------------


def _unit(dims: int, *hot: int) -> list[float]:
    v = [0.0] * dims
    for i in hot:
        v[i] = 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _rotated(base: list[float], angle: float) -> list[float]:
    v = list(base)
    v[0] = base[0] * math.cos(angle) - base[1] * math.sin(angle)
    v[1] = base[0] * math.sin(angle) + base[1] * math.cos(angle)
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


# 5 distinct "ground truth" directions in an 8-d space — orthogonal
GT_VECS = [
    _unit(8, 0),  # fact 0
    _unit(8, 2),  # fact 1
    _unit(8, 4),  # fact 2
    _unit(8, 6),  # fact 3
    _unit(8, 1),  # fact 4
]

# 2 near-duplicates per ground truth (angle ≈ 0.2 rad → cos ≈ 0.98 > 0.85)
ALL_VECS: list[list[float]] = []
ALL_TEXTS: list[str] = []
GT_TEXTS: list[str] = []

for i, gv in enumerate(GT_VECS):
    canonical_text = f"canonical fact {i}"
    GT_TEXTS.append(canonical_text)
    dup1 = _rotated(gv, 0.2)
    dup2 = _rotated(gv, -0.2)
    ALL_VECS.extend([gv, dup1, dup2])
    ALL_TEXTS.extend([canonical_text, f"near dup 1 of fact {i}", f"near dup 2 of fact {i}"])

assert len(ALL_VECS) == 15
assert len(GT_TEXTS) == 5


class FixedOrderEmbedder:
    """Returns ALL_VECS in order, cycling through on repeated calls."""

    id = "fixed-order"
    dimension = 8

    def __init__(self) -> None:
        self._pos = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        n = len(texts)
        result = ALL_VECS[self._pos : self._pos + n]
        self._pos += n
        return result


async def _build_fixture_store() -> tuple[FakeStore, FixedOrderEmbedder]:
    store = FakeStore()
    emb = FixedOrderEmbedder()
    for idx, (text, vec) in enumerate(zip(ALL_TEXTS, ALL_VECS)):
        user = "eval_user"
        imp = 3 if idx % 3 == 0 else 1  # canonical has higher importance
        await store.upsert(
            ids=[f"fact-{idx}"],
            vectors=[vec],
            metadatas=[
                {
                    "user": user,
                    "category": "general",
                    "importance": imp,
                    "confidence": 0.7,
                    "created_at": "2024-01-01T00:00:00+00:00",
                }
            ],
            documents=[text],
        )
    return store, emb


@pytest.mark.asyncio
async def test_compaction_reduces_facts():
    """After compaction, near-dup clusters are merged — fact count drops (REQ-400–403)."""
    store, emb = await _build_fixture_store()
    pre_count = await store.count()
    assert pre_count == 15

    sweeper = CompactionSweeper(
        store=store,
        embedder=emb,
        min_facts_to_compact=3,
        merge_threshold=0.85,
    )
    n_merged = await sweeper.sweep()

    post_count = await store.count()
    assert n_merged > 0, "at least some facts should be merged"
    assert post_count < pre_count, "store should shrink after compaction"


@pytest.mark.asyncio
async def test_compaction_preserves_ground_truth_coverage():
    """Post-compaction, at least one fact per original cluster survives (REQ-404)."""
    store, emb = await _build_fixture_store()
    await CompactionSweeper(
        store=store, embedder=emb, min_facts_to_compact=3, merge_threshold=0.85
    ).sweep()

    remaining_docs = {r["document"] for r in await store.get_all()}
    # Each of the 5 canonical texts should still be present (they have highest importance)
    for gt in GT_TEXTS:
        assert gt in remaining_docs, f"canonical fact '{gt}' missing after compaction"
