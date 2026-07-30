# PRD: Right-to-Export & Memory Lifecycle

**Sprint**: 16 — `16-lifecycle-export`
**Status**: ❌ DROPPED — 2026-07-30
**Reason**: GDPR compliance and data-portability standards are not requirements for this
  deployment. The lifecycle/export theme (encryption at rest, per-category retention,
  right-to-portability) is over-engineered for the actual use-case. Sprint 10 already
  covers the erasure side (forget.user, retention TTLs) which is sufficient.
**Formerly**: Draft (N+2)
**Superseded by**: no replacement scheduled. Sprint 17 advances to N+1.

> The original PRD content is preserved below for reference only. Do not implement.

---

## 1. Problem Statement

Sprint 10 added self-service forget, operator forget, and retention TTLs — the **erasure**
side of privacy. The **export and lifecycle** side remains unaddressed: users cannot retrieve
a portable copy of their stored facts (right-to-portability), fact storage is unencrypted at
rest, and retention policies operate globally rather than per-category (e.g. biographical facts
might warrant longer retention than gaming preferences). As the corpus grows across many sprints,
the lack of these controls becomes a liability.

**Who benefits**: operators (compliance posture, GDPR-adjacent defensibility), the community
(users can see and take their data), and the project (reduces risk from the growing corpus).

## 2. User Stories

- *As a user*, I want to request a portable export of everything the bot knows about me
  (right-to-portability), so I can review or archive it.
- *As an operator*, I want fact storage encrypted at rest, so a compromised store doesn't
  directly expose community member data.
- *As an operator*, I want per-category retention windows (e.g. location data expires in 30
  days, general preferences in 365 days), so I can tune data minimisation per sensitivity.
- *As a moderator*, I want to trigger a full export for a user via a NATS command, so I can
  fulfil a data request without shell access.

## 3. Feasibility / Technical Read

- **Right-to-export**: `store.get_all(where={"user": ...})` already exists (Sprint 5/10).
  Serialise to JSON; add `export.user` command on `kryten.llm.command`; same auth as
  `inspect.user` (Sprint 10). Delivery: reply payload or a temporary NATS subject.
- **Encryption at rest**: Chroma → filesystem-level (OS or volume encryption, out of scope
  for the service itself); pgvector → Postgres-level TDE or column-level encryption for the
  `metadata` JSONB. Both require ops-level changes; the service adds config hooks to document
  the expectation and refuse to start without confirmed encryption (via a `require_encryption`
  flag).
- **Per-category retention**: extend the `RetentionSweeper` (Sprint 10) with a
  `per_category` map that overrides `max_age_days` per metadata `category` value.
- **Risk**: encryption-at-rest for pgvector column-level encryption adds query complexity;
  evaluate feasibility against Sprint 12's eval harness before committing.

## 4. Rough Scope (candidate sorties)

1. `export.user` NATS command — serialise and return user's facts as JSON.
2. Per-category retention overrides — extend `RetentionSweeper` config + logic.
3. Encryption readiness — config flag, startup assertion, documentation.

## 5. Open Questions

- Delivery channel for large exports (reply payload vs. temp subject vs. file)?
- Encryption-at-rest: in-service (column encryption) vs. ops-level (volume)?
- How to migrate existing unencrypted stores?

**REQ reservation**: REQ-310+ (finalised at promotion).
