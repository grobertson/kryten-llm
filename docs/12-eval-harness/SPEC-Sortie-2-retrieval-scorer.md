# SPEC-Sortie-2: Retrieval scorer

**Sprint**: 12 — Memory-Quality Evaluation Harness
**PRD**: [PRD-eval-harness.md](PRD-eval-harness.md)
**Status**: Planned
**Estimate**: 3–5h
**Depends on**: Sortie 1 (loader + seeded provider fixture)
**Requirements**: REQ-255 – REQ-259

---

## 1. Overview

Measure retrieval quality of `LongTermMemoryProvider.provide()` using **precision@k** and
**MRR** (Mean Reciprocal Rank) over the `retrieval.jsonl` corpus. Each scenario has a query
and a set of expected fact IDs; the scorer checks how many expected IDs appear in the top-k
results and at what rank the first expected ID appears.

## 2. Scope and Non-Goals

**In scope**: precision@k and MRR scorers; scoring over all provider scopes (speaker,
topical, room); baseline thresholds that fail the suite when violated.

**Non-goals**: scoring other metrics (Sorties 3–4); live provider calls; cross-user scope
requires the full pipeline — use mock gates.

## 3. Requirements

- **REQ-255** — `precision_at_k(retrieved_ids, expected_ids, k)` returns the fraction of
  top-k retrieved results that appear in `expected_ids`.
- **REQ-256** — `mean_reciprocal_rank(retrieved_ids, expected_ids)` returns the mean of the
  reciprocal rank of the first expected ID in each query's result list.
- **REQ-257** — Eval scenarios in `retrieval.jsonl` cover: single-user speaker scope, topical
  cross-user scope, and (optionally) room scope.
- **REQ-258** — Suite fails (via `assert`) if precision@5 falls below a baseline (initial
  baseline: 0.6; tighten after two stable runs).
- **REQ-259** — The scorer is fast: all scenarios complete in < 10s (mocked embedder).

## 4. Design

```python
def precision_at_k(retrieved: list[str], expected: set[str], k: int) -> float:
    top = retrieved[:k]
    return sum(1 for rid in top if rid in expected) / k if k else 0.0

def mean_reciprocal_rank(retrieved: list[str], expected: set[str]) -> float:
    for rank, rid in enumerate(retrieved, 1):
        if rid in expected:
            return 1.0 / rank
    return 0.0
```

Each eval scenario's query is embedded with the mocked embedder (deterministic random vector
seeded from the query string); retrieval hits are checked against `expected_ids`.

## 5. Implementation Plan

**New**
- `tests/eval/scorers.py` — `precision_at_k`, `mean_reciprocal_rank`, `RetrievalReport`.
- `tests/eval/test_retrieval.py` — `@pytest.mark.eval` test class scoring over
  `retrieval.jsonl`; asserts baseline.

**Modify**
- `tests/eval/fixtures/retrieval.jsonl` — add ≥ 10 scenarios.

## 6. Testing Strategy

- Unit tests for scorer functions (edge cases: empty retrieved, all hits, no hits).
- Integration test: seed a provider with known facts, run a known query, assert expected IDs
  rank highly.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] `pytest -m eval -k retrieval` reports precision@5 and MRR for each scenario.
- [ ] Baseline threshold enforced; suite fails clearly when violated.
- [ ] Scorer unit tests cover edge cases.

## 8. Rollout

- No production code changes. Ships as an eval-only file.

## 9. Documentation

- `docs/EVAL_GUIDE.md`: adding retrieval scenarios; interpreting scores.
- `CHANGELOG.md` entry.
