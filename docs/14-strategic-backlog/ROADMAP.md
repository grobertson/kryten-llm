# Strategic backlog (Sprint 14+)

> **SUPERSEDED** — 2026-07-30. This document served as the original strategic backlog when
> Sprint 10 was current. The canonical roadmap has moved to [`../ROADMAP.md`](../ROADMAP.md).
> This file is retained as a historical planning artefact.

**Status**: Superseded — see `docs/ROADMAP.md` for the current rolling backlog.
**Original context**: Remaining memory-roadmap themes not yet assigned a sprint.

---

## Remaining strategic themes

### A. Cross-channel shared knowledge
Let facts learned in one channel inform the bot in another where appropriate, with strict
per-channel privacy boundaries and explicit opt-in sharing. Research: KV/vector partitioning
model, consent mechanism, leakage prevention. **Risk**: hardest governance problem in the
ecosystem — gate behind Sprint 10 governance maturity and Sprint 12's disclosure-safety
scoring before designing this.

### C. Memory-aware model routing
Use memory signal strength and context size to select the LLM provider/model per turn: cheap
model for low-signal turns, stronger model when a rich memory-grounded reply is warranted.
Research: cost/quality trade-off measurement, provider abstraction in `LLMManager`.
**Note**: requires Sprint 12 eval harness to have objective quality baselines.

### E. Right-to-export & lifecycle
Complete the governance story from Sprint 10: user data export (right-to-portability),
encryption at rest for the fact store, and per-category retention policies. Compliance-oriented.
Depends on Sprint 10's governance primitives.

---

## Research spikes (pre-PRD)

- Vector-store partitioning strategy for cross-channel isolation vs. sharing (Theme A).
- Provider-routing cost model and A/B methodology (Theme C).
- Encryption-at-rest options for Chroma and pgvector (Theme E).

## Prioritization notes

- **Theme C** (model routing) is well-isolated and useful without cross-channel concerns;
  natural candidate for Sprint 14 once Sprint 12 has quality baselines.
- **Theme E** (export/lifecycle) extends Sprint 10's governance; schedule after Sprint 10
  ships and confidence grows in the retention model.
- **Theme A** (cross-channel) is highest value but highest privacy risk; treat as the
  long-term goal after Themes B (confidence, Sprint 13), C, and E are in place.

## Rolling sprint ladder (current view)

| Sprint | Status | Theme |
|--------|--------|-------|
| 10 | 🚀 Current (N) | Memory Privacy & Governance |
| 11 | 📋 Planned (N+1) | Adaptive Engagement |
| 12 | 📝 Draft (N+2) | Eval Harness |
| 13 | 💡 Ideation (N+3) | Fact Confidence |
| 14+ | 🎯 Strategic | Model Routing (C) → Lifecycle (E) → Cross-channel (A) |
