# SPEC-Sortie-2: Multi-Instance Deployment Guide

**Sprint**: 17 — Multi-Instance Shared Memory
**PRD**: [PRD-cross-channel.md](PRD-cross-channel.md)
**Status**: Planned
**Estimate**: 1–2h
**Depends on**: Sortie 1 (validation tests confirm the pattern is safe)
**Requirements**: REQ-344

---

## 1. Overview

Write `docs/MULTI_INSTANCE.md` — the operator-facing deployment guide for running two
kryten-llm instances (primary + secondary bot) against a shared fact store. Covers Chroma
HTTP server mode, pgvector, `ignored_users` peer exclusion, and example systemd units.

## 2. Scope and Non-Goals

**In scope**: `docs/MULTI_INSTANCE.md` covering both store backends, peer exclusion, and
the embedded-Chroma danger warning.

**Non-goals**: Code changes. Kubernetes/Docker deployment. Store migration tooling.

## 3. Requirements

- **REQ-344** — `docs/MULTI_INSTANCE.md` exists and covers: embedded-Chroma danger,
  Chroma HTTP setup, pgvector setup, `ignored_users` peer exclusion, and example config
  snippets for both bots.

## 4. Design

```
docs/MULTI_INSTANCE.md
  ├── Why shared memory?
  ├── The danger: embedded Chroma is single-process
  ├── Option A: Chroma HTTP server
  │     └── setup commands + both-bot config snippets
  ├── Option B: pgvector (already concurrency-safe)
  │     └── both-bot config snippet
  ├── Bot peer exclusion (ignored_users)
  ├── forget.user semantics in shared-store mode
  └── Example systemd units (primary + secondary)
```

## 5. Implementation Plan

**New file**: `docs/MULTI_INSTANCE.md`

## 6. Testing Strategy

Documentation-only sortie. No automated test. Reviewed against the validation tests in
Sortie 1 to ensure the guide matches what the tests prove.

## 7. Acceptance Criteria

- [ ] `docs/MULTI_INSTANCE.md` written and committed.
- [ ] Covers both Chroma HTTP and pgvector deployment paths.
- [ ] Includes `ignored_users` guidance.
- [ ] Includes the embedded-Chroma danger warning prominently.

## 8. Rollout

Documentation only; no runtime change. Can be published independently.

## 9. Documentation

This sortie is itself the documentation deliverable. `CHANGELOG.md` entry.
