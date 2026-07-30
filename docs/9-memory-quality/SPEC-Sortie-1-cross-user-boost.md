# SPEC-Sortie-1: Cross-user boost ranking

**Sprint**: 9 — Memory Quality & Observability
**PRD**: [PRD-memory-quality.md](PRD-memory-quality.md)
**Status**: Implemented — 2 tests green; per-scope boost_ranking (default on)
**Estimate**: 2–4h
**Depends on**: Sprint 8 (Sorties 1/2/7 scopes, Phase 7f `_rank_with_boost`)
**Requirements**: REQ-120 – REQ-129

---

## 1. Overview

Cross-user retrieval (topical/room/ambient) currently orders results by raw cosine similarity.
Speaker retrieval already re-ranks by similarity + importance + recency via Phase 7f
`_rank_with_boost`. Apply that same boost to cross-user result sets so the *most salient*
relevant fact wins, not merely the most textually similar.

## 2. Scope and Non-Goals

**In scope**: reuse `_rank_with_boost` for topical/room/ambient scopes; over-fetch tuning so
the boost has candidates to work with; config to toggle per scope.

**Non-goals**: a new/learned re-ranker (Sprint 9 §9 future); changing the boost formula.

## 3. Requirements

- **REQ-120** — Cross-user scopes re-rank candidates with the Phase 7f importance+recency
  boost before trimming to `top_k`.
- **REQ-121** — Over-fetch (`top_k*3`, bounded) applies to cross-user scopes so the boost can
  surface salient facts outside the pure-similarity top-K.
- **REQ-122** — Boost runs **before** the shadow-mute gate is irrelevant to correctness, but
  the gate still executes after (silenced users never survive regardless of boost).
- **REQ-123** — Per-scope toggle `boost_ranking` (default true once enabled) so operators can
  compare against pure similarity.
- **REQ-124** — LLM-mode only (boost requires importance metadata from Phase 7f); pure-
  similarity mode is unchanged.

## 4. Design

`_rank_with_boost` already accepts a candidate list and returns boosted ordering. Route
cross-user candidate lists through it in `_provide_impl` after the store query and before the
gate + trim:

```python
if scope.boost_ranking and self._llm_mode:
    candidates = self._rank_with_boost(candidates)
candidates = self._apply_gate(scope, candidates)      # Sprint 8
fragment_rows = candidates[: scope.top_k]
```

Ensure the store query over-fetches (`fetch_k = min(top_k*3, top_k+20)`) for cross-user
scopes, mirroring the existing speaker behavior.

## 5. Implementation Plan

**Modify**
- `long_term_memory.py` — thread `boost_ranking` through `RetrievalScope`; apply boost in the
  scope pipeline; extend over-fetch to cross-user scopes.
- `models/config.py` — add `boost_ranking` to topical/room/ambient config blocks.
- `config.example.json` — add the flag to each cross-user block.

## 6. Testing Strategy

- Two candidates with equal similarity but different importance → higher-importance wins after
  boost (mirrors existing `test_ltm_scoring` patterns).
- Over-fetch surfaces a high-importance, lower-similarity fact into the top-K.
- Pure-similarity mode (non-LLM) unchanged.
- Silenced user still excluded regardless of boost.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Cross-user fragments reflect boost ordering, test-proven vs. pure similarity.
- [ ] Gate still removes silenced users after boost.
- [ ] Non-LLM mode and disabled toggle preserve Sprint 8 behavior.

## 8. Rollout

- Enable after Sprint 8 in prod. No new external reads.
- Compare topical relevance before/after via Sortie 5 metrics.

## 9. Documentation

- `config.example.json` comments for `boost_ranking`.
- `docs/user-memory-explained.md`: note salience-based ordering for cross-user recall.
- `CHANGELOG.md` entry.
