# SPEC-Sortie-1: Calibration Metric in Eval Harness

**Sprint**: 18 — Confidence Calibration & Decay Hardening
**PRD**: [PRD-confidence-calibration.md](PRD-confidence-calibration.md)
**Status**: Planned
**Estimate**: 2–3h
**Depends on**: Sprint 12 (eval harness), Sprint 13 (confidence field)
**Requirements**: REQ-370 – REQ-374

---

## 1. Overview

Add a confidence calibration scorer to the Sprint 12 eval harness. The scorer measures
whether high-confidence facts have higher mean importance (corroboration count) than
low-confidence facts — using importance as a proxy for fact correctness, since corroboration
is the organic signal that a fact has been repeatedly confirmed.

## 2. Scope and Non-Goals

**In scope**: `CalibrationReport` dataclass; `score_calibration(records)` function in
`tests/eval/scorers.py`; calibration tests in `tests/test_confidence_calibration.py`.

**Non-goals**: Human-labeled ground truth. Retrieval metrics (those are Sprint 12). The
calibration scorer is a standalone function, not integrated with the existing eval CLI (that
can be a future enhancement).

## 3. Requirements

- **REQ-370** — `score_calibration(records)` accepts a list of store records (dicts with
  `metadata.confidence` and `metadata.importance`) and returns a `CalibrationReport`.
- **REQ-371** — Records are grouped into tiers: `low` (conf < 0.5), `mid` (0.5–0.8),
  `high` (≥ 0.8). Mean importance is computed per tier.
- **REQ-372** — `CalibrationReport.monotonic` is True when mean_importance increases
  monotonically: high ≥ mid ≥ low.
- **REQ-373** — `passes_baseline` is True when the high tier's mean importance ≥ low tier's.
  (Tolerates mid being out of order — 3-tier monotonicity is the aspirational goal.)
- **REQ-374** — Empty tiers (no facts at a confidence level) degrade gracefully; the tier is
  skipped when computing monotonicity.

## 4. Design

```python
@dataclass
class CalibrationReport:
    tiers: dict[str, dict[str, float]]  # tier -> {mean_importance, mean_confidence, count}
    monotonic: bool       # high_imp >= mid_imp >= low_imp
    calibration_score: float  # 0–1: fraction of adjacent tier pairs that are ordered
    n_facts: int
    
    @property
    def passes_baseline(self) -> bool:
        return (
            self.tiers.get("high", {}).get("mean_importance", 0)
            >= self.tiers.get("low", {}).get("mean_importance", 0)
        )

def score_calibration(records: list[dict]) -> CalibrationReport:
    """Compute calibration from records with metadata.confidence / metadata.importance."""
```

## 5. Implementation Plan

**Modify**: `tests/eval/scorers.py` — add `CalibrationReport`, `score_calibration()`.
**New file**: `tests/test_confidence_calibration.py` — tests for all three sorties.

## 6. Testing Strategy

- Well-calibrated facts: high confidence + high importance → `passes_baseline = True`.
- Miscalibrated facts: high confidence + low importance → `passes_baseline = False`.
- Empty tiers: graceful degradation, no ZeroDivisionError.
- Single tier: monotonicity True (vacuously).

## 7. Acceptance Criteria

- [ ] `score_calibration` returns correct tier stats.
- [ ] `passes_baseline` True for well-calibrated fixture, False for inverted one.
- [ ] No exceptions on empty or single-tier inputs.

## 8. Rollout

Eval tests only (`@pytest.mark.eval`). No runtime change.

## 9. Documentation

`CHANGELOG.md` entry.
