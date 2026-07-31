# SPEC-Sortie-1: Recency Score Refinement

**Sprint**: 20 — Temporal Fact Awareness
**PRD**: [PRD-temporal-awareness.md](PRD-temporal-awareness.md)
**Status**: Planned
**Estimate**: 2h
**Depends on**: Sprint 9 (`_rank_with_boost`, `RetrievalBoostConfig`), Sprint 13
  (importance/confidence metadata fields, `_rank_with_boost` confidence axis)
**Requirements**: REQ-405 – REQ-409

---

## 1. Overview

Two changes to the recency layer:

1. Upgrade `_recency_factor` from the non-configurable `1/(1+age_days)` formula to a
   configurable exponential half-life: `exp(-age_days / half_life_days)`. Backward-compatible:
   when `half_life_days = 0` (new default), the legacy formula is used unchanged.
2. Fix the heuristic-mode `_upsert_facts` gap: it writes `created_at` but never `last_seen`,
   so `_recency_factor` always returns 0.0 for heuristic-mode facts. Add `last_seen = now`
   to every upsert.

---

## 2. Scope and Non-Goals

**In scope**: `_recency_factor` signature and logic in `long_term_memory.py`; `last_seen`
written in `_upsert_facts`; `recency_half_life_days` field in `RetrievalBoostConfig`;
unit tests.

**Non-goals**: `recency_days` on `ContextFragment` (Sortie 2). Backfill CLI (Sortie 3).
`config.example.json` update (Sortie 4). No change to `recency_weight` default value.

---

## 3. Requirements

- **REQ-405** — New field `RetrievalBoostConfig.recency_half_life_days: float = 0.0`
  (`ge=0.0`). When 0, `_recency_factor` uses the legacy formula. When > 0, uses
  `math.exp(-age_days / half_life_days)`.
- **REQ-406** — `_recency_factor` signature becomes
  `(last_seen: str, now: datetime, half_life_days: float = 0.0) -> float`.
- **REQ-407** — `_upsert_facts` writes `"last_seen": now` in every fact's metadata
  (alongside the existing `"created_at": now`). This ensures heuristic-mode facts
  participate in recency ranking.
- **REQ-408** — `_rank_with_boost` passes `boost.recency_half_life_days` to the
  `_recency_factor` call.
- **REQ-409** — Default `recency_half_life_days = 0.0`: existing deployments see no
  ranking change.

---

## 4. Design

### Modified `_recency_factor`

```python
@staticmethod
def _recency_factor(
    last_seen: str,
    now: datetime,
    half_life_days: float = 0.0,
) -> float:
    """Return a [0,1] recency factor from an ISO timestamp.

    Sprint 20 (REQ-405): when half_life_days > 0, uses exponential decay
    exp(-age / half_life); otherwise legacy hyperbolic 1/(1+age_days).
    """
    if not last_seen:
        return 0.0
    try:
        ts = datetime.fromisoformat(last_seen)
    except ValueError:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
    if half_life_days > 0:
        return math.exp(-age_days / half_life_days)   # REQ-405
    return 1.0 / (1.0 + age_days)                    # REQ-409 legacy
```

### Modified `_rank_with_boost`

```python
recency = self._recency_factor(
    meta.get("last_seen", ""),
    now,
    half_life_days=boost.recency_half_life_days,   # REQ-408
)
```

### Modified `_upsert_facts`

```python
meta: dict[str, Any] = {
    "user": fact.user,
    "category": fact.category,
    "source": fact.source,
    "created_at": now,
    "last_seen": now,          # REQ-407: heuristic mode now writes last_seen
    "score": fact.score,
    "confidence": min(1.0, fact.score / 100.0),
    "evidence": str(fact.evidence.get("message", ""))[:200],
}
```

### New `RetrievalBoostConfig` field

```python
recency_half_life_days: float = Field(
    default=0.0,
    ge=0.0,
    description=(
        "Exponential recency half-life in days (Sprint 20, REQ-405). "
        "0.0 = legacy hyperbolic formula 1/(1+age_days) (backward-compatible). "
        "90 days = at 90 days, score ≈ 0.37; recommended starting value."
    ),
)
```

---

## 5. Implementation Plan

**Modify** `kryten_llm/components/context/providers/long_term_memory.py`:
1. `_recency_factor`: add `half_life_days` parameter; add exponential branch.
2. `_rank_with_boost`: pass `boost.recency_half_life_days` to `_recency_factor`.
3. `_upsert_facts`: add `"last_seen": now` to the metadata dict.

**Modify** `kryten_llm/models/config.py`:
- `RetrievalBoostConfig`: add `recency_half_life_days` field.

---

## 6. Testing Strategy

Add tests to the existing `tests/test_ltm_scoring.py` (or a new
`tests/test_temporal_awareness.py`):

- **Legacy formula** (`half_life=0`): `_recency_factor("...", now)` returns
  `1 / (1 + age_days)`. E.g. at 1 day: ≈ 0.5; at 0 days: 1.0.
- **Exponential** (`half_life=90`): at 0 days → 1.0; at 90 days → `math.exp(-1)` ≈ 0.368;
  at 180 days → `math.exp(-2)` ≈ 0.135.
- **Missing `last_seen`**: returns 0.0 regardless of formula.
- **Invalid ISO timestamp**: returns 0.0 without raising.
- **`_upsert_facts` writes `last_seen`**: assert `meta["last_seen"]` present after upsert.
- **`_rank_with_boost` with recency**: fact with recent `last_seen` ranks above same-sim
  fact with old `last_seen` when `recency_weight > 0`.
- **No regression**: existing `test_ltm_scoring.py` passes unchanged (`half_life=0`
  default preserves old behaviour).

---

## 7. Acceptance Criteria

- [ ] `_recency_factor` with `half_life=0`: same output as the old formula.
- [ ] `_recency_factor` with `half_life=90, age=90`: output ≈ 0.368.
- [ ] Heuristic-mode upsert includes `last_seen` in metadata.
- [ ] `_rank_with_boost` passes `half_life_days` through.
- [ ] All existing `test_ltm_scoring.py` tests pass.

---

## 8. Rollout

Default `recency_half_life_days = 0.0` — no ranking change for existing deployments.
Operator sets `90` (under `extractor.retrieval_boost.recency_half_life_days`) to enable.

---

## 9. Documentation

`CHANGELOG.md` entry.
`config.example.json` update in Sortie 4.
