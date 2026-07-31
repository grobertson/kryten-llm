# PRD (Ideation): Temporal Fact Awareness

**Sprint**: 20 — `20-temporal-awareness`
**Status**: Ideation (N+4) — problem statement + user stories + feasibility only
**Builds on**: Sprints 8–19 (memory surfaces, quality, governance, eval, confidence,
  model routing, calibration, compaction)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)
**Theme**: H (Strategic Backlog)

> **Detail level**: N+4 ideation. A full PRD (10 sections) and sortie specs are written
> when promoted to N+3 or N+2. No implementation until promotion.

---

## 1. Problem Statement

Facts in the memory store currently carry timestamps (`created_at`, `updated_at`) in
metadata, but those timestamps are invisible to the retrieval and ranking layer. The result:

- A fact first observed two years ago ranks identically to one from last week if their
  importance and confidence are the same.
- The bot cannot hedge with temporal context ("you mentioned this a while back…" vs "you
  just said…"), making its responses feel atemporal even when time matters.
- Sprint 18's temporal confidence drift is a confidence nudge without structural grounding
  — facts that haven't been seen in months can still surface as if they're current.
- Sprint 19's compaction can merge facts without respecting temporal order — the "canonical"
  selection is importance-based; temporal awareness gives a second dimension.

The gap is a first-class **recency dimension** in retrieval ranking and prompt presentation,
driven by actual stored timestamps rather than inferred from importance or confidence alone.

**Who benefits**: operators (more contextually accurate responses — "back when you were into
X" vs presenting stale preferences as current), the community (temporally grounded hedging
feels natural and honest), and Sprint 21 proactive injection (knowing fact age helps the bot
decide whether a memory is topically current enough to surface unprompted).

---

## 2. User Stories

- *As a community member*, I want the bot to acknowledge when something it remembers about
  me is old ("you mentioned back in the day…") vs recent, so its replies feel more honest.
- *As an operator*, I want retrieval to prefer recently corroborated facts over stale ones
  when confidence and importance are equal, so the bot references timely information.
- *As a maintainer*, I want a configurable recency half-life so I can tune how aggressively
  old facts are deprioritised in retrieval without deleting them.
- *As an operator*, I want temporal drift to reduce confidence on facts not seen in N days,
  complementing Sprint 18's importance-gated decay with a time-based axis.

---

## 3. Feasibility / Technical Read

**Timestamp storage**: facts already store `created_at` and `updated_at` in Chroma/pgvector
metadata. Retrieval currently ignores them. The structural work is exposing them to
`_rank_with_boost` as a `recency_score ∈ [0, 1]`.

**Recency score formula**:
```
age_days = (now - last_corroborated_at).total_seconds() / 86400
recency_score = exp(-age_days / half_life_days)
```
Where `half_life_days` is configurable (e.g. 90 days default → a fact unseen for 90 days
scores ~0.37, one from today scores 1.0). This is additive with the existing
`importance_weight` and `recency_weight` axis in `RetrievalBoostConfig`.

**Wait — `recency_weight` already exists**: `RetrievalBoostConfig.recency_weight = 0.1`
was added in Sprint 9. Its current implementation needs to be verified — if it's already
computing recency from timestamps, Sprint 20 may be refining/exposing it rather than adding
it from scratch. **Audit this before promotion.**

**Temporal hedging in templates**: the `user_memory` `ContextFragment` can carry a
`recency_days` integer alongside `confidence`. The Jinja2 `trigger.j2` template can then
emit temporal hedging:
- `recency_days < 7` → present as current ("you mentioned recently…" or no hedge)
- `recency_days ∈ [7, 90]` → light hedge ("a while back…")
- `recency_days > 90` → strong hedge ("back in the day, you used to…")

**Temporal drift (complement to Sprint 18)**: Sprint 18 plans importance-gated decay when a
contradiction is detected. Sprint 20 would add *passive drift* — a background task that
nudges confidence downward for facts whose `last_corroborated_at` is older than
`drift_after_days` (e.g. 120 days), by a small `drift_rate` (e.g. 0.01 per sweep).
This is softer than Sprint 18's contradiction decay; it models "things change over time".

**Schema migration note**: if `last_corroborated_at` is not already reliably stored,
Sprint 20 requires a one-time backfill setting it to `created_at` for existing facts.
This is a schema change — version it, document it, provide a migration helper.

**Risk**: low–medium. The recency score is additive and weight-gated (defaults to 0 weight).
The schema migration is the main operational risk; design carefully for both Chroma and
pgvector backends.

---

## 4. Rough Scope (candidate sorties)

1. **Recency score + retrieval wiring** — expose `last_corroborated_at` from metadata;
   compute `recency_score`; add to `_rank_with_boost` behind a new config weight.
2. **Temporal hedging in templates** — carry `recency_days` on `ContextFragment`; extend
   `trigger.j2` with configurable age-band hedging phrases.
3. **Temporal drift sweep** — background task: nudge confidence downward for dormant facts;
   configurable `drift_after_days` and `drift_rate`; health monitor counter.
4. **Schema migration** — ensure `last_corroborated_at` is consistently written; backfill
   helper for existing stores; update Sprint 12 eval fixtures.

---

## 5. Open Questions

- Does `recency_weight` in the current `RetrievalBoostConfig` already compute from
  timestamps, or is it a stub? (Must audit before promotion.)
- What is the right default `half_life_days`? (90 days is a reasonable starting proposal.)
- Should temporal drift be in the retention sweeper loop or a separate scheduled task?
- How do the age-band hedging phrases interact with Sprint 13's confidence hedging ("I
  think…")? Are they additive, or should one suppress the other?

**REQ reservation**: REQ-400+ (finalised at promotion).
