# SPEC-Sortie-2: Corroboration confidence boost

**Sprint**: 13 — Fact Confidence & Verification
**PRD**: [PRD-fact-confidence.md](PRD-fact-confidence.md)
**Status**: Planned
**Estimate**: 2–3h
**Depends on**: Sortie 1 (confidence field present)
**Requirements**: REQ-285 – REQ-289

---

## 1. Overview

When a near-duplicate fact is encountered (dedup or related-mention path in `_persist`),
increment the existing fact's ``confidence`` score by a small additive step — corroboration
strengthens belief. Cap at 1.0 and use an exponential approach so repeated mentions
converge toward certainty rather than growing without bound.

## 2. Scope and Non-Goals

**In scope**: confidence increment in `_bump_importance`; configurable step; cap; no new
store queries.

**Non-goals**: contradiction decay (Sortie 3); retrieval weighting (Sortie 4); default off
— behaviour-neutral unless the optional `confidence.corroboration_step` config is > 0.

## 3. Requirements

- **REQ-285** — When `_bump_importance` is called (dedup or related-mention), also increment
  ``confidence`` by ``corroboration_step`` (default 0.05).
- **REQ-286** — Confidence is capped at 1.0 after each increment.
- **REQ-287** — Uses exponential approach: ``new_conf = conf + step * (1.0 - conf)``
  to converge toward 1.0 rather than adding linearly.
- **REQ-288** — Config: ``context.providers[].confidence.corroboration_step`` (float ≥ 0,
  default 0.05).
- **REQ-289** — Step = 0 is identical to current behaviour (no confidence change on bump).

## 4. Design

In `_bump_importance`:
```python
if corroboration_step > 0:
    old_conf = float(meta.get("confidence", 0.5))
    meta["confidence"] = min(1.0, old_conf + corroboration_step * (1.0 - old_conf))
```

## 5. Implementation Plan

**Modify**
- `long_term_memory.py` — `_bump_importance` path + config read.
- `models/config.py` — `ConfidenceConfig` nested in the provider's `retrieval` block.

## 6. Testing Strategy

- Single corroboration → confidence increases by expected amount.
- Multiple corroborations → converges toward 1.0, never exceeds it.
- Step = 0 → no change (current behaviour preserved, REQ-289).
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Repeated near-duplicates push confidence toward 1.0 monotonically.
- [ ] Step=0 is transparent (no behaviour change).

## 8. Rollout

- Default step=0.05; enable in config. Monitor via Sprint 12 eval harness.

## 9. Documentation

- `CHANGELOG.md` entry.
