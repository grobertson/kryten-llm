# SPEC-Sortie-1: Engagement score

**Sprint**: 11 — Adaptive Engagement
**PRD**: [PRD-adaptive-engagement.md](PRD-adaptive-engagement.md)
**Status**: Planned
**Estimate**: 3–5h
**Depends on**: Sprint 8 (memory signals exist), Sprint 9 (Sprint 9 S5 observability)
**Requirements**: REQ-220 – REQ-229
**Note**: Implement after Sortie 2 (pre-check ships first; score extends it).

---

## 1. Overview

Combine the memory signals that Sprints 8–9 produce into a single normalized
`engagement_score ∈ [0, 1]` that represents "how much does the bot have to say right now?"
This score is later consumed by the eagerness knob (Sortie 3) and per-user bias (Sortie 4).

## 2. Scope and Non-Goals

**In scope**: score formula combining novelty, topical similarity, ambient mood, and salience;
per-component weights; normalization; no behavior change without Sortie 3.

**Non-goals**: the speak/stay-silent decision (that's Sortie 3); per-user weighting (Sortie 4).

## 3. Requirements

- **REQ-220** — `engagement_score` is a `float` in `[0, 1]` derived from the available memory
  signals for the current turn.
- **REQ-221** — Components: novelty (1 − top-1 speaker similarity), topical fragment
  similarity, ambient mood cosine to current message, and top importance in candidate set.
- **REQ-222** — Components are individually weighted; missing signals default to 0 (graceful
  degradation if a scope is disabled).
- **REQ-223** — Score is computed **after** the pre-check passes (Sortie 2); avoids any score
  computation on the silent path.
- **REQ-224** — Score is logged at debug level (no content, REQ-165 posture).
- **REQ-225** — Configurable weights under `auto_participation.engagement`; defaults produce
  current behavior (score effectively disabled, all weight on novelty if all other signals
  absent).

## 4. Design

A `EngagementScorer` helper (new module) collects signals from the provider's last
`provide()` output and the ambient mood state:

```python
@dataclass
class EngagementSignals:
    novelty: float = 0.0         # 1 - top-1 similarity (already in _novelty_signal path)
    topical_max_sim: float = 0.0 # max similarity in topical_memory candidates
    mood_cosine: float = 0.0     # cosine(mood_vec, message_vec) if ambient available
    max_importance: float = 0.0  # max normalized importance in candidates

def compute(signals, weights) -> float:
    raw = (
        weights.novelty * signals.novelty +
        weights.topical * signals.topical_max_sim +
        weights.mood * signals.mood_cosine +
        weights.importance * signals.max_importance
    )
    return max(0.0, min(1.0, raw / max(sum(weights.values()), 1.0)))
```

Signals are collected in the provider's `provide()` path and exposed on `ContextFragment`
metadata or a thin object passed back through the pipeline. The trigger engine receives the
score when calling the pipeline's `build()`.

## 5. Implementation Plan

**New**
- `kryten_llm/components/memory/engagement.py` — `EngagementSignals` dataclass + `compute()`.

**Modify**
- `long_term_memory.py` — populate `EngagementSignals` during `_provide_impl` (reuse values
  already computed); attach to the return value or a side-channel on the provider.
- `context/pipeline.py` — surface `engagement_score` in the `build()` return dict so the
  trigger engine can consume it.
- `models/config.py` — `engagement` block under `AutoParticipationConfig`.
- `config.example.json` — `auto_participation.engagement` weights.

## 6. Testing Strategy

- With full signals (novelty 0.8, topical 0.6, mood 0.5, importance 0.7) and equal weights →
  score within expected range.
- Missing signals (no topical/ambient) → score gracefully degrades (not zero if novelty high).
- Weights sum to zero → score = 0 (no divide-by-zero).
- Score is in `[0, 1]` for all inputs.
- No score computation before the pre-check passes (call count assertion).
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Score formula is deterministic and documented.
- [ ] Missing signals degrade gracefully.
- [ ] Score is available to the trigger engine via the `build()` return.
- [ ] No computation on the silent path (pre-check must gate it).

## 8. Rollout

- Ship after Sortie 2. Score is computed but ignored until Sortie 3 wires it into the
  decision. Monitor `llm_memory_*` metrics for retrieval timing.

## 9. Documentation

- `config.example.json` weight comments.
- `docs/user-memory-explained.md`: what the engagement score measures.
- `CHANGELOG.md` entry.
