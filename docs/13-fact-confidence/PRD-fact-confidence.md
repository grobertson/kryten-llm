# PRD: Fact Confidence & Verification

**Sprint**: 13 — `13-fact-confidence`
**Status**: Current (N) — full 10-section PRD; sortie specs in progress
**Builds on**: Sprints 8–12 (memory surfaces, quality, governance, engagement, eval harness)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)

---

## 1. Executive Summary

All stored facts currently carry equal weight regardless of corroboration frequency, contradiction
history, or recency of reinforcement. Sprint 13 adds a `confidence` dimension to the memory
system: facts gain confidence when corroborated, lose it when contradicted, and the retrieval
and prompt layers reflect calibrated certainty — hedging low-confidence facts and stating
high-confidence ones assertively.

## 2. Problem Statement

- **What.** `importance` counts engagement but doesn't measure epistemic certainty.
  A fact heard once and a fact corroborated a dozen times receive identical treatment in
  retrieval and in the prompt.
- **Who.** Community members (falsely definitive statements erode trust), operators (unsafe
  to disclose uncertain facts with full confidence), and the project (Sprint 9's contradiction
  signal is unused downstream).
- **Why now.** Sprint 12's eval harness adds a concrete measurement path; confidence scores
  can be baselined and tracked. Sprint 9's contradiction detection provides the decay signal.

## 3. Goals and Success Metrics

- A `confidence ∈ [0, 1]` metadata field on every fact; defaults to a sensible baseline.
- Corroboration raises confidence; contradiction detection (Sprint 9 S3) lowers it.
- `_rank_with_boost` uses confidence as a third scoring axis.
- The prompt template hedges facts below a configurable confidence floor.
- Sprint 12 eval harness can score confidence calibration before and after.
- Success: measurable retrieval improvement on the Sprint 12 corpus; template hedging is
  accurate on labeled examples; no increase in false positives.

## 4. User Stories

- *As a community member*, I want the bot to hedge when unsure ("I think alice mentioned…"),
  so I know when I'm getting uncertain vs. well-established memory.
- *As an operator*, I want recall to weight corroborated facts higher than one-off claims.
- *As a maintainer*, I want contradiction history to lower confidence automatically, so
  contradicted facts are naturally deprioritized.
- *As a maintainer*, I want `pytest -m eval` to score confidence calibration, so regressions
  are detectable.

## 5. Technical Architecture

- **Storage**: `confidence` is a new metadata field in the JSONB/dict (additive, no schema
  migration). New facts default to `confidence = 0.5`; LLM-extracted facts inherit their
  `confidence` attribute from the extractor output.
- **Corroboration path**: `_bump_importance` also increments confidence by a small additive
  step (capped at 1.0), using an exponential decay toward the cap.
- **Contradiction path**: when `_novelty_signal` detects a contradiction (Sprint 9 S3), the
  matching stored fact's confidence is decremented by a configurable amount (floored at
  `confidence_floor`, default 0.1).
- **Retrieval**: `_rank_with_boost` gains `confidence_weight` (default 0.15) alongside
  `importance_weight` and `recency_weight`.
- **Prompt**: `ContextFragment` gains a `confidence` field (averaged from contributing facts).
  The template renders hedged or assertive phrasing based on a `confidence_hedge_below` threshold.

## 6. Dependencies

- Sprint 12 eval harness for measurement and regression testing.
- Sprint 9 contradiction detection (S3) as the decay signal.
- `_bump_importance` path in `LongTermMemoryProvider` (Sprint 7f).
- `_rank_with_boost` scoring (Sprint 7f, REQ-037).

## 7. Security and Privacy

- Confidence metadata is internal only; never exposed in chat or via `inspect.user` beyond
  the summary sentence. No PII implications.
- Confidence decay from contradictions must have a floor to prevent a malicious user from
  deliberately draining the bot's memory (adversarial contradiction spam). The floor + rate
  limit on contradiction events mitigates this.

## 8. Rollout Plan

- Ship confidence field first (default baseline, no behavioral change).
- Enable corroboration boost and confidence-weighted retrieval behind a feature flag.
- Enable template hedging as a separate opt-in.
- Measure with Sprint 12 eval harness before widening each feature.

