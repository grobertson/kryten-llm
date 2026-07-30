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

### Sprint 17 — Cross-Channel Shared Knowledge (N+1)
_Ideation PRD written; full 10-section PRD + sortie specs authored at promotion to Current._

Facts learned in one channel are today invisible to the bot in another channel, even under the
same operator. S17 adds opt-in cross-channel sharing with strict per-channel consent gates: a
user's facts from channel A are only available in channel B if both the operator and the user
have explicitly enabled sharing. The `forget.user` command must cascade correctly across all
consented channels to preserve the erasure guarantee from Sprint 10.

**Primary dependencies**: S10 (governance/erasure), S12 (disclosure regression gate), S15 (routing
context — cross-channel facts affect signal strength).

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

The following themes are candidates for S19+. They are not commitments — each graduates to a
numbered sprint with a full PRD when prioritized. **This is the discussion agenda.**

### F. Semantic Fact Compaction (S19 candidate)
As the corpus matures, near-duplicate facts accumulate: "likes action movies", "enjoys
thrillers", "prefers intense films" are semantically related but stored as separate facts.
Compaction would: cluster semantically similar facts, merge them into a single canonical
statement, distribute the accumulated importance/confidence across the merged fact, and prune
the originals. Effect: smaller store, higher retrieval precision, cleaner confidence signals.

**Builds on**: S9 (quality), S12 (eval harness for regression testing), S13 (confidence — merged
fact inherits blended confidence), S18 (calibrated decay — compaction interacts with decay math).
**Risk**: low. Self-contained, no user-facing contract changes. Natural ops-hygiene sprint.
**Suggested priority**: schedule immediately after S18 if corpus growth is observable.

### G. Proactive Memory Injection (S19/S20 candidate)
Today the bot draws on memory only when a trigger fires (mention, name, keyword). Proactive
mode: during each turn, scan high-confidence facts for topical relevance to the *current
message* even without an explicit trigger, and surface them naturally if the relevance score
crosses a threshold. Shifts the bot from reactive to genuinely participatory — it can connect
what someone just said to something it knows about them without being called on.

**Builds on**: S11 (engagement score controls *when* to be proactive), S13 (confidence gates
which facts are safe to surface unprompted), S15 (routing — a proactive enrichment turn
warrants a stronger model), S18 (calibration — must not surface low-confidence facts as if
they're certain).
**Risk**: medium. The wrong threshold produces intrusive or embarrassing non-sequiturs. Gate
behind S18 so confidence scores are well-calibrated before using them to drive unprompted speech.
**Suggested priority**: S19 or S20 depending on confidence calibration outcomes.

### H. Temporal Fact Awareness (S20 candidate)
Facts currently carry age via TTL but have no first-observed / last-corroborated timestamps
exposed to the retrieval layer. Adding temporal metadata enables: recency-weighted retrieval
(prefer a fact corroborated last week over one from two years ago), "how long ago" hedging in
responses ("you mentioned this a while back…"), and a richer decay model where dormant facts
drift downward in confidence even without contradiction (complementary to S18's temporal drift
scope but more structurally thorough).

**Builds on**: S9 (quality layer), S13 (confidence), S18 (temporal decay — H makes the decay
work structurally rather than as a sweep).
**Risk**: low–medium. Requires a schema migration on the fact store; plan accordingly.
**Suggested priority**: can be combined with F (compaction) as a "corpus health" sprint.

### I. Ecosystem Memory Integration (S21+ candidate)
Other Kryten services (economy, moderator) operate in the same channel but in separate data
silos. A controlled read-only query API on the LLM fact store — keyed by user, returning
relevant facts in structured form — would let the economy service personalize rewards, let the
moderator apply context-aware nuance, and give the API gateway a richer user-profile surface.
Not a free-for-all: the integration API must respect the same erasure and consent gates as the
memory service itself.

**Builds on**: S10 (erasure — any integration must respect forget semantics), S17 (cross-channel
partition model informs multi-service access control).
**Risk**: high architectural reach. Do not begin design until S17's isolation model is proven
in production. This is the long-horizon integration goal.
**Suggested priority**: S21 at the earliest; treat as a post-S19/20 capstone.

---

## Prioritization Notes

```
S15 (current) → S17 (cross-channel) → S18 (calibration)
                                              │
                              ┌───────────────┴────────────────┐
                              ▼                                 ▼
                    F: Compaction (S19)              G: Proactive injection (S19/20)
                    H: Temporal awareness (S20)
                              │
                              └──────────────────┐
                                                 ▼
                                    I: Ecosystem integration (S21+)
```

- **F (compaction)** is low-risk ops-hygiene; fits naturally after S18 and before proactive
  features that depend on a clean, well-calibrated store.
- **G (proactive injection)** is the highest user-visible value theme post-S18, but requires
  S18's calibrated confidence to avoid intrusive mistakes. Target S19 or S20.
- **H (temporal awareness)** can be bundled with F as a "corpus health" sprint or tackled
  standalone; either way it pays compound dividends for G and I.
- **I (ecosystem integration)** is the highest architectural ambition. Defer until the memory
  system itself (isolation, calibration, compaction) is mature and battle-tested.

---

## Rolling Sprint Ladder (current view)

| Sprint | Status | Theme |
|--------|--------|-------|
| 13 | ✅ Complete | Fact Confidence |
| 14 | ✅ Complete | Strategic Backlog (planning only) |
| 15 | 🚀 Current (N) | Memory-Aware Model Routing |
| 16 | ❌ Dropped | Right-to-Export & Lifecycle |
| 17 | 📋 Next (N+1) | Cross-Channel Shared Knowledge |
| 18 | 💡 Draft (N+2) | Confidence Calibration & Decay Hardening |
| 19 | 🎯 Strategic | Compaction (F) / Proactive Injection (G) |
| 20 | 🎯 Strategic | Temporal Awareness (H) |
| 21+ | 🔭 Long-horizon | Ecosystem Integration (I) |
