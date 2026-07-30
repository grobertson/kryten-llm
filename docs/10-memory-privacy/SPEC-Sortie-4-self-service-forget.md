# SPEC-Sortie-4: Self-service forget

**Sprint**: 10 — Memory Privacy & Governance
**PRD**: [PRD-memory-privacy.md](PRD-memory-privacy.md)
**Status**: Planned
**Estimate**: 3–5h
**Depends on**: Sortie 1 (authorized forget path)
**Requirements**: REQ-200 – REQ-209

---

## 1. Overview

Let a user delete **their own** stored facts by asking the bot in chat ("forget me"), with
identity verification so nobody can wipe someone else's data. Builds on Sortie 1's authorized
command path; ships behind an explicit opt-in flag (moderator-only until enabled).

## 2. Scope and Non-Goals

**In scope**: an in-chat trigger phrase; self-only scope (deletes the requester's facts);
identity verification; confirmation reply; audit.

**Non-goals**: forgetting other users (that's the moderator command); partial/selective
forget; cross-channel forget.

## 3. Requirements

- **REQ-200** — A configurable trigger phrase (e.g. "forget me") detected on the chat path
  invokes self-forget for the **requesting** username only.
- **REQ-201** — Identity is verified before deletion: the request must come from the same
  username via the trusted event source (CyTube username from Kryten-Robot), not free text.
- **REQ-202** — Deletes only `where={"user": requester}`; never another user.
- **REQ-203** — The bot replies with a confirmation and the deleted count.
- **REQ-204** — Every self-forget is audit-logged.
- **REQ-205** — Feature-flagged `self_service.enabled` (default false); when off, only the
  moderator command (Sortie 1) can forget.
- **REQ-206** — Rate-limited / cooldown to prevent abuse or accidental spam.

## 4. Design

On the chat path, after the listener filter, match the trigger phrase against the message;
if matched and enabled, call the same authorized forget path as Sortie 1 with
`username = event.username` (trusted, from the Socket.IO event via Kryten-Robot) — so the
scope is inherently self-only and identity is implicit in the event source.

```python
if self._self_forget_enabled and _matches_forget_phrase(msg):
    deleted = await self._provider.forget_user(event.username)
    await client.send_chat(f"Okay {event.username}, I've forgotten what I knew ({deleted}).")
```

## 5. Implementation Plan

**Modify**
- `service.py` (or a small handler) — detect the phrase on the chat path; call forget;
  confirm; cooldown.
- `models/config.py` — `self_service` block (`enabled`, `phrase`, `cooldown_seconds`).
- `config.example.json` — `self_service` block (default off).

## 6. Testing Strategy

- Trigger phrase from alice deletes only alice's facts and confirms.
- The scope is always the event username; a spoofed body naming another user cannot widen it.
- Disabled flag → phrase ignored.
- Cooldown suppresses rapid repeats.
- Audit line emitted.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] A user can self-forget in chat; it only affects their own facts.
- [ ] Off by default; cannot be used to delete others' data.
- [ ] Audited and rate-limited.

## 8. Rollout

- Ship default-off; enable per community with a clear announcement.
- Monitor self-forget audit counter.

## 9. Documentation

- `docs/user-memory-explained.md`: how to make the bot forget you.
- `CHANGELOG.md` entry.
