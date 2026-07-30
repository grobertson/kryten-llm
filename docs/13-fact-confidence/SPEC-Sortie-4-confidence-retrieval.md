# SPEC-Sortie-4: Confidence-weighted retrieval

**Sprint**: 13 — Fact Confidence & Verification
**PRD**: [PRD-fact-confidence.md](PRD-fact-confidence.md)
**Status**: Planned
**Estimate**: 2–3h
**Depends on**: Sortie 1 (confidence field), Sprint 9 `_rank_with_boost`
**Requirements**: REQ-295 – REQ-299

---

## 1. Overview

Add ``confidence`` as a third axis in `_rank_with_boost` alongside importance and recency.
High-confidence facts rank higher; low-confidence facts are deprioritised but not hidden.
Default weight = 0 (no change until enabled).

## 2. Scope and Non-Goals

**In scope**: confidence weight in `_rank_with_boost`; config; default = 0 (transparent).

**Non-goals**: hiding very-low-confidence facts entirely (that's a later hardening step);
changing the novelty signal or template output.

## 3. Requirements

- **REQ-295** — `_rank_with_boost` adds ``confidence_weight * confidence`` to the score.
- **REQ-296** — ``confidence`` for facts that lack the field defaults to 0.5 (REQ-283).
- **REQ-297** — Config: ``retrieval_boost.confidence_weight`` (float ≥ 0, default 0.0).
- **REQ-298** — Weight = 0 is identical to current behaviour.
- **REQ-299** — Sprint 12 eval harness measures retrieval quality before/after enabling.

## 4. Design

In `_rank_with_boost`:
```python
confidence = float(meta.get("confidence", 0.5))
score += boost.confidence_weight * confidence
```

## 5. Implementation Plan

**Modify**
- `long_term_memory.py` — `_rank_with_boost`.
- `models/config.py` — `RetrievalBoostConfig.confidence_weight`.
- `config.example.json` — document the new weight.

## 6. Testing Strategy

- High-confidence fact ranks above equal-similarity low-confidence fact (weight > 0).
- Weight = 0 → identical ranking to current behaviour.
- Missing field defaults to 0.5 (midpoint, neutral).
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Confidence-weighted ranking improves precision@5 in the Sprint 12 eval harness
      (when corpus has high vs. low confidence facts).
- [ ] Weight=0 is transparent.

## 8. Rollout

- Default weight=0. Enable after measuring baseline with Sprint 12 harness.

## 9. Documentation

- `config.example.json` comments.
- `CHANGELOG.md` entry.
