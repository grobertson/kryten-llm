# SPEC-Sortie-2: Room awareness

**Sprint**: 8 — Associative Memory
**PRD**: [PRD-associative-memory.md](PRD-associative-memory.md)
**Status**: Planned
**Estimate**: 3–5h
**Depends on**: Sortie 0 (gate, `$in`); complements Sortie 1
**Requirements**: REQ-060 – REQ-069

---

## 1. Overview

Give the bot awareness of *who is in the room right now*, not just who is talking. Retrieve a
small number of facts for the **other currently-active participants** so the bot can address
the group naturally ("evening all — bob, how's the Plex rebuild going?"). Where Sortie 1 is
topic-driven, Sortie 2 is presence-driven.

## 2. Scope and Non-Goals

**In scope**: derive active-participant set from the recent-message window; scoped `$in`
retrieval; per-user cap; shadow-mute exclusion; de-dup vs. Sortie 1/speaker.

**Non-goals**: presence via the robot userlist KV bucket (deferred); addressing absent users.

## 3. Requirements

- **REQ-060** — Active-participant set derived from the recent-message window, excluding
  speaker and bot.
- **REQ-061** — Retrieval scoped to those users via `$in`.
- **REQ-062** — At most `facts_per_user` facts per user, at most `max_users` users.
- **REQ-063** — Silenced users excluded (fail-closed).
- **REQ-064** — De-dup against `topical_memory` and `user_memory`.
- **REQ-065** — Emitted as `room_memory`; off unless `cross_user.enabled && room_awareness.enabled`.

## 4. Design

The trigger engine already tracks recent activity for the auto-participation threshold
([trigger_engine.py](../../kryten_llm/components/trigger_engine.py)). Reuse the recent-message
window to derive distinct usernames in the last *N* messages / *M* seconds, minus speaker and
bot.

```python
active = recent_distinct_users(window_messages, window_seconds) - {req.username, bot_name}
active = top_by_recency(active, max_users)

scope = RetrievalScope(
    where={"user": {"$in": sorted(active)}},
    query_source="message",          # bias toward topically-relevant facts
    exclude_silenced=True,           # MANDATORY, fail-closed
    fragment_name="room_memory",
    priority=room.priority,
)
```

- After query, keep ≤ `facts_per_user` per username (highest similarity / boost).
- Attribution `• [user] fact`.
- If Sortie 1 also runs, de-dup by fact id; topical wins (higher priority), room fills gaps.

## 5. Implementation Plan

**Modify**
- `long_term_memory.py` — active-user derivation helper, room scope branch, per-user cap,
  de-dup.
- `models/config.py` — `RoomAwarenessConfig`.
- `config.example.json` — `room_awareness` block.

**Config**
```jsonc
"room_awareness": {
  "enabled": false,
  "window_messages": 20,
  "window_seconds": 300,
  "max_users": 4,
  "facts_per_user": 1,
  "priority": 30
}
```

## 6. Testing Strategy

- Speaker=dave, active alice/bob/carol → `room_memory` has ≤1 fact each for alice/bob/carol,
  none for dave.
- Smuted carol excluded even if active.
- `max_users` respected when 6 users active.
- De-dup vs. topical fragment.
- Off by default.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] In a busy room, an auto-participation reply can reference a present user by name via a
      stored fact.
- [ ] Never references a silenced user.
- [ ] Disabled by default.

## 8. Rollout

- Enable after Sortie 0 (and typically alongside Sortie 1). Requires `cross_user.enabled`.
- Monitor room-fragment emissions and timeout rate.

## 9. Documentation

- `config.example.json` comments.
- `docs/user-memory-explained.md`: room-awareness behavior + privacy.
- `CHANGELOG.md` entry.
