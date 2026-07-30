# SPEC-Sortie-5: Callback / long-tail resurfacing

**Sprint**: 8 — Associative Memory
**PRD**: [PRD-associative-memory.md](PRD-associative-memory.md)
**Status**: Planned
**Estimate**: 3–5h
**Depends on**: none for `scope="speaker"`; `scope="any"` needs Sortie 0
**Requirements**: REQ-090 – REQ-099

---

## 1. Overview

The biggest "this bot remembers me" moment is an unprompted **callback** to something old — a
fact that is *important* but *not recent*. Phase 7f's `_rank_with_boost` already suppresses
stale facts; this sortie occasionally **inverts** that to deliberately resurface a
high-importance, low-recency fact as a flavor line.

## 2. Scope and Non-Goals

**In scope**: probabilistic speaker callbacks with importance/age floors, topic-dissimilarity
guard, cooldown; optional cross-user callbacks behind Sortie 0.

**Non-goals**: guaranteed callbacks; multiple callbacks per turn.

## 3. Requirements

- **REQ-090** — Callback fires probabilistically (`probability`) subject to `cooldown_turns`.
- **REQ-091** — Candidates require `importance >= min_importance` and age >= `min_age_days`.
- **REQ-092** — Callbacks avoid facts already surfaced this turn.
- **REQ-093** — Callbacks avoid facts too similar to the current topic
  (`max_similarity_to_topic`).
- **REQ-094** — Selection weighted by importance; one callback per turn max.
- **REQ-095** — Per-channel cooldown enforced after a callback.
- **REQ-096** — `scope="any"` requires `cross_user.enabled` and passes the Sortie 0 gate
  (fail-closed); default `scope="speaker"`.
- **REQ-097** — Disabled by default; no effect on existing fragments when off.

## 4. Design

After normal speaker retrieval (off the critical similarity path):

1. Roll `probability`; bail if it fails or per-channel `cooldown_turns` active.
2. Query speaker facts for `importance >= min_importance` and `created_at` older than
   `min_age_days` (uses existing `score`/`created_at` metadata).
3. Exclude anything surfaced this turn and anything with topic similarity above
   `max_similarity_to_topic` (a callback should feel bot-initiated, not an echo).
4. Pick one (importance-weighted), append a distinct line, set cooldown.

```
You also remember: alice mentioned she used to run the old channel's movie nights.
```

`scope="any"` (default `"speaker"`) may resurface another user's old fact → requires Sortie 0
(`cross_user.enabled` + gate, fail-closed).

## 5. Implementation Plan

**Modify**
- `long_term_memory.py` — callback selector, cooldown state (per channel), append to speaker
  fragment or emit `callback_memory`.
- `models/config.py` — `CallbackConfig`.
- `config.example.json` — `callback` block.

**Config**
```jsonc
"callback": {
  "enabled": false,
  "probability": 0.15,
  "min_importance": 3,
  "min_age_days": 14,
  "max_similarity_to_topic": 0.6,
  "cooldown_turns": 20,
  "scope": "speaker",             // "speaker" | "any"
  "label": "You also remember"
}
```

## 6. Testing Strategy

- `probability=1`, `cooldown=0` → old important fact appended; recent one not.
- On-topic fact (sim > threshold) skipped.
- Cooldown suppresses a second callback within `cooldown_turns`.
- `scope="any"` excludes a smuted user's old fact.
- Off by default.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Over a long session the bot occasionally references an old salient fact, bounded by
      `probability`/`cooldown`.
- [ ] Never resurfaces a silenced user's fact.
- [ ] Disabled by default.

## 8. Rollout

- Ship with `scope="speaker"` first (no Sortie 0 needed). Enable `scope="any"` only after
  Sortie 0 + `cross_user.enabled`.
- Conservative defaults to avoid creepiness. Monitor callback-emission counter.

## 9. Documentation

- `config.example.json` comments.
- `docs/user-memory-explained.md`: callbacks + cross-user caveat.
- `CHANGELOG.md` entry.
