# SPEC-Sortie-3: Temporal Confidence Drift Sweep

**Sprint**: 18 — Confidence Calibration & Decay Hardening
**PRD**: [PRD-confidence-calibration.md](PRD-confidence-calibration.md)
**Status**: Planned
**Estimate**: 2–3h
**Depends on**: Sorties 1–2; Sprint 10 (RetentionSweeper pattern)
**Requirements**: REQ-380 – REQ-384

---

## 1. Overview

Add a `ConfidenceDriftSweeper` — a background task that nudges confidence downward for
facts whose `last_seen` (or `created_at` as fallback) is older than `drift_after_days`.
Models the intuition that stale, un-corroborated facts should be less trusted over time
even without a direct contradiction signal.

## 2. Scope and Non-Goals

**In scope**: `ConfidenceDriftSweeper` class in `retention.py`; `ConfidenceDriftConfig`
in `models/config.py`; wiring in `service.py`; unit tests.

**Non-goals**: Deleting facts (that's the RetentionSweeper). Temporal drift does NOT gate
proactive injection or retrieval ranking directly — it simply adjusts the stored confidence
value, which then affects the existing confidence-weighted retrieval (Sprint 13 S4) when
`confidence_weight > 0`.

## 3. Requirements

- **REQ-380** — `ConfidenceDriftSweeper` applies drift: for each fact where `now - last_seen >
  drift_after_days`, reduce confidence by `drift_rate_per_day * dormant_days`.
- **REQ-381** — Floored at `confidence_floor`; facts already at the floor are skipped.
- **REQ-382** — Default off (`confidence_drift.enabled = false`). No migration needed.
- **REQ-383** — Errors are logged per-fact and the sweep never crashes the service loop.
- **REQ-384** — Count of drifted facts logged at INFO after each sweep.

## 4. Design

```python
class ConfidenceDriftSweeper:
    def __init__(self, store, interval_hours, drift_after_days,
                 drift_rate_per_day, floor, health_monitor): ...
    
    async def sweep(self) -> int:
        """One pass. Returns count of facts whose confidence was updated."""
        cutoff = now - timedelta(days=self._drift_after_days)
        records = await self._store.get_all()
        updated = 0
        for r in records:
            last = _parse_ts(r["metadata"].get("last_seen") or r["metadata"].get("created_at"))
            if last is None or last > cutoff:
                continue  # recent enough, no drift
            dormant_days = (now - last).total_seconds() / 86400.0
            old_conf = float(r["metadata"].get("confidence", 0.5))
            if old_conf <= self._floor:
                continue  # already at floor
            reduction = self._rate * dormant_days
            new_conf = max(self._floor, old_conf - reduction)
            if new_conf < old_conf:
                await self._store.update_metadata(...)
                updated += 1
        return updated
```

## 5. Implementation Plan

**New in** `kryten_llm/components/memory/retention.py`:
- `ConfidenceDriftSweeper` class (same lifecycle pattern as `RetentionSweeper`).

**Modify** `kryten_llm/models/config.py`:
- `ConfidenceDriftConfig` (enabled, drift_after_days, drift_rate_per_day, confidence_floor,
  interval_hours).
- Add `confidence_drift: ConfidenceDriftConfig` field to `LLMConfig`.

**Modify** `kryten_llm/service.py`:
- Start `ConfidenceDriftSweeper` alongside `RetentionSweeper` when configured.

## 6. Testing Strategy

- Fact last_seen 60 days ago, rate=0.001, threshold=30 → drift applied.
- Fact last_seen 10 days ago → no drift (under threshold).
- Fact at floor → skipped.
- `enabled=False` → sweeper not started.
- Sweep count returned correctly.

## 7. Acceptance Criteria

- [ ] Dormant fact gets its confidence reduced after sweep.
- [ ] Recent fact unchanged.
- [ ] Floor respected.
- [ ] Default `enabled=False` → no sweeper started.

## 8. Rollout

Default off. Can be enabled with a config change; no store migration required.

## 9. Documentation

`config.example.json` `confidence_drift` block. `CHANGELOG.md` entry.
