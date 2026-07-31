# kryten-llm Memory System — Rolling Roadmap

**Last updated**: 2026-07-30
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

> **Note on numbering**: Sprint 14 was a planning-only sprint (strategic backlog triage; no
> implementation). Sprint 16 was dropped (see below). Sprint numbers 17+ are fixed.

---

## Dropped

| Sprint | Theme | Reason |
|--------|-------|--------|
| 16 | Right-to-Export & Memory Lifecycle | GDPR / data-portability compliance is not a requirement for this deployment. Sprint 10's `forget.user` + retention TTLs cover the erasure contract that matters. Over-engineered for the use-case. |

---

## Active Planning Horizon

| Sprint | Theme | Status | Docs |
|--------|-------|--------|------|
| 15 | Memory-Aware Model Routing | 🚀 **Current (N)** | [docs/15-model-routing/](15-model-routing/) |
| 17 | Cross-Channel Shared Knowledge | 📋 **Next (N+1)** | [docs/17-cross-channel/PRD-cross-channel.md](17-cross-channel/PRD-cross-channel.md) |
| 18 | Confidence Calibration & Decay Hardening | 💡 **Draft (N+2)** | [docs/18-confidence-calibration/PRD-confidence-calibration.md](18-confidence-calibration/PRD-confidence-calibration.md) |

### Sprint 17 — Multi-Instance Shared Memory (N+1)
_Scope revised 2026-07-30. Ideation PRD rewritten; full PRD + sortie specs authored at promotion to Current._

Two kryten-llm instances (primary + secondary) in the same channel run siloed fact stores today.
S17 validates and documents the **shared-store deployment pattern**: both instances point at one
Chroma HTTP server or pgvector DB. No federation, no consent gates, no cross-channel privacy
architecture — just concurrency-safe shared access and a tested deployment guide. Substantially
smaller than originally scoped (3 sorties vs. 5; no new code architecture).

**Primary dependencies**: S8 (memory backend), S10 (forget.user semantics already correct on shared store).

### Sprint 18 — Confidence Calibration & Decay Hardening (N+2)
_Ideation PRD written; full PRD + sortie specs authored at promotion to N+1._

Sprint 13 shipped confidence as a dimension, but the default step/decay values (0.05 / 0.1)
were chosen without empirical data. S18 adds a calibration metric to the Sprint 12 eval
harness (measuring `P(fact_correct | confidence ≥ threshold)`), importance-gated contradiction
decay (high-importance facts are more resistant to a single contradiction), and optional
temporal confidence drift for facts that haven't been seen in a long time.

**Primary dependencies**: S12 (eval harness for calibration), S13 (confidence infrastructure).
Does **not** require S17; can proceed in parallel or immediately after S17.

---

## Post-S18 Strategic Themes

PRDs written for F, H, and G. Each graduates to full sortie specs when promoted to N+2.
**Dependency order: F → H → G.** Do not promote G until S18 + S19 are complete.

### F. Semantic Fact Compaction → Sprint 19
PRD: [docs/19-fact-compaction/PRD-fact-compaction.md](19-fact-compaction/PRD-fact-compaction.md)

Clusters and merges semantically near-duplicate facts (cosine similarity ≥ `merge_threshold`)
into a single canonical statement, blending importance and confidence. Runs as a
`CompactionSweeper` (analogous to the Sprint 10 `RetentionSweeper`) — default off, CLI
invokable, schedulable. Prerequisite for clean proactive injection (S21).

**Builds on**: S9, S12 (eval regression fixture), S13 (confidence blending). **Risk**: low.

### H. Temporal Fact Awareness → Sprint 20
PRD: [docs/20-temporal-awareness/PRD-temporal-awareness.md](20-temporal-awareness/PRD-temporal-awareness.md)

Exposes `last_corroborated_at` timestamps to the retrieval ranker as a `recency_score`
(`exp(-age_days / half_life_days)`). Adds temporal hedging to `trigger.j2` ("back in the
day…" vs "you mentioned recently…"). Adds passive temporal drift (confidence nudge for
dormant facts, complementing S18's contradiction decay). Requires a schema backfill.

**Builds on**: S9, S13, S18 (temporal drift scoping), S19 (canonical timestamps post-compaction).
**Risk**: low–medium (schema migration).

### G. Proactive Memory Injection → Sprint 21
PRD: [docs/21-proactive-injection/PRD-proactive-injection.md](21-proactive-injection/PRD-proactive-injection.md)

During every triggered turn, scans the speaker's high-confidence facts for topical relevance
to the current message (cosine similarity ≥ `proactive_threshold`). If a fact clears the
threshold, surfaces it as a `"proactive_memory"` fragment into context — even without a direct
trigger. On auto-participation turns, a strong proactive signal can *be* the participation
reason. Shifts the bot from reactive to genuinely participatory.

**Builds on**: S11, S13, S15, S18 (confidence gate), S19 (clean store), S20 (temporal age gate).
**Hard gate**: S18 + S19 complete first. Miscalibrated or noisy facts make this feature
harmful. **Risk**: medium (threshold tuning critical; start at 0.80).

### I. Ecosystem Memory Integration → Sprint 22+
_No PRD yet — long-horizon capstone after S17–S21 are proven in production._

Controlled read-only query API on the LLM fact store for economy/moderator/API-gate services.
Requires S17's per-deployment isolation model and S10's erasure semantics battle-tested.

---

## Prioritization Notes

```
S17 (cross-channel) → S18 (calibration)
                             │
             ┌───────────────┴───────────────┐
             ▼                               ▼
  S19: F Compaction               (can parallel S19)
  S20: H Temporal awareness
             │
             └──────────────┬───────────────┘
                            ▼
               S21: G Proactive injection
                            │
                            ▼
              S22+: I Ecosystem integration
```

- **F (compaction)** first: ops-hygiene that makes G reliable. Low risk, high compound value.
- **H (temporal awareness)** after F: timestamps become authoritative post-compaction;
  can be developed in parallel with F if bandwidth allows.
- **G (proactive injection)** last: hardest gate — needs S18 calibration *and* S19 clean
  store. The highest user-visible reward for the upstream quality work.
- **I (ecosystem integration)** long-horizon: requires S17 isolation proven in production.

---

## Rolling Sprint Ladder (current view)

| Sprint | Status | Theme |
|--------|--------|-------|
| 13 | ✅ Complete | Fact Confidence |
| 14 | ✅ Complete | Strategic Backlog (planning only) |
| 15 | ✅ Complete | Memory-Aware Model Routing |
| 16 | ❌ Dropped | Right-to-Export & Lifecycle |
| 17 | 📋 Next (N+1) | Cross-Channel Shared Knowledge |
| 18 | 💡 Draft (N+2) | Confidence Calibration & Decay Hardening |
| 19 | 🎯 Ideation (N+3) | Semantic Fact Compaction (F) |
| 20 | 🎯 Ideation (N+4) | Temporal Fact Awareness (H) |
| 21 | 🔭 Ideation (N+5) | Proactive Memory Injection (G) — gated on S18+S19 |
| 22+ | 🔭 Long-horizon | Ecosystem Integration (I) |
