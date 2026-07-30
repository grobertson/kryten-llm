# SPEC-Sortie-1: Topic-scoped recall

**Sprint**: 8 — Associative Memory
**PRD**: [PRD-associative-memory.md](PRD-associative-memory.md)
**Status**: Implemented (checkpoint) — 8 topical tests green; default-off
**Estimate**: 3–5h
**Depends on**: Sortie 0 (moderation gate, `$ne`, scope plumbing)
**Requirements**: REQ-050 – REQ-059
**Flagship** — highest impact for least risk.

---

## 1. Overview

When the bot speaks — especially unprompted via **auto-participation** — retrieve facts
semantically similar to the current discussion *regardless of who said them*, so it can be
attentive and "present" instead of only knowing the speaker. Emit an attributed
`topical_memory` fragment:

> Relevant things people have said before:
> • [alice] loves synthwave and vaporwave
> • [bob] runs a Plex server for the group

The `[username]` prefix is the key "feels real" lever — it lets the model name-drop
naturally.

## 2. Scope and Non-Goals

**In scope**: cross-user topical retrieval on configured trigger types; attribution;
de-dup against the speaker fragment; mandatory shadow-mute exclusion.

**Non-goals**: importance/recency re-ranking of topical results (reuse similarity order);
firing on every trigger type by default (auto-participation only).

## 3. Requirements

- **REQ-050** — Topical retrieval drops the user filter and queries with the message vector.
- **REQ-051** — Fires only for trigger types in `fire_on` (default `["auto_participation"]`).
- **REQ-052** — Each line is attributed with the source username.
- **REQ-053** — Silenced users excluded (Sortie 0 gate, fail-closed).
- **REQ-054** — `exclude_speaker` removes the speaker's own facts from this fragment.
- **REQ-055** — Results duplicated in `user_memory` are removed from `topical_memory`.
- **REQ-056** — Emitted as `topical_memory` at configured priority; respects budget trimming.
- **REQ-057** — Off unless `cross_user.enabled && topical.enabled`.

## 4. Design

Runs as a second scope in `_provide_impl` when
`cross_user.enabled && topical.enabled && trigger_type ∈ fire_on`. `trigger_type` is read
from `ContextRequest.trigger`; values include `auto_participation`
([health_monitor.py](../../kryten_llm/components/health_monitor.py#L88)).

```python
scope = RetrievalScope(
    where=({"user": {"$ne": req.username}} if topical.exclude_speaker else None),
    query_source="message",
    exclude_silenced=True,          # MANDATORY here
    fragment_name="topical_memory",
    priority=topical.priority,
)
```

- **Over-fetch then filter.** Gate + `exclude_speaker` drop rows, so fetch `top_k*3`
  (bounded, mirroring existing LLM-mode over-fetch) and trim to `top_k` after filtering.
- **De-dup vs. `user_memory`** by fact id.
- **Format**: `• [{user}] {document}` lines under a "Relevant things people have said
  before:" header.
- **Budget**: `priority=38` (just below speaker `user_memory` at 40).

## 5. Implementation Plan

**Modify**
- `long_term_memory.py` — add topical scope branch, trigger-type gating, over-fetch/trim,
  de-dup, formatter.
- `models/config.py` — `TopicalConfig`.
- `config.example.json` — `topical` block.

**Config**
```jsonc
"topical": {
  "enabled": false,
  "fire_on": ["auto_participation"],
  "top_k": 4,
  "min_similarity": 0.30,
  "exclude_speaker": true,
  "priority": 38
}
```

## 6. Testing Strategy

- Fires for `auto_participation`, not `mention` (default `fire_on`).
- "synthwave" message surfaces alice's fact attributed `[alice]`.
- Smuted bob's fact excluded even as top match.
- Speaker's own fact absent when `exclude_speaker=true`.
- Duplicate of a `user_memory` fact removed from `topical_memory`.
- Off by default → no fragment.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Auto-participation turn on a themed discussion yields a `topical_memory` block naming
      ≥1 other user's relevant fact.
- [ ] No silenced user ever appears.
- [ ] Disabled by default; output unchanged.

## 8. Rollout

- Enable after Sortie 0 in prod. Requires `cross_user.enabled=true`.
- Monitor topical-fragment emission counter and provider timeout rate.

## 9. Documentation

- `config.example.json` comments.
- `docs/user-memory-explained.md`: describe topical recall + attribution + privacy gating.
- `CHANGELOG.md` entry.
