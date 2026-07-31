# kryten-llm Memory System — Rolling Roadmap

**Last updated**: 2026-07-31 (v0.10.0 released — Sprint 23 release gate passed, tag cut)
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
| 19 | Semantic Fact Compaction | `CompactionSweeper` (union-find clustering), `memory compact` CLI, `CompactionConfig`, eval regression fixture |
| 20 | Temporal Fact Awareness | Configurable recency half-life, `last_seen` fix in heuristic upsert, `recency_days` on `ContextFragment`, temporal hedging in templates, `backfill-last-seen` CLI |
| 20.5 | Temporal-Accurate Bulk Import | `log_date_utils` midnight-crossing reconstructor, historically-accurate `created_at`/`last_seen` in seed paths, `memory reset --confirm` CLI |
| 21 | Proactive Memory Injection | `_run_proactive_scope` (sim + confidence dual gate), `proactive_memory` fragment, template integration, `drives_participation` config |
| 22 | Release Prep / Gap Removal | Counter bug fix (`record_memory_facts_compacted`), Sprint 19+21 metrics on `/metrics`, `drives_participation` stale-ok wiring, v0.10.0 release |

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

All sprints through 23 are complete. Sprint 23 (Release Gate) cleared the black/ruff/mypy
defects on the S18–22 code, corrected a stale CHANGELOG note, and cut the annotated
`v0.10.0` tag. **v0.10.0 is released.** No active sprint is currently running.

| Sprint | Theme | Status | Docs |
|--------|-------|--------|------|
| 19 | Semantic Fact Compaction | ✅ **Complete** | [docs/19-fact-compaction/](19-fact-compaction/) |
| 20 | Temporal Fact Awareness | ✅ **Complete** | [docs/20-temporal-awareness/](20-temporal-awareness/) |
| 20.5 | Temporal-Accurate Bulk Import | ✅ **Complete** | [docs/20.5-temporal-bulk-import/](20.5-temporal-bulk-import/) |
| 21 | Proactive Memory Injection | ✅ **Complete** | [docs/21-proactive-injection/](21-proactive-injection/) |
| 22 | Release Prep / Gap Removal | ✅ **Complete** | [docs/22-release-prep/](22-release-prep/) |
| 23 | Release Gate | ✅ **Complete** — v0.10.0 tagged | [docs/23-release-gate/](23-release-gate/) |
| 24+ | Ecosystem Memory Integration | 🔭 **Long-horizon** | No PRD yet |

### Sprint 23 — Release Gate (Complete)
_Hygiene sprint. Fixed the static-analysis defects (black on 7 files; ruff `F821`
undefined `date`; two mypy errors in `__main__.py`) that blocked a clean toolchain gate,
corrected a stale `drives_participation` CHANGELOG note, and cut the annotated `v0.10.0`
tag Sprint 22 never created. No feature or contract changes. PRD:
[docs/23-release-gate/PRD-release-gate.md](23-release-gate/PRD-release-gate.md)._

### Sprint 24+ — Ecosystem Memory Integration (Long-horizon)
_No PRD yet. No sorties planned. Requires S17–S22 proven in production._

Controlled read-only query interface exposing the LLM fact store to economy, moderator, and
api-gate services — enabling cross-service personalization without breaking per-deployment
isolation. Requires S17's shared-store pattern battle-tested and S10's erasure semantics
operating correctly at scale.

Potential early sorties once production signals are in (from Prometheus `/metrics`):
- Per-turn proactive injection rate monitoring (is `drives_participation` firing too often?)
- `CompactionSweeper` tuning based on observed merge rates (`llm_memory_facts_compacted_total`)
- Recency half-life tuning based on observed retrieval patterns

---

## Implementation Notes

_Pre-implementation constraints for S19–S21 are now resolved. These notes are retained
as a historical record._

### Resolved: `VectorStore` API completeness (before S19)

`get_all()`, `update_metadata()`, `delete_ids()`, and `reset()` are present on both the
Chroma and pgvector backends. ✅

### Resolved: Sprint ordering constraint

Implementation order was respected: S19 → S20 → S20.5 → S21 → S22. ✅

### Resolved: `_run_speaker_scope` refactor (S20 + S21)

`recency_days` and proactive scope integration were implemented cleanly in a single pass.
`_run_proactive_scope` uses `_last_message_vec` cached by `_run_speaker_scope`, avoiding
an extra embedding call. ✅

### S22 architecture note: `drives_participation` stale-ok pattern

The `drives_participation` feature (S22 S3) uses the stale-ok signal pattern established
by Sprint 11's engagement signals. When a proactive fragment fires on a triggered turn,
the provider writes `_proactive_override_signal = True` into the fragment's `data` dict;
service.py pops it and calls `TriggerEngine.set_proactive_match_signal(True)`; the engine
consumes the flag once on the next auto-participation miss. This avoids any chicken-and-egg
problem with the eagerness gate running before the context pipeline.

---

## Dependency Graph

```
S17 ✅  S18 ✅
         │
         ├──────────────────────────┐
         ▼                          ▼
  S19 ✅ Compaction          (parallel possible)
         │
         ▼
  S20 ✅ Temporal awareness
         │
         ▼
  S20.5 ✅ Bulk import fix
         │
         ▼
  S21 ✅ Proactive injection
         │
         ▼
  S22 ✅ Release prep / v0.10.0
         │
         ▼
  S23 ✅ Release Gate (cleared gate defects, cut v0.10.0 tag)
         │
         ▼
  S24+: Ecosystem integration  ← horizon edge; no PRD
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
| 19 | ✅ Complete | Semantic Fact Compaction |
| 20 | ✅ Complete | Temporal Fact Awareness |
| 20.5 | ✅ Complete | Temporal-Accurate Bulk Import |
| 21 | ✅ Complete | Proactive Memory Injection |
| 22 | ✅ Complete | Release Prep / Gap Removal — v0.10.0 code complete |
| 23 | ✅ Complete | Release Gate — gate cleared, v0.10.0 tagged |
| 24+ | 🔭 Long-horizon | Ecosystem Integration — no PRD; **planned work ends here** |}
