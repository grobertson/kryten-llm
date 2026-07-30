# PRD (Lite): Adaptive Engagement

**Sprint**: 11 — `11-adaptive-engagement`
**Status**: Ideation (Future N+3 — problem statement + user stories + feasibility only)
**Builds on**: Sprints 8–10 (memory, quality, governance)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)

> **Detail level**: N+3. This captures the problem, user stories, and a feasibility read only.
> A full PRD (10 sections) and sortie specs are written when this is promoted toward "next".

---

## 1. Problem Statement

Auto-participation today decides **when** to speak with a message-count threshold plus rate
limits ([trigger_engine.py](../../kryten_llm/components/trigger_engine.py),
`auto_participation` config). It ignores the rich signals Sprint 8 added — topical relevance,
novelty, and ambient mood. As a result the bot can speak up when it has nothing relevant to
add, or stay silent when it has a genuinely apt callback or reaction. We want engagement that
is **adaptive**: speak more when the bot has something good to say (strong topical/novelty
signal, matching mood) and less otherwise, without becoming annoying.

**Who benefits**: the community (fewer low-value interjections, better-timed good ones) and
operators (engagement that self-tunes instead of manual threshold fiddling).

## 2. User Stories

- *As a community member*, I want the bot to chime in when it actually has a relevant memory or
  reaction, not just because N messages passed.
- *As a community member*, I want it to stay quiet when it has nothing to add, so it never feels
  spammy.
- *As an operator*, I want engagement to factor in memory signal strength, so I can tune "how
  eager" rather than a raw message count.
- *As a returning user*, I want the bot to be more likely to greet/callback me when it holds a
  strong, apt memory about me.

## 3. Feasibility / Technical Read

- **Signals already exist or land in Sprints 8–9**: topical similarity (Sortie 1), novelty
  (Sortie 6), ambient mood (Sortie 7), and salience/boost scores (Sprint 9). These can feed a
  pre-response "should I speak?" score.
- **Integration point**: `trigger_engine` auto-participation decision — augment the threshold
  with a memory-signal gate/score, still bounded by existing rate limits and spam checks
  (`rate_limiter`, `spam_detector`) so we can't regress into spam.
- **Risk**: coupling the trigger decision to retrieval adds latency to the *silent* path
  (we'd compute retrieval to decide whether to speak). Mitigate with a cheap pre-check
  (novelty from the already-fetched nearest fact; mood cosine) before full retrieval.
- **Privacy**: no new disclosure — this changes *timing*, not *content*; all Sprint 8 gates
  still apply when a message is actually generated.
- **Measurability**: depends on Sprint 9 Sortie 5 observability to tune engagement rates.

## 4. Rough Scope (candidate sorties — not yet specced)

- Memory-signal engagement score feeding the auto-participation decision.
- Cheap pre-retrieval gate to avoid latency on the silent path.
- Per-user engagement bias (stronger apt memory → higher greet/callback probability).
- Operator "eagerness" knob replacing/augmenting the raw message-count threshold.
- Guardrails: hard rate-limit ceilings, cooldowns, anti-spam interaction tests.

## 5. Open Questions

- Does computing a "should I speak?" signal on every message cost too much on the silent path?
  (Likely need the cheap pre-check.)
- How to evaluate engagement quality without a human-rated feedback loop?
- Should engagement bias be per-user, per-channel, or both?

**Rough REQ reservation**: 220–249 (finalized at promotion).
