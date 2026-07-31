# SPEC-Sortie-2: Importance-Gated Contradiction Decay

**Sprint**: 18 — Confidence Calibration & Decay Hardening
**PRD**: [PRD-confidence-calibration.md](PRD-confidence-calibration.md)
**Status**: Planned
**Estimate**: 2h
**Depends on**: Sprint 13 (contradiction decay), Sortie 1 (calibration confirms the need)
**Requirements**: REQ-375 – REQ-379

---

## 1. Overview

A single contradiction should not undermine a fact that has been corroborated many times.
Add an `importance_gated_decay` flag: when enabled, the effective decay rate scales inversely
with the fact's importance counter — a fact corroborated 10 times decays at 1/10th the rate.

## 2. Scope and Non-Goals

**In scope**: `importance_gated_decay` config field; modification to `_apply_confidence_decay`;
unit tests.

**Non-goals**: Changing the corroboration boost (Sprint 13 S2). Changing the decay floor.
Any retrieval changes.

## 3. Requirements

- **REQ-375** — `importance_gated_decay: bool` config field under `context.providers[].confidence`,
  default `False` (backward-compatible).
- **REQ-376** — When `True`, effective decay = `decay / max(importance, 1)`.
- **REQ-377** — Importance is read from the fact's existing metadata; missing → 1.
- **REQ-378** — The decay floor (`confidence_floor`) is still applied after gating.
- **REQ-379** — Default `False`: existing deployments see no change.

## 4. Design

In `_apply_confidence_decay`:
```python
# REQ-376: scale decay by 1/importance when gating is enabled.
if self._confidence_importance_gated_decay:
    importance = int(meta.get("importance", 1))
    decay = decay / max(importance, 1)
new_conf = max(floor, old_conf - decay)
```

## 5. Implementation Plan

**Modify**:
- `kryten_llm/components/context/providers/long_term_memory.py` — add
  `self._confidence_importance_gated_decay: bool = False` in `__init__`,
  wire in `from_config`, apply in `_apply_confidence_decay`.
- `config.example.json` — add `importance_gated_decay: false` comment.

## 6. Testing Strategy

- `importance=1, decay=0.1` → effective decay = 0.1 (unchanged).
- `importance=5, decay=0.1` → effective decay = 0.02.
- `importance=10, decay=0.1` → effective decay = 0.01.
- Floor still applied after gating.
- Default `False`: decay unchanged.

## 7. Acceptance Criteria

- [ ] Importance=5 decays at 0.02 when gated and 0.1 when not.
- [ ] Floor still applied correctly.
- [ ] Default config → no behavior change.

## 8. Rollout

Default off. No migration required.

## 9. Documentation

`CHANGELOG.md` entry. `config.example.json` comment.
