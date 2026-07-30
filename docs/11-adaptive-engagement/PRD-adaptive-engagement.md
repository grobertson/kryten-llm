# PRD: Adaptive Engagement

**Sprint**: 11 — `11-adaptive-engagement`
**Status**: Planned (next / N+1) — fully specified; ready to start
**Builds on**: Sprints 8–10 (associative memory, quality, governance)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)

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

## 5. Technical Architecture

The engagement score intercepts the auto-participation decision in `TriggerEngine.check_triggers`
([trigger_engine.py](../../kryten_llm/components/trigger_engine.py)), specifically the
`messages_since_last_trigger >= non_trigger_threshold` branch. The threshold becomes
*score-gated*: even when the count fires, the bot only speaks if `engagement_score >= eagerness`.

Signal sources (all already computed or cheaply derivable):
- **Novelty** — top-1 speaker-fact distance already returned by `_run_speaker_scope`.
- **Topical similarity** — the `topical_memory` fragment, if present.
- **Ambient mood cosine** — `_mood` vector vs. current message vector.
- **Boost/salience** — highest importance in the topical candidate set.

All signals are combined into a normalized `[0, 1]` `engagement_score`. A cheap
**pre-check** (novelty + mood only, no store query) fast-paths the silent case; full
retrieval runs only when the pre-check passes and the count threshold is met.

```
chat_message
  → count threshold met?
      → pre-check (novelty + mood, no store hit)  ← cheap, silent path
          → score ≥ eagerness?
              → full context retrieval
              → generate + send
```

Config lives under `auto_participation` in the service config, keeping engagement
co-located with the threshold it augments.

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

## Sortie index

| # | Spec | Summary | REQ |
|---|------|---------|-----|
| 1 | [SPEC-Sortie-1-engagement-score.md](SPEC-Sortie-1-engagement-score.md) | Compute + normalize memory-signal engagement score | 220–229 |
| 2 | [SPEC-Sortie-2-silent-path-precheck.md](SPEC-Sortie-2-silent-path-precheck.md) | Cheap novelty+mood pre-check on the silent path | 230–239 |
| 3 | [SPEC-Sortie-3-eagerness-knob.md](SPEC-Sortie-3-eagerness-knob.md) | Operator `eagerness` threshold + score-gated auto-participation | 240–244 |
| 4 | [SPEC-Sortie-4-per-user-bias.md](SPEC-Sortie-4-per-user-bias.md) | Per-user engagement weight from stored memory strength | 245–249 |

**Order**: 2 → 1 → 3 → 4. Pre-check (2) is independent and ships first (latency-safe);
score (1) enables the knob (3); per-user bias (4) extends the score. Guardrails span all.
