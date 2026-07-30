# SPEC-Sortie-2: Userlist-based presence

**Sprint**: 9 — Memory Quality & Observability
**PRD**: [PRD-memory-quality.md](PRD-memory-quality.md)
**Status**: Planned
**Estimate**: 3–5h
**Depends on**: Sprint 8 Sortie 2 (room awareness)
**Requirements**: REQ-130 – REQ-139

---

## 1. Overview

Sprint 8 room-awareness infers "who's present" from recent chat activity. Upgrade it to read
the authoritative **userlist** that Kryten-Robot maintains, so the bot knows who is actually in
the channel (including lurkers who haven't spoken) and never references someone who has left.

## 2. Scope and Non-Goals

**In scope**: read-only userlist KV bind; presence source selection (`userlist` |
`recent_activity`); graceful fallback to the Sprint 8 heuristic; TTL cache.

**Non-goals**: storing presence as facts; ranking by presence (that's a future enhancement);
writing userlist state (robot owns it).

## 3. Requirements

- **REQ-130** — Read the userlist from `cytube_{safe_domain}_{channel}_userlist` (key `users`)
  read-only via `kv_get`.
- **REQ-131** — `presence_source: "userlist"` uses the KV list; `"recent_activity"` keeps the
  Sprint 8 heuristic.
- **REQ-132** — Fail-open: on KV error/empty, fall back to the recent-activity heuristic.
- **REQ-133** — Presence set excludes speaker and bot; still capped by `max_users`.
- **REQ-134** — Presence list is TTL-cached to keep the read path fast.
- **REQ-135** — Presence is never stored or treated as a fact.

## 4. Design

Add a presence resolver used by the room scope (Sprint 8 Sortie 2):

```python
async def _present_users(self, domain, channel) -> list[str]:
    if presence_source == "userlist":
        bucket = f"cytube_{domain.lower().replace('.', '_')}_{channel.lower()}_userlist"
        users = await self._client.kv_get(bucket, "users", default=[], parse_json=True)
        names = [u["name"] for u in users if "name" in u]
        if names:
            return names
    return self._recent_distinct_users(...)     # Sprint 8 fallback
```

Feed the resulting set into the existing room `$in` scope. Cache with a short TTL (reuse the
`ModerationGate` caching pattern).

## 5. Implementation Plan

**Modify**
- `long_term_memory.py` — presence resolver + TTL cache; wire into the room scope.
- `models/config.py` — `presence_source`, `presence_cache_ttl_s` in room config.
- `config.example.json` — room block additions.

**Depends** on the service passing `domain`/`channel` and a `KrytenClient` handle to the
provider (already needed by Sprint 8 `ModerationGate`).

## 6. Testing Strategy

- Userlist with alice/bob/carol → presence set matches (minus speaker/bot).
- KV error → falls back to recent-activity heuristic (no exception).
- Empty userlist → fallback.
- `max_users` still enforced.
- TTL cache prevents repeated KV reads within the window.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Room-awareness references only users currently in the userlist when `presence_source=userlist`.
- [ ] KV outage degrades gracefully to Sprint 8 behavior.
- [ ] Presence never persisted.

## 8. Rollout

- Default `presence_source` stays `recent_activity` (Sprint 8 behavior) until validated, then
  flip to `userlist` per channel.
- Monitor fallback-rate metric (Sortie 5).

## 9. Documentation

- `config.example.json` comments.
- `docs/user-memory-explained.md`: presence source options.
- Cross-link Kryten-Robot AGENTS.md (userlist bucket contract).
- `CHANGELOG.md` entry.
