# SPEC-Sortie-3: Contradiction confidence decay

**Sprint**: 13 — Fact Confidence & Verification
**PRD**: [PRD-fact-confidence.md](PRD-fact-confidence.md)
**Status**: Planned
**Estimate**: 2–4h
**Depends on**: Sortie 1 (confidence field), Sprint 9 (contradiction signal)
**Requirements**: REQ-290 – REQ-294

---

## 1. Overview

When the Sprint 9 contradiction signal fires (a new message contradicts a stored fact),
reduce the stored fact's ``confidence`` score by a configurable decay amount. The floor
prevents adversarial spam from draining confidence to zero. Uses the existing
`_novelty_signal` / `_is_contradiction` path — no extra store queries.

## 2. Scope and Non-Goals

**In scope**: confidence decay on contradiction detection; floor guard; rate-limit hook;
config-gated.

**Non-goals**: retrieval weighting (Sortie 4); changing the contradiction detection logic.

## 3. Requirements

- **REQ-290** — When `_is_contradiction` returns True in `_novelty_signal`, fetch the
  nearest fact's metadata and decrement ``confidence`` by ``contradiction_decay`` (default 0.1).
- **REQ-291** — Confidence floor: ``confidence >= confidence_floor`` (default 0.1) — never
  goes to zero from contradiction alone.
- **REQ-292** — Decay is applied asynchronously (fire-and-forget, off the critical path).
- **REQ-293** — Config: ``confidence.contradiction_decay`` and ``confidence.confidence_floor``.
- **REQ-294** — Decay = 0 is identical to current behaviour (no decay).

## 4. Design

In `_novelty_signal`, after confirming a contradiction:
```python
if decay > 0:
    asyncio.ensure_future(
        self._apply_confidence_decay(nearest["id"], decay, floor)
    )
```

`_apply_confidence_decay` reads the fact's metadata, computes
`new_conf = max(floor, conf - decay)`, and writes it back via `update_metadata`.

## 5. Implementation Plan

**Modify**
- `long_term_memory.py` — `_novelty_signal`: trigger decay; add `_apply_confidence_decay`.
- `models/config.py` — `ConfidenceConfig.contradiction_decay`, `.confidence_floor`.

## 6. Testing Strategy

- Contradiction fires → nearest fact's confidence decreases by expected amount.
- Floor guards against decay below threshold.
- Decay = 0 → no change.
- Decay is off-path (fire-and-forget); critical path timing unchanged.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Contradicted facts lose confidence; floor is respected.
- [ ] Off-path; never adds latency to the `provide()` call.

## 8. Rollout

- Default decay=0.1; floor=0.1. Monitor via Sprint 12 disclosure harness.

## 9. Documentation

- `CHANGELOG.md` entry.
