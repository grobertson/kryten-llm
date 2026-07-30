# PRD (Draft): Adaptive Engagement

**Sprint**: 11 — `11-adaptive-engagement`
**Status**: Drafted (Future N+2) — PRD + rough sortie outline; specs expanded before start
**Builds on**: Sprints 8–10 (associative memory, quality, governance)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)

> **Detail level**: N+2 draft. The sortie outline below is intentionally rough; each becomes a
> full `SPEC-Sortie-{M}-{name}.md` (9-section template) when this sprint is promoted to "next".

---

## 1. Executive Summary

Sprints 8–9 gave the bot rich memory *signals* (topical relevance, novelty, ambient mood,
salience). This sprint uses those signals to make **when the bot speaks** adaptive: it speaks
up more when it has something genuinely relevant to add and stays quiet otherwise — instead of
firing on a raw message-count threshold. The goal is engagement that feels timely and
present without becoming spammy.

## 2. Problem Statement

- **What.** Auto-participation decides *when* to speak with a message-count threshold plus rate
  limits ([trigger_engine.py](../../kryten_llm/components/trigger_engine.py)); it ignores the
  memory signals Sprint 8 added. The bot can interject with nothing relevant, or stay silent
  when it holds an apt callback/reaction.
- **Who.** The community (low-value interjections vs. well-timed good ones) and operators
  (manual threshold tuning instead of self-adjusting engagement).
- **Why now.** The signals exist as of Sprints 8–9 and are observable via Sprint 9's
  telemetry; wiring them into the speak decision is the natural next step.

## 3. Goals and Success Metrics

**Goals**
- A memory-signal "should I speak?" score augments the auto-participation decision.
- A cheap pre-check avoids adding latency to the *silent* path.
- Optional per-user engagement bias (stronger apt memory → more likely to greet/callback).
- An operator "eagerness" knob replacing/augmenting the raw message-count threshold.

**Success metrics**
- Auto-participation fires more often on high-signal turns and less on low-signal turns
  (measurable via Sprint 9 telemetry: signal strength vs. fire rate).
- No p95 latency regression on the silent path (pre-check is cheap; full retrieval only when
  likely to speak).
- Rate-limit/spam ceilings are never exceeded (anti-spam interaction tests pass).
- Coverage ≥ 85% on new code.

## 4. User Stories

- *As a community member*, I want the bot to chime in when it actually has a relevant memory or
  reaction, not just because N messages passed.
- *As a community member*, I want it to stay quiet when it has nothing to add, so it never
  feels spammy.
- *As an operator*, I want to tune "how eager" the bot is rather than a raw message count.
- *As a returning user*, I want the bot to be more likely to greet me when it holds a strong,
  apt memory about me.

## 5. Technical Architecture (sketch)

- **Signal sources**: topical similarity (S8 S1), novelty (S8 S6), ambient mood cosine (S8 S7),
  salience/boost (S9). Combine into a bounded `engagement_score`.
- **Decision point**: `trigger_engine` auto-participation branch — replace/augment the count
  threshold with `engagement_score >= eagerness`, still bounded by `rate_limiter` and
  `spam_detector`.
- **Latency guard**: a cheap pre-check (novelty from the nearest already-fetched fact; mood
  cosine) gates whether to run full retrieval on the silent path.
- **Per-user bias** (optional): weight the score by the strength of stored memory about the
  speaker/greeting target.

## 6. Dependencies

- Sprints 8–9 merged (signals + telemetry). `trigger_engine`, `rate_limiter`, `spam_detector`.
  No new external services.

## 7. Security and Privacy

- This changes **timing, not content** — no new disclosure surface. All Sprint 8 gates
  (shadow-mute, cross-user) still apply when a message is actually generated.
- Per-user engagement bias must not leak *which* facts are held (timing only).

## 8. Rollout Plan

- Default to current behavior (count threshold); introduce the engagement score behind a flag
  and an `eagerness` knob. Ship the cheap pre-check first, then the score, then per-user bias.
- Monitor fire-rate vs. signal strength and rate-limit headroom via Sprint 9 metrics.

## 9. Future Enhancements

- Learned engagement policy from feedback signals. Time-of-day / channel-activity awareness.

## 10. Open Questions

- Does computing a "should I speak?" signal on every message cost too much on the silent path?
  (Likely need the cheap pre-check.)
- How to evaluate engagement quality without a human-rated feedback loop? (Ties to Sprint 12
  eval harness.)
- Should engagement bias be per-user, per-channel, or both?

---

## Rough sortie outline (to be expanded)

| # | Sortie (working title) | Gist | Rough REQ |
|---|------------------------|------|-----------|
| 1 | Engagement score | Combine topical/novelty/mood/salience into a bounded score | 220–229 |
| 2 | Silent-path pre-check | Cheap gate (nearest-fact novelty, mood cosine) before full retrieval | 230–239 |
| 3 | Eagerness knob | Operator threshold on the score augmenting the message count | 240–244 |
| 4 | Per-user engagement bias | Weight score by strength of stored memory about the target | 245–249 |

**Dependencies within sprint**: 1 before 3 (knob acts on the score); 2 independent (latency
guard); 4 after 1. Guardrails (rate-limit ceilings, cooldowns, anti-spam tests) span all.
