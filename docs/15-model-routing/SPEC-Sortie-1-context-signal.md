# SPEC-Sortie-1: ContextSignal computation

**Sprint**: 15 — Memory-Aware Model Routing
**PRD**: [PRD-model-routing.md](PRD-model-routing.md)
**Status**: Planned
**Estimate**: 2–3h
**Depends on**: Sprints 11 (engagement score), 13 (confidence)
**Requirements**: REQ-310 – REQ-314

---

## 1. Overview

Define and compute a per-turn `ContextSignal ∈ [0, 1]` value that aggregates memory richness,
confidence, and trigger priority into a single routing signal. This sortie produces the signal;
it doesn't route yet — that's Sortie 2.

## 2. Scope and Non-Goals

**In scope**: `ContextSignal` dataclass; computation from fragments, engagement signals, and
trigger priority; wiring into `service.py` after `pipeline.build()`.

**Non-goals**: routing decisions (Sortie 2); provider tiers (Sortie 2); metrics (Sortie 3).

## 3. Requirements

- **REQ-310** — `ContextSignal` is a `float` in `[0, 1]` computed from: fragment count (capped
  at a configurable max), total character budget fraction, avg fragment confidence (Sprint 13),
  and trigger priority (normalised).
- **REQ-311** — Components are individually weighted; missing signals degrade gracefully to 0.
- **REQ-312** — Signal is computed in `service.py` after `pipeline.build()` returns.
- **REQ-313** — Config: `routing.signal.*` weights under the top-level `LLMConfig`.
- **REQ-314** — Default weights produce a signal but routing stays on the single default tier
  (Sortie 2 wires the routing).

## 4. Design

```python
@dataclass
class ContextSignal:
    fragment_count: int = 0
    budget_fraction: float = 0.0
    avg_confidence: float = 0.5
    trigger_priority: float = 0.0

def compute_signal(cs: ContextSignal, weights: SignalWeightsConfig) -> float:
    # Normalise + weighted sum → [0, 1]
    ...
```

Populated from the context dict after `pipeline.build()` — fragment count, budget used, and
the `_engagement_signals.max_importance` proxy for confidence.

## 5. Implementation Plan

**New**
- `kryten_llm/components/memory/routing.py` — `ContextSignal`, `compute_signal`.

**Modify**
- `kryten_llm/service.py` — compute signal after `pipeline.build()`.
- `kryten_llm/models/config.py` — `SignalWeightsConfig`, `RoutingConfig`.

## 6. Testing Strategy

- Full signals → score in [0, 1].
- Missing components → graceful degradation.
- Default weights → non-zero signal when fragments present.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] `ContextSignal` computed from real pipeline output.
- [ ] Score deterministic and in [0, 1].
- [ ] Default config produces correct signal with zero routing effect (Sortie 2 not yet wired).

## 8. Rollout

- Ship first; no routing change until Sortie 2.

## 9. Documentation

- `CHANGELOG.md` entry.
