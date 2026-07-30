# SPEC-Sortie-4: Per-trigger routing override

**Sprint**: 15 — Memory-Aware Model Routing
**PRD**: [PRD-model-routing.md](PRD-model-routing.md)
**Status**: Planned
**Estimate**: 2–3h
**Depends on**: Sortie 2 (tier routing live)
**Requirements**: REQ-325 – REQ-329

---

## 1. Overview

Allow individual trigger configurations to hard-pin a routing tier, overriding the signal
threshold. A "high-stakes mention" trigger might always use the premium tier; a background
auto-participation response might always use economy regardless of signal.

## 2. Scope and Non-Goals

**In scope**: `preferred_tier` field on `Trigger` config; override in routing logic when
non-empty.

**Non-goals**: per-user routing; time-of-day routing.

## 3. Requirements

- **REQ-325** — `triggers[].preferred_tier` (str | None, default None) pins the routing tier
  for that trigger, bypassing the signal threshold.
- **REQ-326** — When `preferred_tier` is set and the tier exists, it is always used.
- **REQ-327** — When `preferred_tier` names a non-existent tier, fall back to signal routing
  and log a warning.
- **REQ-328** — `preferred_tier = None` (default) → signal routing (no change).
- **REQ-329** — Backward-compatible: existing trigger configs with no `preferred_tier` field
  behave identically to today.

## 4. Design

In routing selection:
```python
trigger_tier = trigger_result.preferred_tier  # new field from TriggerResult
if trigger_tier and trigger_tier in self._tiers:
    return self._tiers[trigger_tier]
return self.route(signal, threshold)
```

## 5. Implementation Plan

**Modify**
- `kryten_llm/models/config.py` — `Trigger.preferred_tier`.
- `kryten_llm/models/events.py` — `TriggerResult.preferred_tier`.
- `kryten_llm/components/trigger_engine.py` — pass through `preferred_tier`.
- `kryten_llm/service.py` — pass tier override to routing.

## 6. Testing Strategy

- Known tier → always used regardless of signal.
- Unknown tier → fallback + warning.
- None → signal routing (default behavior).
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Trigger pinning overrides signal threshold.
- [ ] Unknown tier falls back gracefully.

## 8. Rollout

- Default None → no behavior change.

## 9. Documentation

- `config.example.json` trigger `preferred_tier` comments.
- `CHANGELOG.md` entry.
