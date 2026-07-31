# kryten-llm Memory System — Rolling Roadmap

**Last updated**: 2026-07-31
**Canonical location**: `docs/ROADMAP.md`
_(supersedes [`docs/14-strategic-backlog/ROADMAP.md`](14-strategic-backlog/ROADMAP.md), which is retained as a historical artefact)_

---

## Completed Sprints

| Sprint | Theme | Key Deliverables |
|--------|-------|-----------------|
| 8 | Associative Memory | Vector store, fact extraction, associative retrieval pipeline |
| 9 | Memory Quality | Deduplication, importance scoring, novelty signal |
| 10 | Memory Privacy & Governance | `forget.user`, operator forget, retention TTLs, PII hardening |
| 11 | Adaptive Engagement | Engagement score, per-user eagerness knob, silent pre-check |
| 12 | Eval Harness | Eval CLI, `FakeEmbedder`/`FakeStore`, recall@5 ≥ 60% baseline |
| 13 | Fact Confidence | `confidence` field, corroboration boost, contradiction decay, hedged templates |
| 15 | Memory-Aware Model Routing | Context-signal computation, provider tier routing, observability, per-trigger overrides |
| 17 | Multi-Instance Shared Memory | Shared-store pattern validated; concurrent write safety; `store_mode` observability; deployment guide |
| 18 | Confidence Calibration & Decay Hardening | Calibration metric, importance-gated contradiction decay, `ConfidenceDriftSweeper` |

> **Note on numbering**: Sprint 14 was a planning-only sprint (strategic backlog triage; no
> implementation). Sprint 16 was dropped (see below). Sprint numbers 17+ are fixed.
> Sprint 20.5 is a micro-sprint inserted between S20 and S21 (see below).

---

## Dropped

| Sprint | Theme | Reason |
|--------|-------|--------|
| 16 | Right-to-Export & Memory Lifecycle | GDPR / data-portability compliance is not a requirement for this deployment. Sprint 10's `forget.user` + retention TTLs cover the erasure contract that matters. Over-engineered for the use-case. |

---

## Active Planning Horizon

| Sprint | Theme | Status | Docs |
|--------|-------|--------|------|
| 19 | Semantic Fact Compaction | 🚀 **Current (N)** | [docs/19-fact-compaction/](19-fact-compaction/) |
| 20 | Temporal Fact Awareness | 📋 **Next (N+1)** | [docs/20-temporal-awareness/](20-temporal-awareness/) |
| 20.5 | Temporal-Accurate Bulk Import | 📋 **Planned** | [docs/20.5-temporal-bulk-import/](20.5-temporal-bulk-import/) |
| 21 | Proactive Memory Injection | 💡 **Planned (N+2)** | [docs/21-proactive-injection/](21-proactive-injection/) |
| 22+ | Ecosystem Memory Integration | 🔭 **Long-horizon** | No PRD yet |

### Sprint 19 — Semantic Fact Compaction (Current)

A background `CompactionSweeper` clusters near-duplicate facts (cosine similarity ≥
`merge_threshold`, default 0.85) and merges each cluster into a single canonical fact,
accumulating importance and averaging confidence. Runs on a configurable interval, default
off. Prerequisite for reliable proactive injection (S21).

**Sorties**: 4 — core sweeper algorithm, CLI (`memory compact`), config & service wiring,
eval regression fixture.  
**Builds on**: S9 (dedup), S12 (eval harness), S13 (confidence blending), S18 (sweeper pattern).  
**Risk**: low.

### Sprint 20 — Temporal Fact Awareness (Next)

Upgrades `_recency_factor` from a fixed hyperbolic formula to a configurable exponential
half-life (`exp(-age_days / half_life_days)`). Fixes a gap where heuristic-mode facts had
no `last_seen` field, silently disabling recency ranking. Adds `recency_days` to
`ContextFragment` and age-band hedging to `trigger.j2` ("back in the day…"). Provides a
`backfill-last-seen` CLI tool for existing stores.

**Sorties**: 4 — recency score fix + `last_seen` in heuristic upsert; temporal hedging &
`recency_days`; backfill CLI; config/eval.  
**Builds on**: S9 (`_rank_with_boost`), S13 (confidence/importance metadata), S18 (drift sweeper).  
**Risk**: low.

### Sprint 20.5 — Temporal-Accurate Bulk Import (Planned, after S20)

A micro-sprint addressing the `memory seed` command's silent timestamp problem: both the
heuristic and LLM seed paths write `created_at = now()`, making all seeded facts appear
brand-new regardless of when the original chat messages were sent. Adds a log-date
reconstructor that infers calendar dates from midnight crossings in the `HH:MM:SS`-only
log format, anchored to the file's mtime (or an explicit `--log-end-date` override). Also
adds `memory reset --confirm` to safely clear a store before re-seeding.

