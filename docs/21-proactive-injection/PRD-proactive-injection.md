# PRD (Ideation): Proactive Memory Injection

**Sprint**: 21 — `21-proactive-injection`
**Status**: Ideation (N+5) — problem statement + user stories + feasibility only
**Builds on**: Sprints 8–20 (memory surfaces, quality, governance, engagement, eval,
  confidence, model routing, calibration, compaction, temporal awareness)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)
**Theme**: G (Strategic Backlog)

> **Detail level**: N+5 ideation. A full PRD (10 sections) and sortie specs are written
> when promoted to N+4 or N+3. No implementation until promotion.
> **Gate**: do not promote until Sprint 18 (confidence calibration) and Sprint 19 (compaction)
> are complete. Proactive injection with miscalibrated or noisy facts is worse than no
> injection — the store must be clean and confidence must be well-calibrated first.

---

## 1. Problem Statement

Every LLM response today is trigger-driven: the bot speaks when it is mentioned, when a
trigger word fires, or when auto-participation threshold is reached. Memory is consulted only
on those triggered turns.

This leaves the bot in a reactive posture. It can know that a user loves samurai films and
be listening when someone in the channel says "we should watch more samurai movies" — but if
that message doesn't mention the bot by name or match a trigger, the bot stays silent and
a perfect connection is missed.

**Proactive injection** changes the signal path: during every triggered turn (including
auto-participation), scan the speaker's high-confidence facts for *topical relevance to the
current message*. If a fact clears a relevance threshold, surface it into the context even
without a direct trigger. The bot can then naturally weave memory into its response ("since
you love samurai films, you'd probably enjoy this") rather than only recalling when called on.

This is distinct from the existing topical-scope retrieval (which surfaces *other users'*
facts via associative recall). Proactive injection is **speaker-focused**: it enriches the
bot's response with the *current speaker's* own facts when they're topically germane to
what they just said — without requiring a mention.

**Who benefits**: the community (the bot feels like it's genuinely paying attention, not just
waiting for its name), operators (higher engagement per turn, especially on auto-participation
turns where the bot proactively connects the room's conversation to individual members),
and the memory system's ROI (years of learned facts actually surface when they're relevant,
not just when users explicitly invoke the bot).

---

## 2. User Stories

- *As a community member*, I want the bot to connect what I'm saying to things it already
  knows about me, even when I haven't directly addressed it, so conversations feel
  personal and continuous.
- *As a community member*, I want proactive injection to feel natural, not intrusive — the
  bot should interject only when the connection is genuinely strong, not on every message.
- *As an operator*, I want a configurable relevance threshold so I can tune how aggressively
  the bot injects memories (start conservative; tune up with data).
- *As an operator*, I want proactive injection to respect all existing rate limits, cooldowns,
  and spam detection so it can't be used to circumvent them.
- *As a maintainer*, I want proactive injection decisions to be observable (logged, metered)
  so I can tell when and why the bot chose to inject a memory.

---

## 3. Feasibility / Technical Read

**Where it fits in the pipeline**: Proactive injection augments the context pipeline's
`build()` call. After the standard speaker-scope retrieval, a new **proactive scope** checks
whether the top-ranked speaker fact has cosine similarity ≥ `proactive_threshold` to the
current message embedding. If so, it's flagged as a `"proactive_memory"` fragment and
injected into context with a priority that puts it alongside `"user_memory"`.

This is a lightweight extension to `LongTermMemoryProvider` (or a new provider): the
embedding of the current message is already computed during topical-scope retrieval; the
proactive check reuses it.

**Confidence gate (Sprint 18 dependency)**: only facts with `confidence ≥ proactive_min_confidence`
(e.g. 0.7) are eligible for proactive injection. This is the hard gate that requires Sprint 18
to be calibrated first — a mis-calibrated confidence score of 0.7 on a dubious fact would
produce embarrassing "proactive" interjections.

**Store quality gate (Sprint 19 dependency)**: if near-duplicate facts exist, proactive
injection may surface the wrong phrasing of the same fact. Post-compaction, the store
represents each concept with a single canonical fact, so injecting the top match is reliable.

**Trigger interaction**:
- On *mention* and *trigger_word* turns: proactive injection enriches the context when a
  relevant high-confidence fact exists. The fact is surfaced alongside the standard
  `user_memory` fragment — the LLM sees both and can weave them together.
- On *auto_participation* turns: proactive injection can *replace* the auto-participation
  trigger entirely if the relevance score is strong enough — the bot speaks specifically
  *because* a memory is relevant, not just because the message counter tripped.

**Rate limiting**: proactive injection does not bypass rate limits. If the bot is rate-limited
or on cooldown, no response is generated regardless of proactive signal. This is REQ-318 analog.

**Template changes**: `trigger.j2` gains a `proactive_memory` block that prefixes the
injected fact contextually ("Since you mentioned X, and I know you Y…" or just weaves it
naturally via the system prompt).

**Observability**: `record_proactive_injection(triggered: bool, similarity: float)` on
health monitor. `llm_proactive_injections_total` counter; `llm_proactive_similarity_avg`
gauge. Debug log: `proactive: user=X fact="Y..." similarity=0.81 threshold=0.75`.

**Risk**: medium. The wrong threshold produces intrusive or incoherent non-sequiturs. This is
the feature where calibrated confidence (S18) and a clean store (S19) are not optional.
Default off; start with `proactive_threshold = 0.80` (high) and tune down with data.

---

## 4. Rough Scope (candidate sorties)

1. **Proactive scope in LongTermMemoryProvider** — post-speaker-scope check: top-ranked
   fact similarity ≥ threshold + confidence gate → `"proactive_memory"` fragment emitted.
2. **Template integration** — `trigger.j2` `proactive_memory` block; system prompt hint
   that a proactive memory was surfaced.
3. **Config + auto-participation wiring** — `proactive` config block; on auto-participation
   turns, proactive signal can serve as the participation reason (replaces count-based trigger).
4. **Observability** — health monitor `record_proactive_injection`; Prometheus metrics;
   debug log line per turn.

---

## 5. Open Questions

- Should proactive injection create a *new trigger type* (`proactive`) or augment the
  existing turn without changing the trigger type?
- On auto-participation turns: if proactive injection fires, should the auto-participation
  counter *not* reset (since the bot spoke for memory reasons, not social timing reasons)?
- What is the right default `proactive_threshold`? (0.80 proposed; lower than the topical
  scope's `min_similarity` to distinguish the two paths.)
- Does proactive injection interact with Sprint 17's cross-channel sharing? (User X's fact
  from channel A being proactively injected in channel B requires the cross-channel consent
  gate — design must be explicitly gated behind S17.)

**REQ reservation**: REQ-420+ (finalised at promotion).