## 9. Future Enhancements

- Per-category confidence floors (preference vs. biographical facts warrant different thresholds).
- Explicit operator commands to confirm/deny a fact (manually set confidence to 1.0 / 0.0).
- Cross-user confidence signal: if multiple users corroborate a claim, confidence rises faster.

## 10. Open Questions

- Default confidence for freshly heuristic-extracted facts (0.5 vs. `score / 100`)?
- Decay rate for contradictions — configurable or fixed?
- Should very-low-confidence facts be hidden from the prompt entirely?
- Adversarial spam guard: rate-limit contradiction-driven decays per user per day?

**REQ reservation**: REQ-280 – REQ-309 (finalized at promotion to N+1).

---

## Rough sortie outline (to be expanded at promotion)

| # | Working title | Gist | Rough REQ |
|---|---------------|------|-----------|
| 1 | Confidence field + baseline | `confidence` in metadata; defaults; no behavioral change | 280–284 |
| 2 | Corroboration boost | Increment confidence in `_bump_importance`; cap + exponential approach | 285–289 |
| 3 | Contradiction decay | Decrement confidence when Sprint 9 contradiction fires; floor guard | 290–294 |
| 4 | Confidence-weighted retrieval | Third axis in `_rank_with_boost`; config weight | 295–299 |
| 5 | Hedged template presentation | Fragment carries `confidence`; template hedges below threshold | 300–309 |


---

## 1. Problem Statement

All stored facts carry the same weight regardless of how many times a claim was corroborated,
whether it has ever been contradicted, or how recently it was reinforced. The bot can state
something it has "heard" exactly once with the same confidence as something repeated across
dozens of sessions. This makes the bot sound falsely certain about fragile knowledge, and
means low-confidence facts contribute equally to recall and disclosure decisions.

**Who benefits**: the community (hedged, calibrated replies instead of overconfident ones) and
operators (safer, verifiable disclosure). Pairs with Sprint 12's eval harness — confidence
scores are a natural metric to score.

## 2. User Stories

- *As a community member*, I want the bot to hedge its memory ("I think alice mentioned…"
  vs. "alice mentioned…") when it's not certain, so it doesn't sound falsely definitive.
- *As an operator*, I want recall to weight confirmed facts higher than one-off observations,
  so spurious or misattributed facts don't dominate the prompt.
- *As a maintainer*, I want contradiction history (from Sprint 9) to lower a fact's
  confidence over time, so contradicted facts are deprioritized automatically.

## 3. Feasibility / Technical Read

- **Storage**: `confidence ∈ [0, 1]` is a new metadata field alongside `importance` and
  `score`. It's additive: existing facts default to a baseline confidence. No schema migration
  of the vector table itself — the `metadata` JSONB/dict already absorbs new keys.
- **Update path**: `confidence` rises on corroboration (repeated similar claim in a
  `_bump_importance`-style call) and falls when the Sprint 9 contradiction signal fires.
- **Retrieval**: `_rank_with_boost` gets a third axis (confidence weight). Low-confidence
  facts surface less often and can be formatted with a hedge.
- **Prompt presentation**: the template can render high-confidence facts assertively and
  low-confidence facts hedged ("I think X mentioned…").
- **Risk**: if confidence drains too fast from valid contradictions, good facts get hedged
  unnecessarily. Needs a floor and a decay cap.
- **Dependency**: Sprint 12 eval harness can measure confidence calibration directly.

## 4. Rough Scope (candidate sorties — not yet specced)

- `confidence` metadata field; default + baseline on new facts.
- Confidence update on corroboration (in `_bump_importance` path).
- Confidence decay on contradiction signal (Sprint 9 S3 output).
- Confidence-weighted retrieval in `_rank_with_boost`.
- Hedged template formatting (low-confidence facts use softer language).

## 5. Open Questions

- What is the default confidence for freshly extracted facts?
- How fast should contradictions drain confidence? (Floor needed.)
- Should confidence affect whether a fact is stored at all (high-uncertainty rejection)?

**Rough REQ reservation**: 280–309 (finalized at promotion).
