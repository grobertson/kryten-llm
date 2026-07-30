# SPEC-Sortie-4: Per-user engagement bias

**Sprint**: 11 — Adaptive Engagement
**PRD**: [PRD-adaptive-engagement.md](PRD-adaptive-engagement.md)
**Status**: Planned
**Estimate**: 2–4h
**Depends on**: Sortie 1 (score formula)
**Requirements**: REQ-245 – REQ-249

---

## 1. Overview

Optionally weight the engagement score by the *depth of stored memory about the speaker* — a
user the bot knows a lot about signals higher relational value, making the bot more likely to
greet or callback them. This is a light multiplicative bias on the existing score, not a
separate system.

## 2. Scope and Non-Goals

**In scope**: a per-user bias weight derived from the speaker's stored fact count + average
importance; multiplicative factor on the engagement score; config-gated, default-off.

**Non-goals**: per-channel bias; recency-based greeting campaigns; actively fetching facts just
to compute bias (must reuse already-available metadata).

## 3. Requirements

- **REQ-245** — Per-user bias is a multiplicative factor `bias ∈ [1.0, max_bias]` applied to
  the engagement score before the eagerness threshold.
- **REQ-246** — Bias is derived from the speaker's stored fact count and/or average importance
  (both available on the speaker's `provide()` result without an extra store query).
- **REQ-247** — Default `max_bias = 1.0` → no bias (score unchanged).
- **REQ-248** — Bias must not disclose *which* facts are held, only *that* the bot has more or
  fewer facts (timing signal only; privacy: REQ-165 posture).
- **REQ-249** — When the speaker has no stored facts, bias = 1.0 (neutral).

## 4. Design

Extend `EngagementSignals` with a `user_depth` field (0–1, normalized from fact count and
avg importance already surfaced by the speaker scope):

```python
bias = 1.0 + (cfg.max_bias - 1.0) * signals.user_depth
final_score = min(1.0, raw_score * bias)
```

`user_depth` is computed from the count of facts returned for the speaker and their average
importance — both already present in the speaker `provide()` result metadata.

## 5. Implementation Plan

**Modify**
- `engagement.py` — add `user_depth` to `EngagementSignals`; update `compute()` to apply bias.
- `long_term_memory.py` — populate `user_depth` from speaker scope result metadata.
- `models/config.py` — `max_bias` under `AutoParticipationConfig.engagement`.
- `config.example.json` — addition.

## 6. Testing Strategy

- `max_bias=1.0` → score unchanged (neutral).
- Speaker with many high-importance facts → bias > 1 → higher final score.
- Speaker with no facts → bias = 1.0.
- Final score capped at 1.0.
- Bias computation requires no extra store query (assert call count).
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] `max_bias=1.0` is behavior-identical to no bias.
- [ ] Known users with strong memory get a modest boost; unknown users get neutral.
- [ ] No extra store query.

## 8. Rollout

- Default `max_bias=1.0`. Enable modestly (1.2–1.5) after observing fire-rate metrics.

## 9. Documentation

- `config.example.json` comments (max_bias range and privacy note).
- `CHANGELOG.md` entry.
