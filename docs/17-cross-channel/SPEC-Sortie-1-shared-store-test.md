# SPEC-Sortie-1: Shared-Store Concurrency Validation

**Sprint**: 17 — Multi-Instance Shared Memory
**PRD**: [PRD-cross-channel.md](PRD-cross-channel.md)
**Status**: Planned
**Estimate**: 2–3h
**Depends on**: Sprint 8–10 (LongTermMemoryProvider, FakeStore, forget_user)
**Requirements**: REQ-340 – REQ-343

---

## 1. Overview

Validate that two `LongTermMemoryProvider` instances sharing the same `VectorStore` object
correctly share facts, maintain per-user isolation, and propagate erasure.  This is the
code-level proof that the shared-store deployment pattern is semantically correct.

## 2. Scope and Non-Goals

**In scope**: Test that shared-store sharing works at the provider level using `FakeStore`.
Test user isolation. Test `forget_user` erasure propagation. Test concurrent writes.

**Non-goals**: Testing Chroma HTTP server concurrency (that's a deployment concern, not a
code concern — the Chroma server handles it). Testing pgvector concurrency. Network tests.

## 3. Requirements

- **REQ-340** — Facts seeded into a shared store are visible to any provider instance
  pointing at that store.
- **REQ-341** — User isolation: querying for user A from provider B does not return user
  B's facts.
- **REQ-342** — `forget_user` called on one provider instance removes facts from the shared
  store; the other instance sees the deletion immediately on its next query.
- **REQ-343** — Concurrent `asyncio` writes from two providers to the same `FakeStore`
  do not corrupt or lose data (asyncio is single-threaded; both sets of facts persist).

## 4. Design

Use the existing `FakeStore` and `make_provider` from `tests/eval/harness.py`.
Pass the **same `FakeStore` instance** to two `make_provider` calls to simulate both bots
pointing at the same backend.

```python
shared = FakeStore()
embedder = FakeEmbedder()
primary = make_provider(shared, embedder)
secondary = make_provider(shared, embedder)
```

## 5. Implementation Plan

**New file**: `tests/test_multi_instance.py`

Tests:
1. `test_shared_store_visibility` — seed via store; both providers read the fact.
2. `test_user_isolation` — Alice's facts don't appear when secondary queries for Bob.
3. `test_forget_propagates` — primary.forget_user("alice"); secondary sees count == 0.
4. `test_concurrent_writes` — asyncio.gather of two seed_store calls; both persisted.
5. `test_silo_baseline` — two providers with **different** stores cannot see each other's
   facts (proves the shared-store pattern is a deliberate choice, not a default).

## 6. Testing Strategy

All tests use `FakeStore` + `FakeEmbedder` — no ONNX, no Chroma server, no network.
Runs in the default `pytest` suite. Coverage ≥ 85% on new code.

## 7. Acceptance Criteria

- [ ] All 5 tests pass.
- [ ] `test_silo_baseline` demonstrates that separate stores stay separate.
- [ ] `test_forget_propagates` confirms erasure reaches the shared store.
- [ ] Full suite (844+ tests) still green.

## 8. Rollout

Ships first; no config or runtime change. Purely additive test file.

## 9. Documentation

`CHANGELOG.md` entry. `docs/MULTI_INSTANCE.md` written in Sortie 2.
