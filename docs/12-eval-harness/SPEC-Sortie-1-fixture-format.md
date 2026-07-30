# SPEC-Sortie-1: Fixture format & loader

**Sprint**: 12 — Memory-Quality Evaluation Harness
**PRD**: [PRD-eval-harness.md](PRD-eval-harness.md)
**Status**: Planned
**Estimate**: 3–4h
**Depends on**: Sprint 8–11 merged; existing test fakes available as seed
**Requirements**: REQ-250 – REQ-254

---

## 1. Overview

Define the JSONL corpus schema for eval fixtures and build the loader + in-memory-store
seeders that all subsequent sorties depend on. This is the infrastructure sortie — nothing
scores yet, but after this sortie the fixture pipeline is wired end-to-end.

## 2. Scope and Non-Goals

**In scope**: JSONL schema; a `FixtureLoader` that reads, validates, and seeds a
`LongTermMemoryProvider` (against a mocked/in-memory store); a pytest fixture exposing a
seeded provider; teardown.

**Non-goals**: scoring logic (Sortie 2–4); CLI (Sortie 5); real Chroma/pgvector dependency
in the normal test run.

## 3. Requirements

- **REQ-250** — Fixture format is JSONL; each line is a JSON object with:
  `{"label": str, "facts": [{"user", "summary", "category", "importance", "created_at"}],
   "query": str, "expected_ids": [str], "silenced_users": [str], "tags": [str]}`.
- **REQ-251** — The loader validates required fields and raises clearly on schema errors.
- **REQ-252** — A `seed_provider(facts)` helper upserts the fixture facts into the provider's
  vector store using the provider's existing `_upsert_facts` path (or direct store upsert).
- **REQ-253** — Fixtures are deterministic: `stable_fact_id` is used for IDs so re-seeding
  is idempotent.
- **REQ-254** — A `tests/eval/` directory is created; the `@pytest.mark.eval` marker is
  declared in `pyproject.toml` and excluded from the default `pytest` run.

## 4. Design

```
tests/
  eval/
    __init__.py
    fixtures/
      retrieval.jsonl     # Sortie 2 corpus
      contradiction.jsonl # Sortie 3 corpus
      disclosure.jsonl    # Sortie 4 corpus
    conftest.py           # pytest fixtures: seeded_provider, etc.
    harness.py            # FixtureLoader + seed_provider
```

`FixtureLoader.load(path)` returns a list of `EvalScenario` dataclasses.
`seed_provider(provider, scenarios)` calls `provider._store.upsert(...)` directly.

## 5. Implementation Plan

**New**
- `tests/eval/harness.py` — `EvalScenario` dataclass, `FixtureLoader`, `seed_provider`.
- `tests/eval/conftest.py` — `seeded_provider(scenarios)` pytest fixture (module scope).
- `tests/eval/__init__.py`
- `tests/eval/fixtures/retrieval.jsonl` — 10+ retrieval scenarios.
- `tests/eval/fixtures/contradiction.jsonl` — labeled contradiction pairs.
- `tests/eval/fixtures/disclosure.jsonl` — silenced-user scenarios.

**Modify**
- `pyproject.toml` — register `eval` marker; add `addopts = "-m 'not eval'"` guard.

## 6. Testing Strategy

- Unit tests for `FixtureLoader`: schema validation, malformed input raises, idempotent seed.
- Verify `@pytest.mark.eval` tests are skipped in the default run.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] `FixtureLoader.load(path)` reads and validates all three fixture files without errors.
- [ ] `seed_provider` seeds a provider and the facts are retrievable by query.
- [ ] `pytest` (no flags) does not run `@pytest.mark.eval` tests.
- [ ] `pytest -m eval` runs the eval suite.

## 8. Rollout

- Ships without changing any production code paths. Off by default.

## 9. Documentation

- `README.md` or `docs/EVAL_GUIDE.md`: how to run the eval suite, add fixtures, interpret
  results.
- `CHANGELOG.md` entry (new eval infrastructure).
