# SPEC-Sortie-2: Temporal Hedging in Templates

**Sprint**: 20 — Temporal Fact Awareness
**PRD**: [PRD-temporal-awareness.md](PRD-temporal-awareness.md)
**Status**: Planned
**Estimate**: 2–3h
**Depends on**: Sortie 1 (`last_seen` reliably written); Sprint 13 (`ContextFragment.confidence`,
  confidence hedging in `trigger.j2`)
**Requirements**: REQ-410 – REQ-414

---

## 1. Overview

Add a `recency_days: int | None` field to `ContextFragment` and populate it from the
`last_seen` timestamp of the top-ranked speaker fact. Update `trigger.j2` to emit
age-band hedging phrases when `temporal_hedge_enabled` is True. The temporal hedging is
independent of and non-conflicting with the existing confidence hedging.

---

## 2. Scope and Non-Goals

**In scope**: `ContextFragment.recency_days` field; population in `_run_speaker_scope`;
`trigger.j2` temporal hedging block; new config fields on the `long_term_memory` provider;
unit tests.

**Non-goals**: `last_seen` backfill (Sortie 3). `config.example.json` update (Sortie 4).
The `system.j2` template is not modified in this sortie.

---

## 3. Requirements

- **REQ-410** — `ContextFragment` gains `recency_days: int | None = None`.
- **REQ-411** — In `_run_speaker_scope`, after ranking, compute `recency_days` from the
  top-ranked fact's `last_seen` (fallback: `created_at`; fallback: `None`).
  Set it on the emitted `user_memory` fragment.
- **REQ-412** — New provider config fields (under the `long_term_memory` provider config,
  alongside `confidence`): `temporal_hedge_enabled: bool = False`,
  `temporal_recent_threshold: int = 7` (days), `temporal_old_threshold: int = 90` (days).
- **REQ-413** — `trigger.j2` temporal hedging block:
  - `recency_days >= temporal_old_threshold` → strong hedge prefix.
  - `recency_days >= temporal_recent_threshold` AND `< temporal_old_threshold` → light hedge.
  - `recency_days < temporal_recent_threshold` OR `recency_days is None` → no hedge.
  Temporal hedging takes precedence over confidence hedging when both are enabled.
- **REQ-414** — Default `temporal_hedge_enabled: false`: `trigger.j2` behaviour is
  unchanged for existing deployments.

---

## 4. Design

### ContextFragment

```python
@dataclass
class ContextFragment:
    name: str
    priority: int
    text: str
    est_chars: int
    confidence: float | None = None   # Sprint 13
    recency_days: int | None = None   # Sprint 20, REQ-410
```

### `_run_speaker_scope` population

After building the `text` for the `user_memory` fragment:

```python
# Sprint 20, REQ-411: compute age of the top-ranked fact.
recency_days: int | None = None
if ranked:
    top_meta = ranked[0].get("metadata", {})
    top_ts = top_meta.get("last_seen") or top_meta.get("created_at")
    if top_ts:
        try:
            ts = datetime.fromisoformat(str(top_ts))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
            recency_days = max(0, int(age))
        except (ValueError, OverflowError):
            pass

return (
    [ContextFragment(
        name="user_memory",
        priority=self._priority,
        text=text,
        est_chars=len(text),
        confidence=avg_conf,
        recency_days=recency_days,   # REQ-411
    )] + signal_frags,
    surfaced_ids,
    speaker_signals,
)
```

### Provider config fields

In `LongTermMemoryProvider.__init__` (alongside confidence fields):
```python
self._temporal_hedge_enabled: bool = False
self._temporal_recent_threshold: int = 7
self._temporal_old_threshold: int = 90
```

In `from_config` (alongside confidence wiring):
```python
temporal_cfg = pcfg.get("temporal", {})
provider._temporal_hedge_enabled = bool(temporal_cfg.get("hedge_enabled", False))
provider._temporal_recent_threshold = int(temporal_cfg.get("recent_threshold_days", 7))
provider._temporal_old_threshold = int(temporal_cfg.get("old_threshold_days", 90))
```

These fields are passed to the template via the `ContextPipeline` or the prompt builder.
They must be accessible in the Jinja2 template rendering context. Check how `hedge_enabled`
and `hedge_above` are currently passed; use the same mechanism.

### trigger.j2

Replace the existing `user_memory` block:

```jinja2
{% if user_memory %}
{% if temporal_hedge_enabled and recency_days is defined and recency_days is not none %}
  {% if recency_days >= temporal_old_threshold %}
(From some time ago — things may have changed) {{ user_memory }}
  {% elif recency_days >= temporal_recent_threshold %}
(A while back) {{ user_memory }}
  {% else %}
{{ user_memory }}
  {% endif %}
{% elif confidence is defined and confidence is not none and confidence < hedge_above and hedge_enabled %}
I think {{ user_memory }}
{% else %}
{{ user_memory }}
{% endif %}
{% endif %}
```

---

## 5. Implementation Plan

**Modify** `kryten_llm/components/context/base.py`:
- Add `recency_days: int | None = None` to `ContextFragment`.

**Modify** `kryten_llm/components/context/providers/long_term_memory.py`:
- `__init__`: add `_temporal_hedge_enabled`, `_temporal_recent_threshold`,
  `_temporal_old_threshold`.
- `from_config`: wire from `pcfg.get("temporal", {})`.
- `_run_speaker_scope`: compute `recency_days`; pass to `ContextFragment`.
- Ensure temporal fields reach the template rendering context (trace how `hedge_enabled`
  flows through the pipeline to the template vars dict; replicate for temporal fields).

**Modify** `templates/trigger.j2`:
- Replace the `user_memory` block as shown above.

---

## 6. Testing Strategy

- `ContextFragment(name="x", priority=1, text="y", est_chars=1)` — `recency_days` defaults
  to `None`.
- `_run_speaker_scope` with fact `last_seen = 100 days ago` → `recency_days = 100`.
- `_run_speaker_scope` with no `last_seen` on any ranked fact → `recency_days = None`.
- Template: `temporal_hedge_enabled=True, recency_days=100, temporal_old_threshold=90`
  → output contains `"From some time ago"`.
- Template: `temporal_hedge_enabled=True, recency_days=30, thresholds=(7,90)`
  → output contains `"A while back"`.
- Template: `temporal_hedge_enabled=True, recency_days=3` → no hedge prefix.
- Template: `temporal_hedge_enabled=False` → existing confidence hedging behaviour.

---

## 7. Acceptance Criteria

- [ ] `ContextFragment.recency_days` field present, default `None`.
- [ ] `_run_speaker_scope` populates `recency_days` from `last_seen`.
- [ ] `_run_speaker_scope` sets `recency_days=None` when no timestamp available.
- [ ] `trigger.j2` hedges at 100 days with `temporal_hedge_enabled=True`.
- [ ] `trigger.j2` unchanged when `temporal_hedge_enabled=False`.

---

## 8. Rollout

Default `temporal_hedge_enabled: false`. No template output changes for existing deployments.

---

## 9. Documentation

`CHANGELOG.md` entry.
Update `docs/user-guide-templates.md` with the new template variables.
