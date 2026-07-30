# PRD (Draft): Memory Privacy & Governance

**Sprint**: 10 — `10-memory-privacy`
**Status**: Drafted (Future N+2 — PRD + rough sortie outline; specs to be expanded before start)
**Builds on**: Sprints 8–9 (associative memory + quality)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)

> **Detail level**: This is an N+2 draft. Sortie outlines below are intentionally rough; each
> becomes a full `SPEC-Sortie-{M}-{name}.md` (9-section template) when this sprint is promoted
> to "next".

---

## 1. Executive Summary

Sprints 8–9 make the bot recall and disclose more, including *across users*. This sprint puts
**governance** around that memory: self-service and runtime "forget", data-retention/TTL and
fact expiry, hardened PII/secret scrubbing, and user-facing transparency ("what do you know
about me?"). It turns the privacy posture from "gated by flags" into "operable policy".

## 2. Problem Statement

- **What.** A `forget` path exists only as an admin CLI (`kryten-llm memory forget <user>`).
  There is no runtime/self-service forget, no automatic expiry, and PII scrubbing lives only at
  write-time in `safety.py`. As the corpus grows and cross-user disclosure ships, the lack of
  retention and transparency controls becomes a real privacy and compliance risk.
- **Who.** Community members (want control over their data), operators (need retention policy
  and auditability), and the project (reduce liability from the ecosystem's memory).
- **Why now.** Cross-user disclosure (Sprint 8) raises the stakes; governance should land
  before the corpus and disclosure surface grow further.

## 3. Goals and Success Metrics

- Runtime forget reachable without CLI (moderator command and/or user self-service).
- Configurable retention: facts expire by age and/or low importance.
- PII/secret scrubbing strengthened and testable against a fixture corpus.
- A transparency path so a user can learn (and request deletion of) what's stored.
- Success: forget removes all traces (vector + metadata); expiry runs without corrupting the
  store; scrubbing precision/recall improve on fixtures; coverage ≥ 85%.

## 4. User Stories

- *As a user*, I want to say "forget me" in chat and have my facts deleted, so I control my data.
- *As a moderator*, I want a `kryten.llm.command` to forget a user, so I don't need shell access.
- *As an operator*, I want facts to expire after a retention window, so memory doesn't grow
  unbounded or retain stale/sensitive data.
- *As a user*, I want to ask "what do you know about me?" and get a summary, so memory is
  transparent.

## 5. Technical Architecture (sketch)

- Reuse `store.delete(where={"user": ...})` (already backing the CLI forget) behind a
  `kryten.llm.command` command (`forget_user`) and an opt-in chat self-service trigger.
- Add a retention sweeper (periodic task) using existing `created_at`/`score` metadata and
  `delete_ids` for expiry.
- Extend `safety.py` scrubbing with a stronger PII/secret ruleset + fixtures.
- Transparency: a read that summarizes a user's stored facts (reuses `get_all(where=...)`).

## 6. Dependencies

- Sprints 8–9 merged. kryten-py command handling on `kryten.llm.command`. Existing
  `VectorStore` delete/get_all APIs. Moderator rank/permission model for who may issue forget.

## 7. Security and Privacy

- Forget must be **authorized** (moderator rank or verified self) — guard against abuse
  (forcing deletion of others' data). Log deletions for audit.
- Self-service forget must verify identity to prevent one user wiping another's facts.
- Transparency output must respect the shadow-mute/privacy posture (don't leak others' facts).
- Retention/TTL is a config-schema change → version and document it.

## 8. Rollout Plan

- Ship forget-command first (low risk, reuses delete). Then retention sweeper (default off /
  generous window). Then scrubbing hardening. Then transparency.
- Feature-flag self-service forget; default moderator-only.

## 9. Future Enhancements

- Right-to-export (user data dump). Per-category retention policies. Encryption at rest for
  fact storage.

## 10. Open Questions

- Who may issue forget — moderator rank threshold? Self-service by exact-name match, or PM
  verification via the robot?
- Default retention window (or disabled by default)?
- Should expiry consider retrieval recency (last-surfaced) in addition to `created_at`?

---

## Rough sortie outline (to be expanded)

| # | Sortie (working title) | Gist | Rough REQ |
|---|------------------------|------|-----------|
| 1 | Forget command | `forget_user` on `kryten.llm.command`; authorized; audit-logged; reuses `store.delete` | 170–179 |
| 2 | Retention sweeper | Periodic expiry by age/importance via `created_at`/`score` + `delete_ids`; config window | 180–189 |
| 3 | PII/secret scrubbing hardening | Extend `safety.py` ruleset; fixture-tested precision/recall | 190–199 |
| 4 | Self-service forget | Opt-in chat trigger with identity verification; moderator-only by default | 200–209 |
| 5 | Transparency / inspection | "What do you know about me?" summary via `get_all`, privacy-safe | 210–219 |

**Dependencies within sprint**: 1 before 4 (self-service builds on the authorized command
path); 3 independent; 2 independent; 5 after 1 (shares the per-user read/authorization).
