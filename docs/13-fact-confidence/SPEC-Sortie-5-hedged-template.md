# SPEC-Sortie-5: Hedged template presentation

**Sprint**: 13 — Fact Confidence & Verification
**PRD**: [PRD-fact-confidence.md](PRD-fact-confidence.md)
**Status**: Planned
**Estimate**: 2–3h
**Depends on**: Sortie 1 (confidence field), Sortie 4 (score-weighted ranking)
**Requirements**: REQ-300 – REQ-309

---

## 1. Overview

Expose average fragment confidence to the prompt template so that low-confidence facts
are presented with hedged language ("I think X mentioned…") and high-confidence facts
with assertive language ("X has mentioned…"). Feature-flagged; default off.

## 2. Scope and Non-Goals

**In scope**: average confidence computed from speaker-scope results; attached to the
`ContextFragment`; Jinja2 template reads it to vary phrasing.

**Non-goals**: per-fact hedging within the fragment text (only fragment-level averaging);
hiding facts entirely based on confidence.

## 3. Requirements

- **REQ-300** — `ContextFragment` gains an optional ``confidence`` float field (average
  over contributing facts; 0–1).
- **REQ-301** — The template receives ``confidence`` and uses it to select phrasing:
  - ``confidence >= hedge_above`` (default 0.7): assertive phrasing.
  - ``confidence < hedge_above``: hedged phrasing ("I think…", "I believe…").
- **REQ-302** — Config: ``confidence.hedge_above`` (default 0.7) and
  ``confidence.hedge_enabled`` (default false).
- **REQ-303** — When disabled, the template behaves identically to today.
- **REQ-304** — Privacy: confidence is a numeric scalar only; no fact content is
  exposed beyond the existing fragment text.

## 4. Design

In `_run_speaker_scope`, compute average confidence from the ranked results:
```python
avg_conf = sum(float(r["metadata"].get("confidence", 0.5)) for r in ranked) / len(ranked)
fragment = ContextFragment(name="user_memory", ..., confidence=avg_conf)
```

In `templates/trigger.j2`:
```jinja
{% if memory.confidence and memory.confidence < hedge_above %}
  I think {{ username }} may have mentioned: {{ memory.text }}
{% else %}
  {{ username }} has mentioned: {{ memory.text }}
{% endif %}
```

## 5. Implementation Plan

**Modify**
- `context/base.py` — add ``confidence: float | None = None`` to `ContextFragment`.
- `long_term_memory.py` — populate ``confidence`` in `_run_speaker_scope`.
- `templates/trigger.j2` — conditional phrasing based on ``confidence`` (if enabled).
- `models/config.py` — `ConfidenceConfig.hedge_above`, `.hedge_enabled`.

## 6. Testing Strategy

- Low-confidence fragment → template uses hedged phrasing (when enabled).
- High-confidence fragment → assertive phrasing.
- Feature disabled → no phrasing change (REQ-303).
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Hedged phrasing appears for low-confidence fragments when enabled.
- [ ] Default disabled → no change to existing template output.

## 8. Rollout

- Default disabled. Enable per deployment and monitor with Sprint 12 harness.

## 9. Documentation

- `docs/user-memory-explained.md`: what confidence means for the user experience.
- `CHANGELOG.md` entry.
