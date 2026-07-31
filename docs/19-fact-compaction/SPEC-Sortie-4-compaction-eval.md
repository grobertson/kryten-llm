# SPEC-Sortie-4: Eval Regression Fixture

**Sprint**: 19 — Semantic Fact Compaction
**PRD**: [PRD-fact-compaction.md](PRD-fact-compaction.md)
**Status**: Planned
**Estimate**: 2h
**Depends on**: Sorties 1–3; Sprint 12 (eval harness, `FakeEmbedder`, recall@5 scorer)
**Requirements**: REQ-400 – REQ-404

---

## 1. Overview

Extend the Sprint 12 eval harness with a compaction regression fixture. Seed a store with
5 distinct ground-truth facts plus 2 near-duplicate paraphrases for each (15 facts total),
record pre-compaction recall@5, run `CompactionSweeper`, record post-compaction recall@5,
and assert that (a) at least some facts were merged and (b) recall@5 did not decrease.

---

## 2. Scope and Non-Goals

**In scope**: Compaction fixture in `tests/eval/` (or `tests/test_compaction_eval.py`);
`FakeEmbedder` paraphrase vector construction; pre/post recall@5 assertion.

**Non-goals**: Changing the Sprint 12 harness structure. Human-labeled ground truth.
Real embeddings (deterministic fake embeddings only in eval tests).

---

## 3. Requirements

- **REQ-400** — Fixture seeds one user (`"eval_user"`) with 5 distinct ground-truth facts
  + 2 near-duplicate paraphrases of each = 15 facts total. The 5 ground-truth IDs are
  tracked for recall measurement.
- **REQ-401** — `FakeEmbedder` vectors are constructed so that paraphrase pairs have cosine
  similarity ≥ `merge_threshold` (0.85) and distinct-fact pairs have cosine similarity
  < 0.85.
- **REQ-402** — Pre-compaction recall@5 is measured using the Sprint 12 harness's
  `eval_recall_at_5` function (or equivalent) querying with each ground-truth fact's text.
- **REQ-403** — `CompactionSweeper(store, embedder, merge_threshold=0.85,
  min_facts_to_compact=3)` is awaited for one full sweep.
- **REQ-404** — Assertions: `n_merged > 0`; post-compaction fact count < 15; post-compaction
  recall@5 ≥ pre-compaction recall@5.

---

## 4. Design

