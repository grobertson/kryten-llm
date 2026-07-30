# SPEC-Sortie-2: Provider tier routing

**Sprint**: 15 — Memory-Aware Model Routing
**PRD**: [PRD-model-routing.md](PRD-model-routing.md)
**Status**: Planned
**Estimate**: 3–4h
**Depends on**: Sortie 1 (ContextSignal)
**Requirements**: REQ-315 – REQ-319

---

## 1. Overview

Wire `ContextSignal` into `LLMManager` to select the provider tier for each turn: low-signal
turns get the "economy" tier (fast/cheap); high-signal turns get the "premium" tier
(smarter/slower). Default config collapses to current behavior (single tier).

## 2. Scope and Non-Goals

**In scope**: tier config; `LLMManager.route(signal)` method; per-turn tier selection in
`_handle_chat_message`; guard that rate limiter/spam still apply.

**Non-goals**: per-trigger overrides (Sortie 4); metrics (Sortie 3); A/B testing.

## 3. Requirements

- **REQ-315** — `routing.tiers` maps tier names → provider priority lists.
- **REQ-316** — `routing.signal_threshold` (default 0.0): if signal ≥ threshold, use
  `premium` tier; below, use `economy` tier. 0.0 = single tier (current behavior).
- **REQ-317** — When a tier's providers all fail, fall through to the other tier (REQ-003).
- **REQ-318** — Rate limiter and spam detector are never bypassed regardless of tier.
- **REQ-319** — Default config → single-tier = current behavior (no breaking change).

## 4. Design

```python
def route(self, signal: float, threshold: float) -> list[str]:
    if signal >= threshold and self._premium_providers:
        return self._premium_providers
    return self._economy_providers or self._default_priority
```

## 5. Implementation Plan

**Modify**
- `kryten_llm/components/llm_manager.py` — `route(signal)` method.
- `kryten_llm/service.py` — pass signal to `llm_manager.route()` before `generate_response`.
- `kryten_llm/models/config.py` — `RoutingConfig.tiers`, `.signal_threshold`.

## 6. Testing Strategy

- Signal ≥ threshold → premium providers used.
- Signal < threshold → economy providers used.
- Threshold = 0 → single tier (current behavior).
- Premium tier failure → falls through to economy.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Tier routing verified in unit tests with mocked providers.
- [ ] Default (threshold=0) → no change to observed behavior.

## 8. Rollout

- Default threshold=0. Raise after observing signal distribution in production.

## 9. Documentation

- `config.example.json` routing block.
- `CHANGELOG.md` entry.
