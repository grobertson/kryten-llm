# Strategic backlog (moved)

The strategic backlog has been promoted to its own sprint slot per the rolling-window advance.

**See**: [../14-strategic-backlog/ROADMAP.md](../14-strategic-backlog/ROADMAP.md)

This file is kept for historical reference only.

**Status**: Strategic (beyond the current 1–4 sprint window) — themes only; no PRD yet.
**Context**: These are the memory-roadmap themes **not** selected for Sprint 12. Sprint 12
took theme D (the evaluation harness — see [PRD-eval-harness.md](PRD-eval-harness.md)) because
it is privacy-neutral and de-risks tuning for all prior sprints. Each theme below graduates to
its own numbered sprint with a full PRD when prioritized.

---

## Strategic themes

### A. Cross-channel shared knowledge
Let facts learned in one channel inform the bot in another where appropriate, with strict
per-channel privacy boundaries and opt-in sharing. Research: KV/vector partitioning model,
consent, leakage prevention. **Risk**: privacy — likely the hardest governance problem; gate
behind Sprint 10 governance maturity.

### B. Fact confidence & verification
Attach a confidence/verification score to facts (corroboration across messages, contradiction
history from Sprint 9 Sortie 3). Retrieval and disclosure weight by confidence; low-confidence
facts are hedged ("I think alice mentioned…"). Pairs naturally with Sprint 9's contradiction
work and feeds safer disclosure.

### C. Memory-aware model routing
Use memory signal strength / context size to pick the LLM provider or model per turn (cheap
model for low-signal turns, stronger model when a rich memory-grounded reply is warranted).
Research: cost/quality trade-off, provider abstraction in `LLMManager`.

### E. Right-to-export & lifecycle
Complete the governance story from Sprint 10: user data export, encryption at rest, and
per-category retention policy. Compliance-oriented.

---

## Research spikes (pre-PRD)

- Vector-store partitioning strategy for cross-channel isolation vs. sharing (Theme A).
- Confidence scoring model options and storage cost (Theme B).
- Provider-routing cost model and A/B methodology (Theme C).

## Prioritization notes

- **B (confidence)** is the natural follow-on to Sprint 9's contradiction work and Sprint 12's
  harness (confidence needs measurement).
- **A (cross-channel)** is highest value but highest privacy risk — sequence after Sprint 10
  governance and Sprint 12 disclosure-safety scoring are mature.
