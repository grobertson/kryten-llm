# SPEC-Sortie-4: Attention-weighted pooling

**Sprint**: 9 — Memory Quality & Observability
**PRD**: [PRD-memory-quality.md](PRD-memory-quality.md)
**Status**: Implemented — 5 tests green; default pooling stays mean/recency
**Estimate**: 3–5h
**Depends on**: Sprint 8 Sortie 3 (window query) and Sortie 7 (mood vector)
**Requirements**: REQ-150 – REQ-159

---

## 1. Overview

Sprint 8 pools the conversation-window vector and the ambient mood vector with a plain (or
geometric-decay) mean. Upgrade both to a lightweight **attention-style weighting** so
higher-signal messages (longer, more topical, more recent) contribute more, and low-signal
lines (emotes, "lol", links) contribute less. This sharpens both the window query vector and
the ambient mood without adding a model dependency.

## 2. Scope and Non-Goals

**In scope**: pluggable pooling strategy (`mean` | `recency` | `attention`) shared by window
and mood; salience weighting; back-compat default.

**Non-goals**: transformer/learned attention; changing retrieval scopes themselves.

## 3. Requirements

- **REQ-150** — Pooling strategy is configurable: `mean` (Sprint 8) | `recency` | `attention`.
- **REQ-151** — `attention` weights each message vector by a salience score (length, recency,
  and self-similarity to the window centroid).
- **REQ-152** — The same pooling module serves both the window query vector and the ambient
  mood vector.
- **REQ-153** — Low-signal messages (below `min_salience`) are down-weighted or dropped.
- **REQ-154** — Default remains `mean`; existing behavior byte-compatible when unchanged.
- **REQ-155** — Pooling stays within the fail-open budget (bounded window size).

## 4. Design

Extract pooling into a shared helper used by Sprint 8 window and mood code:

```python
def pool(vectors, texts, *, strategy, recency_weight, min_salience):
    if strategy == "mean":       return normalize(mean(vectors))
    if strategy == "recency":    return normalize(geom_decay_mean(vectors, recency_weight))
    if strategy == "attention":
        w = [salience(t, i, n) for i, t in enumerate(texts)]   # length·recency·centrality
        w = [x if x >= min_salience else 0.0 for x in w]
        return normalize(weighted_mean(vectors, w) or mean(vectors))
```

`salience` is cheap and heuristic (token count, position/recency, cosine to the running
centroid). No new dependencies.

## 5. Implementation Plan

**New**
- `kryten_llm/components/memory/pooling.py` — `pool(...)` + `salience(...)`.

**Modify**
- `long_term_memory.py` — window vector builder (Sortie 3) and mood EWMA update (Sortie 7)
  call the shared pooler.
- `models/config.py` — `pooling_strategy`, `min_salience` (retrieval + ambient blocks).
- `config.example.json` — additions.

## 6. Testing Strategy

- `attention` down-weights ":thumbsup:" vs. a substantive sentence (assert weight ordering).
- `mean` strategy equals numpy mean (back-compat).
- Window terminated by an emote still yields a topically-relevant vector.
- Mood vector under attention converges faster to a sustained topic than plain mean.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] `attention` measurably improves window/mood relevance on the fixture threads.
- [ ] Default `mean` output unchanged.
- [ ] No p95 regression on the fail-open budget.

## 8. Rollout

- Default `mean`; enable `attention` per channel after validation.
- Compare retrieval relevance via Sortie 5 metrics.

## 9. Documentation

- `config.example.json` comments (strategy trade-offs).
- `docs/user-memory-explained.md`: pooling strategies.
- `CHANGELOG.md` entry.
