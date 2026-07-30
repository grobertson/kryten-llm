# SPEC-Sortie-1: Confidence field and baseline

**Sprint**: 13 — Fact Confidence & Verification
**PRD**: [PRD-fact-confidence.md](PRD-fact-confidence.md)
**Status**: Planned
**Estimate**: 2–3h
**Depends on**: Sprints 8–12 merged
**Requirements**: REQ-280 – REQ-284

---

## 1. Overview

Introduce a ``confidence ∈ [0, 1]`` metadata field on every fact — the foundation for
Sorties 2–5. This sortie adds the field, sets a sensible default, and ensures existing
facts are treated as having the baseline value. No behaviour changes yet.

## 2. Scope and Non-Goals

**In scope**: ``confidence`` in the `_upsert_facts` and `_persist` metadata paths; a
baseline default; the Sprint 12 eval harness can track it.

**Non-goals**: corroboration boost (Sortie 2); contradiction decay (Sortie 3); retrieval
weighting (Sortie 4); hedged template (Sortie 5).

## 3. Requirements

- **REQ-280** — A ``confidence`` field (float, ``[0, 1]``) is stored in every new fact's
  metadata from this sprint forward.
- **REQ-281** — Heuristic-extracted facts default to
  ``confidence = min(1.0, score / 100.0)`` (maps the existing 0–100 score to [0, 1]).
- **REQ-282** — LLM-extracted facts already carry ``ef.confidence``; this value is stored
  unchanged (it is already ``[0, 1]``).
- **REQ-283** — Existing facts that lack a ``confidence`` field are treated as
  ``confidence = 0.5`` wherever it is read (read-path default, no migration needed).
- **REQ-284** — The field is present in the Sprint 12 eval harness's ``FakeStore`` so
  confidence-aware scoring can be exercised offline.

## 4. Design

In `_upsert_facts` (heuristic path):
```python
meta["confidence"] = min(1.0, fact.score / 100.0)
```

In `_persist` (LLM path) — field already set via `ef.confidence`; no change needed there.

In `_rank_with_boost` and anywhere `metadata.get("confidence")` is used, fall back to 0.5
when the field is absent (REQ-283).

## 5. Implementation Plan

**Modify**
- `long_term_memory.py` — add ``confidence`` to `_upsert_facts` metadata dict (heuristic path).
- `harness.py` (tests/eval) — add ``confidence`` to the ``seed_store`` metadata dict.

## 6. Testing Strategy

- Heuristic upsert produces ``confidence`` in metadata proportional to score.
- LLM persist retains the extractor's confidence value.
- Missing field reads as 0.5 (test `metadata.get("confidence", 0.5)`).
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] All newly written facts carry a ``confidence`` field.
- [ ] No schema migration needed for existing facts (read-path default).
- [ ] Harness fixtures include confidence so Sortie 4+ can be eval-scored.

## 8. Rollout

- Ship first (additive metadata; no behaviour change).

## 9. Documentation

- `CHANGELOG.md` entry (additive metadata field).
