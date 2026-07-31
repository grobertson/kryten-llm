# SPEC-Sortie-4: Config Docs & Eval Tests

**Sprint**: 20 — Temporal Fact Awareness
**PRD**: [PRD-temporal-awareness.md](PRD-temporal-awareness.md)
**Status**: Planned
**Estimate**: 1–2h
**Depends on**: Sorties 1–3 (all changes implemented)
**Requirements**: REQ-420 – REQ-424

---

## 1. Overview

Finalise Sprint 20 with three deliverables: (1) update `config.example.json` with the new
`recency_half_life_days` and `temporal` config fields, (2) add an eval test that verifies
recency ordering — a recently-corroborated fact ranks above an older fact with equal
importance and similarity — and (3) update `test_config.py` to verify the new
`RetrievalBoostConfig` field.

---

## 2. Scope and Non-Goals

**In scope**: `config.example.json` updates; `test_temporal_ranking.py` eval test;
`test_config.py` coverage for `recency_half_life_days`.

**Non-goals**: New code changes (Sorties 1–3 are complete). Changes to `DEPLOYMENT.md`
beyond the Sprint 20 upgrade note (added in Sortie 3).

---

## 3. Requirements

- **REQ-420** — `config.example.json` includes `recency_half_life_days: 0` (with inline
  comment) under `extractor.retrieval_boost`.
- **REQ-421** — `config.example.json` includes a `temporal` block under the
  `long_term_memory` provider config with `hedge_enabled`, `recent_threshold_days`,
  `old_threshold_days`.
- **REQ-422** — `test_config.py` asserts `RetrievalBoostConfig().recency_half_life_days == 0.0`.
- **REQ-423** — `test_temporal_ranking` asserts: given two facts with equal importance and
  equal cosine distance to a query, the one with `last_seen = today` ranks above the one
  with `last_seen = 180 days ago` when `recency_weight = 0.2` and `half_life_days = 90`.
- **REQ-424** — `test_temporal_ranking` asserts the legacy formula (`half_life_days = 0`)
  also preserves recency ordering (today > 180 days ago).

---

## 4. Design

### config.example.json additions

Under `extractor.retrieval_boost`:
```json
"retrieval_boost": {
  "importance_weight": 0.2,
  "recency_weight": 0.1,
  "confidence_weight": 0.0,
  "recency_half_life_days": 0
}
```

Under the `long_term_memory` provider's provider-level config:
```json
"temporal": {
  "hedge_enabled": false,
  "recent_threshold_days": 7,
  "old_threshold_days": 90
}
```

### test_config.py

```python
def test_retrieval_boost_config_defaults():
    cfg = RetrievalBoostConfig()
    assert cfg.importance_weight == 0.2
    assert cfg.recency_weight == 0.1
    assert cfg.confidence_weight == 0.0
    assert cfg.recency_half_life_days == 0.0   # REQ-422
```

### test_temporal_ranking.py

```python
from datetime import datetime, timezone, timedelta
import math
import pytest
from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider

def _make_result(distance: float, last_seen_days_ago: float) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(days=last_seen_days_ago)).isoformat()
    return {
        "id": f"fact_{last_seen_days_ago}",
        "document": "some fact",
        "distance": distance,
        "metadata": {
            "importance": 1,
            "confidence": 0.5,
            "last_seen": ts,
        },
    }

@pytest.mark.parametrize("half_life", [0.0, 90.0])
def test_recent_fact_ranks_above_stale(half_life):
    """REQ-423/424: recent fact outranks stale fact with equal importance+similarity."""
    from kryten_llm.models.config import RetrievalBoostConfig, ScoringConfig, ExtractorConfig

    boost_cfg = RetrievalBoostConfig(
        importance_weight=0.0,
        recency_weight=0.2,
        confidence_weight=0.0,
        recency_half_life_days=half_life,
    )
    scoring_cfg = ScoringConfig()
    ext_cfg = ExtractorConfig(retrieval_boost=boost_cfg, scoring=scoring_cfg)

    recent = _make_result(distance=0.3, last_seen_days_ago=0)
    stale = _make_result(distance=0.3, last_seen_days_ago=180)

    # Build a minimal provider to call _rank_with_boost
    # (or just test _recency_factor directly)
    now = datetime.now(timezone.utc)
    recent_score = LongTermMemoryProvider._recency_factor(
        recent["metadata"]["last_seen"], now, half_life
    )
    stale_score = LongTermMemoryProvider._recency_factor(
        stale["metadata"]["last_seen"], now, half_life
    )
    assert recent_score > stale_score, (
        f"half_life={half_life}: recent={recent_score:.4f} stale={stale_score:.4f}"
    )
```

---

## 5. Implementation Plan

**Modify** `config.example.json`:
- Add `recency_half_life_days` under `retrieval_boost`.
- Add `temporal` block under `long_term_memory` provider config.

**Modify** `tests/test_config.py`:
- Add `test_retrieval_boost_config_defaults` assertion for `recency_half_life_days`.

**New file** `tests/test_temporal_ranking.py` (or add to `tests/test_ltm_scoring.py`):
- `test_recent_fact_ranks_above_stale` parametrised on half_life.

---

## 6. Testing Strategy

The eval tests in this sortie run in the default pytest suite (not marked `@pytest.mark.eval`
since they test `_recency_factor` directly, not a full store interaction).

- `RetrievalBoostConfig()` defaults parse correctly.
- `config.example.json` parses without error (`test_config.py`).
- `_recency_factor(today, now, half_life=90)` == 1.0.
- `_recency_factor(180_days_ago, now, half_life=90)` == `math.exp(-2)` ≈ 0.135.
- Both `half_life=0` and `half_life=90` produce `recent_score > stale_score`.

---

## 7. Acceptance Criteria

- [ ] `config.example.json` includes `recency_half_life_days` and `temporal` block.
- [ ] `test_config.py` asserts `recency_half_life_days == 0.0`.
- [ ] `test_recent_fact_ranks_above_stale` passes for both `half_life=0.0` and `half_life=90.0`.
- [ ] All existing tests still pass.

---

## 8. Rollout

Config docs only. No runtime changes.

---

## 9. Documentation

`CHANGELOG.md` entry for Sprint 20 final.
`config.example.json` inline comment: `"// 0 = legacy formula; 90 = recommended starting value"`.