**Sorties**: 3 — date reconstruction module + tests; seed path upgrade (heuristic + LLM);
CLI (`--log-end-date`, `memory reset`).  
**Builds on**: S20 Sortie 1 (`last_seen` in heuristic path must exist before S20.5 is meaningful).  
**Operator note**: stop any in-flight seed run, run `memory reset --confirm`, then re-seed.  
**Risk**: low.

### Sprint 21 — Proactive Memory Injection (Planned, after S19 + S20)

After the standard trigger-driven speaker-scope pull, a fast synchronous check tests whether
the top-ranked fact has cosine similarity ≥ `proactive_threshold` to the current message AND
confidence ≥ `proactive_min_confidence`. If both gates pass, the fact is emitted as a
`proactive_memory` context fragment — even when the bot was not addressed. Shifts the bot
from reactive to genuinely participatory. Default off; requires a clean, calibrated store.

**Sorties**: 4 — proactive scope in `LongTermMemoryProvider`; template integration
(`trigger.j2`, `system.j2`); config & `from_config` wiring; observability (metrics, debug log).  
**Builds on**: S13 (confidence gate), S18 (calibration required), S19 (clean store recommended),
S20 (`recency_days` as future gate).  
**Hard gate**: S18 ✅ + S19 complete. Miscalibrated or noisy facts make this harmful.  
**Risk**: medium — threshold tuning is critical; start conservative at 0.80.

### Sprint 22+ — Ecosystem Memory Integration (Long-horizon)
_No PRD yet. No sorties planned. Requires S17–S21 proven in production._

Controlled read-only query interface exposing the LLM fact store to economy, moderator, and
api-gate services — enabling cross-service personalization without breaking per-deployment
isolation. Requires S17's shared-store pattern battle-tested and S10's erasure semantics
operating correctly at scale.

---

## Implementation Notes

### `VectorStore` API audit required before Sprint 19

`CompactionSweeper` (S19 Sortie 1) calls `get_all()`, `update_metadata()`, and `delete_ids()`.
Sprint 20.5 Sortie 3 adds `reset()`. Verify all four methods exist on both the Chroma and
pgvector backends before beginning S19 work. Missing methods must be added first.

### Sprint ordering constraint

```
S19 (compaction) → S20 (temporal awareness) → S20.5 (bulk import fix) → S21 (proactive)
```

S20.5 must follow S20: Sprint 20 Sortie 1 establishes `last_seen` in the live heuristic
upsert path; Sprint 20.5 then threads `historical_ts` through the seed path. Reversing this
order produces a partially-wired state.

### `_run_speaker_scope` refactor (S20 + S21 interaction)

Sprint 20 Sortie 2 adds `recency_days` computation inside `_run_speaker_scope`. Sprint 21
Sortie 1 refactors `_run_speaker_scope` to return raw query results for reuse by the
proactive scope (avoiding a second store query). Both changes touch the same method.
Whoever implements S21 Sortie 1 must integrate both cleanly.

---

## Dependency Graph

```
S17 ✅  S18 ✅
         │
         ├──────────────────────────┐
         ▼                          ▼
  S19: Compaction          (parallel possible)
         │
         ▼
  S20: Temporal awareness
         │
         ▼
  S20.5: Bulk import fix
         │
         ▼
  S21: Proactive injection
         │
         ▼
  S22+: Ecosystem integration  ← horizon edge; no PRD
```

---

## Rolling Sprint Ladder (current view)

| Sprint | Status | Theme |
|--------|--------|-------|
| 13 | ✅ Complete | Fact Confidence |
| 14 | ✅ Complete | Strategic Backlog (planning only) |
| 15 | ✅ Complete | Memory-Aware Model Routing |
| 16 | ❌ Dropped | Right-to-Export & Lifecycle |
| 17 | ✅ Complete | Multi-Instance Shared Memory |
| 18 | ✅ Complete | Confidence Calibration & Decay Hardening |
| 19 | 🚀 **Current (N)** | Semantic Fact Compaction — PRD + 4 sortie specs ready |
| 20 | 📋 Next (N+1) | Temporal Fact Awareness — PRD + 4 sortie specs ready |
| 20.5 | 📋 Planned | Temporal-Accurate Bulk Import — PRD + 3 sortie specs ready |
| 21 | 💡 Planned (N+2) | Proactive Memory Injection — PRD + 4 sortie specs ready; gated on S18+S19 |
| 22+ | 🔭 Long-horizon | Ecosystem Integration — no PRD; **planned work ends here** |
