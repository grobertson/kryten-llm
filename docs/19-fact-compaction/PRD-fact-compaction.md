# PRD (Ideation): Semantic Fact Compaction

**Sprint**: 19 — `19-fact-compaction`
**Status**: Ideation (N+3) — problem statement + user stories + feasibility only
**Builds on**: Sprints 8–18 (memory surfaces, quality, governance, eval, confidence,
  model routing, calibration)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)
**Theme**: F (Strategic Backlog)

> **Detail level**: N+3 ideation. A full PRD (10 sections) and sortie specs are written
> when promoted to N+2 or N+1. No implementation until promotion.

---

## 1. Problem Statement

The insertion-time deduplication (`dedup_novelty_max` threshold) only catches exact
re-statements made in close proximity. Over weeks of chat, the same information about a
user accumulates as semantically distinct but logically equivalent facts:

- `"likes action movies"`, `"enjoys thriller films"`, `"prefers intense cinema"`

These are separate vector store entries, each with their own importance counter and
confidence score. The effects compound over time:
- **Retrieval noise**: a top-k query returns three slots for one real fact, crowding out
  genuinely distinct information.
- **Diluted importance**: importance increments are spread across duplicates rather than
  concentrating on one canonical fact.
- **Miscalibrated confidence**: Sprint 13 corroboration boosts go to whichever near-duplicate
  happens to be the nearest neighbour at insert time, not to a single representative fact.
- **Store bloat**: unbounded accumulation for long-running deployments.

Sprint 12's eval harness shows recall@5 today; compaction would materially improve precision
without touching recall (fewer slots wasted on semantic duplicates).

**Who benefits**: operators (smaller, faster stores), the community (more diverse retrieval
per turn — the bot surfaces genuinely different things it knows), and Sprint 18/21 (calibrated
confidence and proactive injection both improve when the underlying store is clean).

---

## 2. User Stories

- *As an operator*, I want a compaction job that merges near-duplicate facts so the store
  stays lean without manual curation.
- *As a maintainer*, I want compaction to be runnable offline (CLI) or as a background sweep,
  so it never blocks response generation.
- *As a maintainer*, I want to configure the similarity threshold for merging so I can tune
  conservatively (high threshold = only near-identical) or aggressively (lower = broader merge).
- *As a community member*, I want the bot to surface more varied information about me per
  turn rather than repeatedly hitting the same conceptual territory.

---

## 3. Feasibility / Technical Read

**Where it lives**: A `CompactionSweeper` analogous to `RetentionSweeper` (Sprint 10).
The retention sweeper already has the per-user fact-query pattern and batch-delete
plumbing — compaction builds directly on that infrastructure.

**Algorithm sketch**:
1. For each user with > `min_facts` facts in the store, query all facts (no similarity
   constraint — retrieve the raw corpus).
2. Cluster by cosine similarity: facts with similarity ≥ `merge_threshold` form a cluster.
   Simple greedy approach: iterate facts in importance-descending order; assign each to an
   existing cluster if any centroid is close enough, else start a new cluster.
3. For clusters of size > 1:
   - **Canonical text**: the highest-importance fact's text (most-established statement).
   - **Merged importance**: sum of cluster importances, capped at `importance_cap`.
   - **Merged confidence**: weighted average by importance.
   - **Timestamps**: keep earliest `created_at`, use now() for `updated_at`.
4. Delete the cluster members (except canonical); upsert the merged fact.
5. Record `n_merged` in health monitor; log at INFO.

**Threshold guidance**: `merge_threshold` ≈ 0.82–0.88 is a natural band for "semantically
equivalent but differently phrased". Sprint 12's `FakeEmbedder` can be used to write
deterministic tests. The `dedup_novelty_max` (currently 0.08 = cosine distance ≤ 0.08,
i.e. similarity ≥ 0.92) is stricter than what compaction targets — compaction catches the
0.82–0.92 band that today's dedup misses.

**Backend considerations**:
- *Chroma*: `collection.get(where={"user_id": uid})` returns all facts; delete by ID list is
  supported. Compaction would issue one large `get` per user then one `delete` + one `add`
  per merged cluster.
- *pgvector*: similar; a single `SELECT … WHERE user_id = $1` + batched `DELETE` + `INSERT`.
- Both backends support this; no backend-specific code path needed beyond what already exists
  in `VectorStore`.

**Risk**: low. Compaction is additive (new background sweep) and default-off. The worst
failure mode is over-merging (threshold too low), which is recoverable: the canonical fact
retains all the text and importance of the merged cluster; nothing is silently discarded.

**Sprint 12 eval harness**: add a compaction regression fixture that seeds duplicates, runs
compaction, and asserts post-compaction recall@5 is ≥ pre-compaction (merging should never
reduce recall).

---

## 4. Rough Scope (candidate sorties)

1. **CompactionSweeper** — core algorithm: cluster, merge, delete/upsert, health metrics.
2. **CLI command** — `kryten-llm memory compact [--user USER] [--dry-run]` for offline runs.
3. **Config & integration** — `compaction` block in `LLMConfig`; optional scheduling
   alongside retention sweeper; `llm_memory_facts_compacted_total` metric.
4. **Eval regression** — duplicate-seeding fixture + post-compaction recall@5 assertion in
   the Sprint 12 eval harness.

---

## 5. Open Questions

- Should compaction run in the same sweep loop as retention, or as a separate scheduled task?
- What is the right default `merge_threshold`? (Propose 0.85 as a conservative start.)
- Should compacted facts merge their `category` tags (union) or inherit from the canonical?
- How do we handle cross-user compaction edge cases — e.g., two users with nearly identical
  facts about themselves? (Answer: scope strictly to single-user; never cross-user merge.)

**REQ reservation**: REQ-380+ (finalised at promotion).
