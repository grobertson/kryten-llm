# SPEC-Sortie-5: Transparency / inspection

**Sprint**: 10 — Memory Privacy & Governance
**PRD**: [PRD-memory-privacy.md](PRD-memory-privacy.md)
**Status**: Planned
**Estimate**: 2–4h
**Depends on**: Sortie 1 (per-user read/authorization); store `get_all`
**Requirements**: REQ-210 – REQ-219

---

## 1. Overview

Give users and moderators a way to see **what the bot has stored about a user** — a privacy
transparency surface. Exposed as a command (and optionally an opt-in self-service phrase),
returning a compact, privacy-respecting summary of a user's facts.

## 2. Scope and Non-Goals

**In scope**: `inspect.user` command returning a user's stored facts (summaries + categories +
ages); self-scope for self-service; authorization for inspecting others.

**Non-goals**: exporting raw vectors/embeddings; inspecting *other* users without moderator
rank; editing facts.

## 3. Requirements

- **REQ-210** — `inspect.user` command on `kryten.llm.command` returns a user's facts via
  `store.get_all(where={"user": ...})`, projected to `{summary, category, created_at,
  importance}` (no embeddings).
- **REQ-211** — Inspecting **another** user requires moderator authorization (reuse Sortie 1's
  auth); self-inspection is always allowed for the requester.
- **REQ-212** — Output is capped/paginated to a sane size and ordered by importance/recency.
- **REQ-213** — Optional self-service phrase ("what do you know about me?") returns the
  requester's own summary in chat, behind the `self_service` flag (Sortie 4).
- **REQ-214** — The transparency output never leaks *other* users' facts and respects the
  shadow-mute/privacy posture.
- **REQ-215** — Read-only: never mutates facts.

## 4. Design

A handler resolves the provider and returns a projected view:

```python
records = await store.get_all(where={"user": username})
items = sorted(
    ({"summary": r["document"], **_project(r["metadata"])} for r in records),
    key=lambda x: (x["importance"], x["created_at"]), reverse=True,
)[:limit]
```

Self-service chat variant formats the top items into a short, friendly message.

## 5. Implementation Plan

**Modify**
- `components/command_handler.py` — `inspect.user` handler + auth (self vs. moderator).
- `service.py` — optional self-service phrase on the chat path (shares Sortie 4's flag).
- `models/config.py` — `inspect.limit`.
- `config.example.json` — `commands.inspect` block.

## 6. Testing Strategy

- `inspect.user` returns projected facts (no embeddings) ordered correctly.
- Self-inspection allowed; inspecting another user requires moderator rank.
- Output capped at `limit`.
- Self-service phrase returns the requester's summary only.
- Read-only (no store mutation).
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] A user can see what's stored about them; moderators can inspect others.
- [ ] No embeddings leaked; other users' facts never exposed.
- [ ] Read-only and bounded.

## 8. Rollout

- Command ships with Sortie 1; self-service phrase gated by Sortie 4's flag.

## 9. Documentation

- `docs/user-memory-explained.md`: how to see/inspect stored memory.
- Command contract in the NATS API doc.
- `CHANGELOG.md` entry.