```python
# tests/test_compaction_eval.py  (or tests/eval/test_compaction_regression.py)
import math
import pytest
from kryten_llm.components.memory.retention import CompactionSweeper

# ---------------------------------------------------------------------------
# Vector fixture helpers
# ---------------------------------------------------------------------------

def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v


def _near_dup(base: list[float], angle_rad: float = 0.45) -> list[float]:
    """Rotate a 4-D unit vector by angle_rad → cosine_sim ≈ cos(angle_rad) ≈ 0.90."""
    v = list(base)
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    v[0], v[1] = c * base[0] - s * base[1], s * base[0] + c * base[1]
    return _unit(v)


# 5 orthogonal base facts
_BASES = [
    _unit([1, 0, 0, 0]),
    _unit([0, 1, 0, 0]),
    _unit([0, 0, 1, 0]),
    _unit([0, 0, 0, 1]),
    _unit([1, 1, 0, 0]),
]

_FACTS = [
    {"id": f"gt_{i}", "text": f"ground truth fact {i}", "base": b}
    for i, b in enumerate(_BASES)
]


async def _seed_store(store, embedder) -> list[str]:
    """Seed 5 GT facts + 2 near-dups each. Return GT IDs."""
    gt_ids = []
    for f in _FACTS:
        base_vec = f["base"]
        await store.upsert(
            ids=[f["id"]],
            vectors=[base_vec],
            metadatas=[{"user": "eval_user", "importance": 3, "confidence": 0.8,
                        "category": "test", "created_at": "2024-01-01T00:00:00+00:00",
                        "last_seen": "2025-01-01T00:00:00+00:00"}],
            documents=[f["text"]],
        )
        gt_ids.append(f["id"])
        for j in range(2):
            dup_vec = _near_dup(base_vec, angle_rad=0.45 + j * 0.05)
            dup_id = f"dup_{f['id']}_{j}"
            await store.upsert(
                ids=[dup_id],
                vectors=[dup_vec],
                metadatas=[{"user": "eval_user", "importance": 1, "confidence": 0.6,
                            "category": "test", "created_at": "2024-01-01T00:00:00+00:00",
                            "last_seen": "2025-01-01T00:00:00+00:00"}],
                documents=[f"paraphrase of fact {f['id']} variant {j}"],
            )
    return gt_ids


@pytest.mark.eval
async def test_compaction_does_not_reduce_recall(fake_vector_store, fake_embedder):
    """Seeded near-duplicates compact without reducing recall@5 (REQ-400–404)."""
    store = fake_vector_store
    embedder = fake_embedder

    gt_ids = await _seed_store(store, embedder)
    assert await store.count(where={"user": "eval_user"}) == 15

    # Pre-compaction recall@5
    pre_recall = await _measure_recall(store, gt_ids)

    sweeper = CompactionSweeper(
        store=store,
        embedder=embedder,
        merge_threshold=0.85,
        min_facts_to_compact=3,
    )
    n_merged = await sweeper.sweep()

    assert n_merged > 0, "Expected at least one merge"
    assert await store.count(where={"user": "eval_user"}) < 15, "Expected fact count to drop"

    post_recall = await _measure_recall(store, gt_ids)
    assert post_recall >= pre_recall, (
        f"Recall degraded after compaction: {pre_recall:.3f} → {post_recall:.3f}"
    )


async def _measure_recall(store, gt_ids: list[str]) -> float:
    """Fraction of GT fact IDs appearing in top-5 recall across all GT queries."""
    hits = 0
    for fact in _FACTS:
        results = await store.query(vector=fact["base"], k=5, where={"user": "eval_user"})
        returned_ids = {r.get("id") for r in results}
        if fact["id"] in returned_ids:
            hits += 1
    return hits / len(_FACTS)
```

The `fake_vector_store` and `fake_embedder` fixtures must support the `CompactionSweeper`
interface (`get_all`, `delete_ids`, `update_metadata`, `query`, `count`). If `FakeEmbedder`
is used, it needs to return the pre-seeded vector for a given text — or the test can bypass
`embedder.embed()` by pre-loading the embeddings into the sweeper via a patched `embed`.

A simpler approach: use the real `InMemoryVectorStore` if available in the test fixtures,
and pass a `FakeEmbedder` that returns the same pre-computed base vectors for the fact texts
(keyed by text substring).

---

## 5. Implementation Plan

**New file** `tests/test_compaction_eval.py`:
- `_seed_store`, `_measure_recall`, `test_compaction_does_not_reduce_recall`.
- Mark with `@pytest.mark.eval`.

**Modify** `pytest.ini` or `pyproject.toml` if the `eval` marker is not already registered.
(It likely is from Sprint 12; verify.)

---

## 6. Testing Strategy

The test itself IS the eval fixture. Additional unit coverage:
- Verify `angle_rad = 0.45` gives `cosine_sim = cos(0.45) ≈ 0.900` (≥ 0.85 merge threshold).
- Verify distinct bases give `cosine_sim < 0.1` (orthogonal).

---

## 7. Acceptance Criteria

- [ ] `n_merged > 0` after one sweep pass.
- [ ] Post-compaction fact count < 15 (at least one cluster merged).
- [ ] `post_recall >= pre_recall`.
- [ ] Test marked `@pytest.mark.eval`; excluded from default `pytest` run.
- [ ] Default `pytest` run (without `-m eval`) passes; eval test does not run.

---

## 8. Rollout

Eval tests only (`pytest -m eval`). Not in CI's default test matrix unless explicitly
added to an eval stage.

---

## 9. Documentation

`CHANGELOG.md` entry: `test: compaction eval regression fixture (Sprint 19, Sortie 4, REQ-400–404)`.
