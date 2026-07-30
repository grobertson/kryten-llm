# SPEC-Sortie-3: Contradiction scorer

**Sprint**: 12 — Memory-Quality Evaluation Harness
**PRD**: [PRD-eval-harness.md](PRD-eval-harness.md)
**Status**: Planned
**Estimate**: 3–4h
**Depends on**: Sortie 1 (loader)
**Requirements**: REQ-260 – REQ-264

---

## 1. Overview

Build a **precision/recall scorer** for the Sprint 9 contradiction detector (`_is_contradiction`
via both the heuristic and embedding methods) using a labeled corpus of message/fact pairs.
Each labeled pair says whether the message contradicts the fact; the scorer measures how often
the detector agrees.

## 2. Scope and Non-Goals

**In scope**: labeled `contradiction.jsonl`; a scorer that calls `_is_contradiction` and
measures precision/recall; thresholds for both methods.

**Non-goals**: changing the contradiction detector; cross-user gate; live embedder (use mock).

## 3. Requirements

- **REQ-260** — Each scenario in `contradiction.jsonl` has: `{"message": str, "fact": str,
  "contradicts": bool, "method": "heuristic"|"embedding"|"both"}`.
- **REQ-261** — The scorer calls `_is_contradiction(message, fact, candidate_count)` (with
  the appropriate method configured) and compares to the `contradicts` label.
- **REQ-262** — Reports precision and recall separately for heuristic and embedding methods.
- **REQ-263** — Suite fails if heuristic recall < 0.70 or embedding precision < 0.65 (initial
  baselines; adjust after two stable runs).
- **REQ-264** — At least 20 labeled pairs in the corpus, balanced between true/false.

## 4. Design

```python
def score_contradictions(scenarios, provider) -> ContradictionReport:
    tp = fp = tn = fn = 0
    for s in scenarios:
        result = asyncio.run(provider._is_contradiction(s.message, s.fact, 10))
        if result and s.contradicts:   tp += 1
        elif result and not s.contradicts: fp += 1
        elif not result and s.contradicts: fn += 1
        else:                          tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall    = tp / (tp + fn) if (tp + fn) else 1.0
    return ContradictionReport(precision, recall)
```

## 5. Implementation Plan

**New**
- `tests/eval/scorers.py` — extend with `score_contradictions`, `ContradictionReport`.
- `tests/eval/test_contradiction.py` — `@pytest.mark.eval` test.
- `tests/eval/fixtures/contradiction.jsonl` — ≥ 20 labeled pairs.

## 6. Testing Strategy

- Unit test the report dataclass.
- Integration: small labeled set with known outcomes; assert report values make sense.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Scorer reports precision and recall for heuristic and embedding paths.
- [ ] At least 20 labeled pairs in the fixture.
- [ ] Thresholds enforced.

## 8. Rollout

- No production code changes.

## 9. Documentation

- `docs/EVAL_GUIDE.md`: contradiction corpus format; interpreting precision/recall.
- `CHANGELOG.md` entry.
