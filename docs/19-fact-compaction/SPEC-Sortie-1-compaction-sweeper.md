# SPEC-Sortie-1: CompactionSweeper Core Algorithm

**Sprint**: 19 — Semantic Fact Compaction
**PRD**: [PRD-fact-compaction.md](PRD-fact-compaction.md)
**Status**: Planned
**Estimate**: 3–4h
**Depends on**: Sprint 10 (`RetentionSweeper` pattern, `VectorStore.get_all/delete_ids/update_metadata`), Sprint 13 (importance/confidence metadata), Sprint 18 (`ConfidenceDriftSweeper` pattern)
**Requirements**: REQ-385 – REQ-389

> **Pre-condition**: Before beginning this sortie, add `update_metadata` to the `VectorStore`
> Protocol in `vector_store.py` (it already exists on both concrete backends but is absent
> from the Protocol). Also add `reset()` while there (needed by Sprint 20.5 Sortie 3).
> This is a one-commit prep step — add stubs with `...` body to the Protocol class.

---

## 1. Overview

Implement `CompactionSweeper` in `kryten_llm/components/memory/retention.py`. The sweeper
fetches all facts per user, re-embeds the fact texts, clusters them by cosine similarity
using a **full pairwise algorithm** (repeatedly merge the most similar pair until no pair
exceeds `merge_threshold`), and merges each multi-member cluster into a single canonical
fact (highest-importance text, summed importance, weighted confidence).
Supports a `dry_run` mode that logs the plan without writing to the store.

---

## 2. Scope and Non-Goals

**In scope**: `CompactionSweeper` class with `start`/`stop`/`sweep` lifecycle; `_sweep_user`
per-user merge logic; `_greedy_cluster` helper; `dry_run` mode; unit tests in
`tests/test_compaction.py`.

**Non-goals**: Config model or service wiring (Sortie 3). CLI command (Sortie 2). Eval
fixture (Sortie 4). No LLM-assisted text synthesis — canonical text = highest-importance
fact's text verbatim.

---

## 3. Requirements

- **REQ-385** — `CompactionSweeper.__init__` accepts: `store: VectorStore`,
  `embedder: Embedder`, `interval_hours: float = 24.0`, `min_facts_to_compact: int = 10`,
  `merge_threshold: float = 0.85`, `importance_cap: int = 10000`,
  `health_monitor: Any = None`, `dry_run: bool = False`.
- **REQ-386** — `sweep()` fetches all records via `get_all()`, groups by user, calls
  `_sweep_user` for each, logs total merged count at INFO, returns total `n_merged`.
- **REQ-387** — `_sweep_user` skips users with fewer than `min_facts_to_compact` facts.
  For eligible users: re-embeds all fact texts; runs `_greedy_cluster`; for clusters of
  size ≥ 2 merges them. Returns count of facts deleted (non-canonicals removed).
- **REQ-388** — Merge rule: canonical = highest-importance fact in the cluster. Merged
  importance = `min(sum(importances), importance_cap)`. Merged confidence = weighted average
  by importance. `created_at` = earliest across cluster. `last_seen` = `now()`. Non-canonical
  members deleted via `store.delete_ids`. Canonical metadata updated via `store.update_metadata`.
- **REQ-389** — When `dry_run=True`: logs `"[dry-run] user=X cluster_size=N
  canonical='…' would_merge=M"` for each cluster ≥ 2; no store writes; returns the count
  of facts that *would* be deleted.

---

## 4. Design

