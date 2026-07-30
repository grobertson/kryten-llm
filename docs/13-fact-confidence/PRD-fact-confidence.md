# PRD (Lite): Fact Confidence & Verification

**Sprint**: 13 — `13-fact-confidence`
**Status**: Ideation (N+3) — problem statement + user stories + feasibility only
**Builds on**: Sprints 8–12 (memory surfaces, quality, governance, engagement, eval harness)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)

> **Detail level**: N+3. Problem, user stories, and a feasibility read only. A full PRD (10
> sections) and sortie specs are written when this is promoted toward "next". Chosen from the
> strategic backlog (theme B) as the natural follow-on to Sprint 12's eval harness and Sprint 9's
> contradiction work.

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
