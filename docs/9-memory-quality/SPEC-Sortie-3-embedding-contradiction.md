# SPEC-Sortie-3: Embedding-based contradiction detection

**Sprint**: 9 — Memory Quality & Observability
**PRD**: [PRD-memory-quality.md](PRD-memory-quality.md)
**Status**: Implemented — 6 tests green; default contradiction_method=heuristic
**Estimate**: 4–6h
**Depends on**: Sprint 8 Sortie 6 (novelty/contradiction signal)
**Requirements**: REQ-140 – REQ-149

---

## 1. Overview

Sprint 8's contradiction signal uses a shallow keyword/negation heuristic. Upgrade it to an
**embedding-based** check: a message is a likely contradiction/update when it is *topically
close* to a stored fact but *semantically opposed*. This reduces false positives from
coincidental word overlap and catches contradictions the keyword heuristic misses.

## 2. Scope and Non-Goals

**In scope**: opposition scoring using embeddings; cold-start guard; keep the read-only
`memory_signal` fragment contract; retain the heuristic as a cheap pre-filter.

**Non-goals**: full NLI/entailment model (Sprint 12 roadmap); auto-editing stored facts.

## 3. Requirements

- **REQ-140** — Contradiction requires topical similarity ≥ `contradiction_min_similarity`
  (existing) AND an opposition score above `opposition_threshold`.
- **REQ-141** — Opposition score derived from embeddings (e.g. antonym/negation-augmented
  comparison), not just keyword negation.
- **REQ-142** — Cold-start guard: skip contradiction detection when the user has fewer than
  `min_facts_for_contradiction` stored facts.
- **REQ-143** — Still emits the read-only `memory_signal` fragment; never mutates stored facts.
- **REQ-144** — Falls back to the Sprint 8 heuristic if the opposition scorer is unavailable
  (fail-open).
- **REQ-145** — No additional store round-trip beyond the nearest-fact already fetched.

## 4. Design

Reuse the nearest stored speaker fact (already fetched in Sprint 8 Sortie 6). Compute an
opposition score between the incoming message and that fact:

```python
sim = 1.0 - nearest.distance
if sim >= cfg.contradiction_min_similarity and user_fact_count >= cfg.min_facts_for_contradiction:
    opp = opposition_score(message, nearest.document)   # embedding-based
    if opp >= cfg.opposition_threshold:
        signal = ("contradiction", nearest.document)
```

`opposition_score` v1: compare the message embedding against a negation-augmented transform of
the fact (e.g. embed "not {fact}" / a small antonym-substituted variant) and measure relative
closeness. Keep it cheap and dependency-light; the keyword heuristic remains a fast pre-filter
and the fallback.

## 5. Implementation Plan

**New**
- `kryten_llm/components/memory/opposition.py` — `opposition_score(...)` helper.

**Modify**
- `long_term_memory.py` — replace the Sortie 6 contradiction branch; add cold-start guard;
  fallback to heuristic.
- `models/config.py` — `opposition_threshold`, `min_facts_for_contradiction`.
- `config.example.json` — novelty block additions.

## 6. Testing Strategy

- "I hate horror now" vs. stored "loves horror" → contradiction (high sim + high opposition).
- Coincidental word overlap with no opposition → no contradiction (fixes heuristic false
  positive).
- User with < `min_facts_for_contradiction` facts → no signal.
- Scorer unavailable → heuristic fallback path used.
- No extra `store.query` issued.
- Precision improves vs. heuristic on a labeled fixture set.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Measured contradiction precision improves over the Sprint 8 heuristic on the fixture set.
- [ ] No fact mutated; signal remains read-only.
- [ ] Fail-open to heuristic when scorer unavailable.

## 8. Rollout

- Default-off (keep Sprint 8 heuristic) until fixture precision validated, then enable.
- Track contradiction-signal counts via Sortie 5.

## 9. Documentation

- `config.example.json` comments.
- `docs/user-memory-explained.md`: contradiction detection semantics + limits.
- `CHANGELOG.md` entry.
