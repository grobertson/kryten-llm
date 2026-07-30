# Roadmap (Strategic): Sprint 12+

**Sprint**: 12 — `12-roadmap`
**Status**: Strategic (Future N+4 — roadmap items only; no PRD yet)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)

> **Detail level**: N+4. Strategic themes and research spikes only. Each item graduates to its
> own numbered sprint with a full PRD when prioritized.

---

## Strategic themes

### A. Cross-channel shared knowledge
Let facts learned in one channel inform the bot in another where appropriate, with strict
per-channel privacy boundaries and opt-in sharing. Research: KV/vector partitioning model,
consent, leakage prevention. **Risk**: privacy — likely the hardest governance problem.

### B. Fact confidence & verification
Attach a confidence/verification score to facts (corroboration across messages, contradiction
history from Sprint 9 Sortie 3). Retrieval and disclosure weight by confidence; low-confidence
facts are hedged ("I think alice mentioned…"). Feeds better ranking and safer disclosure.

### C. Memory-aware model routing
Use memory signal strength / context size to pick the LLM provider or model per turn (cheap
model for low-signal turns, stronger model when a rich memory-grounded reply is warranted).
Research: cost/quality trade-off, provider abstraction in `LLMManager`.

### D. Memory-quality evaluation harness
An offline harness that scores retrieval relevance, contradiction precision, and disclosure
safety against curated fixtures — turning the ad hoc per-sortie fixtures into a standing
regression suite. Enables data-driven tuning of every threshold introduced in Sprints 8–11.

### E. Right-to-export & lifecycle
Complete the governance story from Sprint 10: user data export, encryption at rest, and
per-category retention policy. Compliance-oriented.

---

## Research spikes (pre-PRD)

- Vector-store partitioning strategy for cross-channel isolation vs. sharing (Theme A).
- Confidence scoring model options and storage cost (Theme B).
- Provider-routing cost model and A/B methodology (Theme C).
- Fixture curation + metrics definition for the eval harness (Theme D).

## Prioritization notes

- **D (eval harness)** is a strong early pick — it de-risks tuning for all prior sprints and is
  privacy-neutral.
- **B (confidence)** pairs naturally with Sprint 9's contradiction work.
- **A (cross-channel)** is highest value but highest privacy risk — gate behind Sprint 10
  governance maturity.
