# SPEC-Sortie-1: Forget command

**Sprint**: 10 — Memory Privacy & Governance
**PRD**: [PRD-memory-privacy.md](PRD-memory-privacy.md)
**Status**: Planned
**Estimate**: 3–4h
**Depends on**: Sprint 8 (provider + store); existing `store.delete` / CLI forget
**Requirements**: REQ-170 – REQ-179

---

## 1. Overview

Expose the existing admin-CLI forget (`kryten-llm memory forget <user>`) as an **authorized,
audited runtime command** on `kryten.llm.command` so operators/moderators can delete a user's
stored facts without shell access. Reuses `store.delete(where={"user": ...})`.

## 2. Scope and Non-Goals

**In scope**: `forget.user` command on the existing command subject; authorization; audit log;
success/count reply.

**Non-goals**: in-chat self-service forget (Sortie 4); retention/expiry (Sortie 2); deleting
by anything other than username.

## 3. Requirements

- **REQ-170** — `forget.user` command handled on `kryten.llm.command`, dispatched by the
  existing `CommandHandler._handle_command` map.
- **REQ-171** — Request `{"command":"forget.user","username":...}`; reply
  `{"service":"llm","command":"forget.user","success":bool,"data":{"deleted":N}}`.
- **REQ-172** — Deletes all facts for the user via `store.delete(where={"user": username})`;
  returns the deleted count.
- **REQ-173** — Authorization required: caller must present a moderator-rank credential (or
  configured allowlist); unauthorized requests reply `success:false` and are logged.
- **REQ-174** — Every deletion is audit-logged (who, whom, count, timestamp).
- **REQ-175** — Idempotent: forgetting an unknown user replies `success:true, deleted:0`.
- **REQ-176** — Off/− safe when the memory provider is disabled (reply `success:false` with a
  clear error).

## 4. Design

`CommandHandler` gains a `forget.user` entry pointing at a handler that resolves the
`LongTermMemoryProvider` (via the pipeline) and calls its existing `forget_user` path
(the same code the CLI uses). Authorization reuses the request `meta` rank the ecosystem
already carries; a config `forget.min_rank` (default moderator) gates it.

```python
async def _handle_forget_user(self, request: dict) -> dict:
    username = request.get("username")
    if not self._authorized(request):     # rank / allowlist
        return {"service": "llm", "command": "forget.user", "success": False,
                "error": "unauthorized"}
    deleted = await self._provider.forget_user(username)
    self.logger.info("audit: forget.user by=%s target=%s deleted=%s", ...)
    return {"service": "llm", "command": "forget.user", "success": True,
            "data": {"deleted": deleted}}
```

## 5. Implementation Plan

**Modify**
- `components/command_handler.py` — add `forget.user` to the dispatch map + handler + auth.
- `components/context/providers/long_term_memory.py` — ensure a public `forget_user(username)`
  returning the deleted count (extract from the CLI path if needed).
- `models/config.py` — `forget.min_rank` / allowlist.
- `config.example.json` — `commands.forget` block.

## 6. Testing Strategy

- Authorized `forget.user` deletes and returns count.
- Unauthorized request → `success:false`, audited, nothing deleted.
- Unknown user → `success:true, deleted:0`.
- Provider disabled → clear error reply.
- Audit log line emitted on deletion.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] A moderator can forget a user over NATS; a non-moderator cannot.
- [ ] All deletions are audited; counts are accurate.
- [ ] Idempotent and safe when disabled.

## 8. Rollout

- Ship first (low risk; reuses delete). Document the command contract in the API reference.
- Monitor an audit counter for forget operations.

## 9. Documentation

- `docs/user-memory-explained.md`: how to forget a user at runtime.
- Command contract in the service's NATS API doc.
- `CHANGELOG.md` entry (new command = public API addition).
