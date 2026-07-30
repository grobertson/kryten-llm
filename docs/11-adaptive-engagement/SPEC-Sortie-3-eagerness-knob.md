# SPEC-Sortie-3: Eagerness knob

**Sprint**: 11 — Adaptive Engagement
**PRD**: [PRD-adaptive-engagement.md](PRD-adaptive-engagement.md)
**Status**: Planned
**Estimate**: 2–4h
**Depends on**: Sortie 1 (score), Sortie 2 (pre-check wired)
**Requirements**: REQ-240 – REQ-244

---

## 1. Overview

Wire the engagement score into the auto-participation speak/stay-silent decision via an
operator-tunable `eagerness` threshold. When the count fires **and** the pre-check passes
**and** `engagement_score >= eagerness`, the bot speaks. This replaces/augments the pure
message-count threshold without changing any default.

## 2. Scope and Non-Goals

**In scope**: `eagerness` threshold config; score-gated auto-participation; guardrails; metrics.

**Non-goals**: per-user weighting (Sortie 4); changing the count-threshold logic itself.

## 3. Requirements

- **REQ-240** — When `eagerness > 0`, the bot speaks on auto-participation only when
  `engagement_score >= eagerness` (in addition to the count threshold and pre-check).
- **REQ-241** — Default `eagerness = 0` → behavior is identical to today (count threshold
  only).
- **REQ-242** — Hard ceiling: the `rate_limiter` and `spam_detector` always apply regardless
  of score; the score gate is additive, not a bypass.
- **REQ-243** — A "forced" speak path: if `eagerness > 0` and `force_interval` messages have
  passed without the bot speaking (score always below threshold), force a speak to avoid the
  bot going permanently silent in a high-signal community.
- **REQ-244** — Score-gate pass/fail is logged (debug, no content) and incremented as a metric.

## 4. Design

In `check_triggers` auto-participation branch:

```python
if self._precheck_passes(msg):
    score = self._get_engagement_score()
    eagerness = self.config.auto_participation.eagerness
    if eagerness > 0 and score < eagerness:
        self._score_misses += 1
        if self._score_misses < self.config.auto_participation.force_interval:
            return TriggerResult(triggered=False, ...)    # stay silent
        # force_interval exceeded → speak anyway
    self._score_misses = 0
    # ... proceed to trigger
```

`_get_engagement_score()` reads the signal computed in Sortie 1 (no extra retrieval).

## 5. Implementation Plan

**Modify**
- `trigger_engine.py` — score-gate logic + `_score_misses` counter + `force_interval`.
- `models/config.py` — `eagerness`, `force_interval` under `AutoParticipationConfig`.
- `config.example.json` — additions (both default 0 / disabled).
- `health_monitor.py` — `record_engagement_score_gate(passed: bool)` counter.

## 6. Testing Strategy

- `eagerness=0` → current behavior (all count-threshold fires pass through).
- `eagerness=0.8`, low score → silent; high score → triggers.
- `force_interval` kicks in after N consecutive misses (prevents permanent silence).
- Rate limiter still fires even when engagement score is high.
- Metric incremented for each gate evaluation.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] `eagerness=0` default is behavior-identical to today.
- [ ] High-eagerness config suppresses low-signal turns; high-signal turns fire normally.
- [ ] `force_interval` prevents permanent silence.
- [ ] Rate limits not bypassed by the score.

## 8. Rollout

- Default `eagerness=0`. Enable gradually with a low value (0.2) and observe fire-rate vs.
  signal metrics before raising.

## 9. Documentation

- `config.example.json` comments (eagerness range guidance, force_interval).
- `CHANGELOG.md` entry (behavior change when eagerness > 0).
