# PRD: Semantic Fact Compaction

**Sprint**: 19 — `19-fact-compaction`
**Status**: Current (N) — Sorties 1–4 ready for implementation
**Builds on**: Sprints 8–18 (memory surfaces, quality, governance, eval, confidence,
  model routing, calibration)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)
**REQs**: REQ-385 – REQ-404

---

## 1. Executive Summary

Insertion-time deduplication (`dedup_novelty_max` = 0.08, cosine distance ≤ 0.08 = similarity
≥ 0.92) catches only near-identical re-statements at insert time. Over weeks of chat,
semantically equivalent but differently-phrased facts accumulate: *"likes action movies"*,
*"enjoys thriller films"*, *"prefers intense cinema"* — three vector store slots for one
real preference. Sprint 19 adds a background `CompactionSweeper` that clusters near-duplicates
by cosine similarity and merges each cluster into a single canonical fact, accumulating
importance and averaging confidence. Default-off, zero latency on the response path, and
includes a `--dry-run` CLI for safe auditing before enabling.

---

## 2. Problem Statement

The insertion-time deduplication catches only re-statements made in close proximity with
similarity ≥ 0.92. Over weeks of chat, the 0.85–0.92 similarity band fills with logically
equivalent facts. The effects compound over time:

- **Retrieval noise**: top-K slots wasted on re-phrasings of the same concept, crowding out
  genuinely distinct information.
- **Diluted importance**: corroboration increments scatter across near-duplicates rather than
  concentrating on one canonical fact.
- **Miscalibrated confidence**: Sprint 13 corroboration boosts go to whichever near-duplicate
  happens to be the nearest neighbour at insert time, not to a single authoritative fact.
- **Store bloat**: unbounded accumulation in long-running deployments.

**Who benefits**: operators (smaller, faster stores), the community (more diverse retrieval
per turn), and Sprint 21 proactive injection (which improves when the store is clean and
confidence is concentrated on canonical facts).

---

## 3. Goals and Success Metrics

| Metric | Target |
|--------|--------|
| `recall@5` post-compaction (Sprint 12 harness) | ≥ pre-compaction baseline |
| Facts reduced on seeded near-duplicate fixture | ≥ 10% reduction per user |
| No fact text silently discarded | Canonical = highest-importance fact's text |
| No cross-user merges | Scope strictly to single user |

**Non-regression gate**: Sprint 12 eval harness is extended with a compaction fixture
(Sortie 4) that seeds near-duplicates, runs compaction, and asserts recall@5 is not reduced.

---

## 4. User Stories

- *As an operator*, I want a compaction job that merges near-duplicate facts so the store
  stays lean without manual curation.
- *As a maintainer*, I want compaction to be runnable offline (`--dry-run`) or as a
  background sweep, so it never blocks response generation.
- *As a maintainer*, I want to configure the similarity threshold for merging so I can tune
  conservatively (high threshold = only near-identical) or aggressively.
- *As a community member*, I want the bot to surface more varied information about me per
  turn rather than repeatedly hitting the same conceptual territory.

---

## 5. Technical Architecture

### 5.1 CompactionSweeper

Lives in `kryten_llm/components/memory/retention.py` alongside `RetentionSweeper` and
`ConfidenceDriftSweeper`. Takes `store`, `embedder`, `interval_hours`, `min_facts_to_compact`,
`merge_threshold`, `importance_cap`, `health_monitor`.

**Algorithm (per user):**
1. `get_all(where={"user": uid})` — fetch all facts for the user.
2. If `len(records) < min_facts_to_compact`, skip.
3. Re-embed all fact texts via the injected `Embedder`.
4. **Greedy cluster** (importance-descending): iterate facts from highest- to
   lowest-importance; each unassigned fact either joins the first cluster whose seed
   achieves cosine similarity ≥ `merge_threshold`, or seeds a new cluster.
5. For clusters of size ≥ 2:
   - **Canonical text**: the highest-importance fact's text (the cluster seed).
   - **Merged importance**: `min(sum(importances), importance_cap)`.
   - **Merged confidence**: weighted average by importance.
   - **Timestamps**: keep earliest `created_at`; set `last_seen = now()`.
6. Delete non-canonical members via `store.delete_ids()`.
7. Update canonical metadata via `store.update_metadata()`.
8. Return total `n_merged` (facts deleted).

**Re-embedding cost**: For a 200-fact-cap user with the local ONNX embedder, re-embedding
takes ~0.1 s. Running once daily at off-peak is negligible.

**Threshold guidance**: `merge_threshold = 0.85` (conservative default). The dedup floor
at 0.92 is stricter; compaction targets the 0.85–0.92 band that dedup misses.

### 5.2 CLI command

`kryten-llm memory compact [--user USER] [--dry-run] [--threshold FLOAT]`

Reuses `CompactionSweeper` with `dry_run=True`: logs the cluster plan without writing.

### 5.3 Config block

```json
"compaction": {
  "enabled": false,
  "interval_hours": 24,
  "min_facts_to_compact": 10,
  "merge_threshold": 0.85,
  "importance_cap": 10000
}
```

### 5.4 Observability

`HealthMonitor.record_memory_facts_compacted(n)` increments
`_memory_facts_compacted_total`. Mirrors `_memory_facts_expired_total` (Sprint 10).

---

## 6. Dependencies

| Sprint | Dependency |
|--------|------------|
| Sprint 10 | `RetentionSweeper` pattern; `service.py` sweeper wiring |
| Sprint 12 | Eval harness for non-regression test |
| Sprint 13 | `confidence`, `importance` metadata fields |
| Sprint 18 | `ConfidenceDriftSweeper` pattern; `update_metadata` on `VectorStore` |

`VectorStore` requires `get_all(where)`, `delete_ids(ids)`, `update_metadata(ids, metadatas)`
— all implemented since Sprint 10/18.

---

## 7. Security and Privacy

Compaction operates strictly within a single user's fact corpus; there is no cross-user merge
path. Facts are never transmitted to external systems during compaction. The `--dry-run` flag
provides a safe audit path with no store writes.

---

## 8. Rollout Plan

1. **Sortie 1**: `CompactionSweeper` core algorithm + unit tests. No service wiring.
2. **Sortie 2**: CLI `kryten-llm memory compact` command. Manual runs possible.
3. **Sortie 3**: `CompactionConfig` in `models/config.py`; `service.py` wiring;
   `HealthMonitor.record_memory_facts_compacted`; `config.example.json`.
   Default `enabled: false` — no change to existing deployments.
4. **Sortie 4**: Eval regression fixture in Sprint 12 harness.
5. **Operator opt-in**: Set `compaction.enabled: true`, `merge_threshold: 0.85`.
   Monitor `llm_memory_facts_compacted_total` for first few runs. Tune threshold if needed.

---

## 9. Future Enhancements

- LLM-assisted text synthesis: merge a cluster's texts into one canonical sentence rather
  than inheriting the highest-importance fact's text verbatim.
- Per-category compaction thresholds (e.g., stricter for `preference` than for `activity`).
- Union of `category` tags across merged facts (currently canonical's category is inherited).
- Post-compaction statistics in `inspect.user` output.

---

## 10. Open Questions

**Resolved at promotion:**
- Separate task or retention sweeper loop? → Separate `CompactionSweeper` (same pattern as
  `ConfidenceDriftSweeper`), running on its own interval.
- Default `merge_threshold`? → 0.85 (conservative).
- Category tags: union or canonical? → Canonical's category inherited in v1. Union deferred.
- Cross-user edge cases? → Out of scope; scope strictly to single user; never cross-user merge.
