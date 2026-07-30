# SPEC-Sortie-2: Silent-path pre-check

**Sprint**: 11 — Adaptive Engagement
**PRD**: [PRD-adaptive-engagement.md](PRD-adaptive-engagement.md)
**Status**: Planned
**Estimate**: 2–4h
**Depends on**: Sprint 8 S6 (novelty signal path), Sprint 8 S7 (ambient mood vector)
**Requirements**: REQ-230 – REQ-239
**Ships first** — latency-safe, no behavior change without Sortie 3.

---

## 1. Overview

Coupling auto-participation to the engagement score risks adding latency to the *silent*
path — the majority of messages the bot ignores. This sortie adds a **cheap pre-check**
(no store query) that fast-paths the silent case: only when both the message-count threshold
*and* the pre-check pass does the bot proceed to full context retrieval.

## 2. Scope and Non-Goals

**In scope**: cheap two-signal check (novelty from already-held state, mood cosine from the
in-memory mood vector); integration into the auto-participation branch; no extra store hits.

**Non-goals**: the full engagement score (Sortie 1); the eagerness threshold (Sortie 3).

## 3. Requirements

- **REQ-230** — Pre-check runs only when the message-count threshold is met and
  auto-participation is triggered.
- **REQ-231** — Pre-check uses at most two signals requiring no store round-trip: the
  nearest-fact distance (if a prior provider result is cached) and the ambient mood cosine.
- **REQ-232** — Pre-check is configurable: `min_novelty` and `min_mood_cosine` thresholds; if
  either is 0 the signal is ignored (default: both 0 → always passes, current behavior).
- **REQ-233** — If no memory signals are available (provider disabled / cold-start), pre-check
  passes so the bot isn't permanently silenced.
- **REQ-234** — Pre-check adds no store query or embedder call; must be sub-millisecond.
- **REQ-235** — Pre-check result (pass/fail) is recorded as a metric (REQ-163 posture).

## 4. Design

The trigger engine retains a lightweight signal cache — the result of the last `provide()`
call containing novelty and mood data — which is populated off the critical path. The
pre-check reads this cache synchronously:

```python
def _precheck_passes(self, msg: str) -> bool:
    if not self.config.auto_participation.precheck.enabled:
        return True
    cfg = self.config.auto_participation.precheck
    signals = self._last_memory_signals   # populated after last provide()
    if signals is None:
        return True   # REQ-233: cold-start passes
    if cfg.min_novelty > 0 and signals.novelty < cfg.min_novelty:
        return False
    if cfg.min_mood_cosine > 0 and signals.mood_cosine < cfg.min_mood_cosine:
        return False
    return True
```

The `_last_memory_signals` stale-ok pattern is intentional: it uses the last observed state,
which is accurate enough for an engagement gate and avoids synchronous retrieval.

## 5. Implementation Plan

**Modify**
- `trigger_engine.py` — add `_precheck_passes()`, cache slot for last memory signals;
  integrate into the auto-participation branch.
- `service.py` — after the pipeline's `build()` returns, forward the engagement signals to the
  trigger engine's cache (single attribute set, off the critical response path).
- `models/config.py` — `precheck` block under `AutoParticipationConfig`.
- `config.example.json` — `auto_participation.precheck` block (default thresholds = 0).
- `health_monitor.py` — counter for pre-check passes/fails.

## 6. Testing Strategy

- Pre-check enabled with `min_novelty=0.4`: a low-novelty message (near-duplicate of known
  facts) → fail; a novel message → pass.
- No memory signals available → pass (REQ-233).
- Both thresholds = 0 → always pass (current behavior).
- Pre-check adds zero `store.query` calls (assert call count).
- Pass/fail metric incremented.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Silent-path messages with low novelty are pre-filtered; no store query issued.
- [ ] Cold-start (no signals) always passes.
- [ ] Default (both thresholds = 0) = current behavior.
- [ ] Sub-millisecond; no embedder/store calls.

## 8. Rollout

- Ship first; default thresholds = 0 (transparent). Enable non-zero thresholds only after
  signal data is observed via Sprint 9 metrics. Monitor pre-check fail rate.

## 9. Documentation

- `config.example.json` comments (pre-check thresholds + what they measure).
- `CHANGELOG.md` entry.