```python
class CompactionSweeper:
    """Background task that merges semantically near-duplicate facts (Sprint 19, REQ-385–389).

    Runs default-off (REQ-389). Never raises into the event loop; all errors logged.
    """

    def __init__(
        self,
        store: "VectorStore",
        embedder: "Embedder",
        interval_hours: float = 24.0,
        min_facts_to_compact: int = 10,
        merge_threshold: float = 0.85,
        importance_cap: int = 10000,
        health_monitor: Any = None,
        dry_run: bool = False,
    ) -> None: ...

    def start(self) -> None:
        """Schedule the background sweep loop."""

    async def stop(self) -> None:
        """Cancel the background task."""

    async def _loop(self) -> None:
        """Sweep immediately on start, then repeat on interval."""

    async def sweep(self) -> int:
        """Full pass across all users. Returns total facts merged/deleted."""

    async def _sweep_user(self, uid: str, records: list[dict]) -> int:
        """Compact one user's facts. Returns facts deleted."""

    @staticmethod
    def _pairwise_cluster(
        records: list[dict],
        vecs: list[list[float]],
        threshold: float,
    ) -> list[list[dict]]:
        """Full pairwise clustering (O(N²) per sweep pass).

        Repeatedly finds the most similar pair of remaining facts. If their
        cosine similarity ≥ threshold, merge them into one record (keeping the
        higher-importance fact's text and id; accumulating importance; weighted
        confidence). Repeat until no pair exceeds threshold.
        The final list of records (after all merges) forms the cluster list —
        each surviving record represents one canonical fact.
        """

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        """Cosine similarity between two unit or non-unit vectors."""
```

### Merge logic detail

```python
canonical = max(cluster, key=lambda r: int(r["metadata"].get("importance", 1)))
others = [r for r in cluster if r["id"] != canonical["id"]]
total_imp = sum(int(r["metadata"].get("importance", 1)) for r in cluster)
merged_imp = min(total_imp, self._importance_cap)
weights = [int(r["metadata"].get("importance", 1)) for r in cluster]
confs = [float(r["metadata"].get("confidence", 0.5)) for r in cluster]
w_sum = max(sum(weights), 1)
merged_conf = sum(w * c for w, c in zip(weights, confs)) / w_sum
created_ats = [
    r["metadata"].get("created_at") for r in cluster
    if r["metadata"].get("created_at")
]
earliest_created = min(created_ats) if created_ats else None
now = datetime.now(timezone.utc).isoformat()
new_meta = dict(canonical["metadata"])
new_meta["importance"] = merged_imp
new_meta["confidence"] = merged_conf
if earliest_created:
    new_meta["created_at"] = earliest_created
new_meta["last_seen"] = now
```

---

## 5. Implementation Plan

**Modify** `kryten_llm/components/memory/retention.py`:
- Add `CompactionSweeper` class after `ConfidenceDriftSweeper`.

**New file** `tests/test_compaction.py`:
- Tests for all REQ-385–389 scenarios.

---

## 6. Testing Strategy

Use `FakeEmbedder` and `FakeVectorStore` (or the in-memory store already in test fixtures).

- **3 near-duplicates** (cosine sim ≥ 0.85) for one user → 1 cluster, 2 deleted, `n_merged=2`.
- **2 distinct facts** (cosine sim < 0.85) → 2 clusters, 0 deleted.
- **Merged importance** = sum, capped at `importance_cap`.
- **Merged confidence** = weighted average (higher-importance fact pulls more weight).
- **Canonical text** = text of the highest-importance fact.
- **`dry_run=True`** → no calls to `delete_ids` or `update_metadata`; correct count returned.
- **`len(records) < min_facts_to_compact`** → `_sweep_user` skips; returns 0.
- **Store `get_all` raises** → logged, `sweep()` returns 0 (no crash).
- **Per-user error** → logged, other users still processed.

To construct deterministic near-duplicate vectors:

```python
import math
base = [1.0, 0.0, 0.0, 0.0]
# paraphrase: small rotation → sim ≈ 0.87
angle = 0.5  # radians
near_dup = [math.cos(angle), math.sin(angle), 0.0, 0.0]
```

---

## 7. Acceptance Criteria

- [ ] 3 near-duplicate facts compact to 1; `n_merged = 2`.
- [ ] 2 distinct facts: `n_merged = 0`; no store writes.
- [ ] `merged_importance = min(sum, cap)`.
- [ ] `merged_confidence` is weighted average by importance.
- [ ] Canonical text unchanged.
- [ ] `dry_run=True`: no `delete_ids`/`update_metadata` calls; correct count.
- [ ] `min_facts_to_compact` guard: user with 2 facts skipped.
- [ ] Store exceptions: logged, `sweep()` returns 0.

---

## 8. Rollout

Not wired into the service at this point (Sortie 3). Usable via CLI (Sortie 2) and tests.

---

## 9. Documentation

`CHANGELOG.md` entry: `feat: CompactionSweeper core algorithm (Sprint 19, Sortie 1, REQ-385–389)`.
