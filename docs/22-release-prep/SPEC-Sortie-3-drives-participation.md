# SPEC-Sortie-3: Wire `drives_participation` to the Auto-Participation Path

**Sprint**: 22 — Release Prep / Gap Removal
**PRD**: [PRD-release-prep.md](PRD-release-prep.md)
**Status**: Planned
**Estimate**: 2h
**Depends on**: Sprint 21 (`_proactive_drives_participation` stored on provider,
  `proactive_memory_active` written into context data dict); Sprint 11 (eagerness
  gate pattern in `TriggerEngine`/`service.py`)
**Requirements**: REQ-471 – REQ-475

---

## 1. Overview

`_proactive_drives_participation` is read from config and stored on `LongTermMemoryProvider`
but never acted on. When `drives_participation: true`, a strong proactive match on an
`auto_participation` turn should override the eagerness gate and cause the bot to speak.

The wiring is done entirely in `service.py` using data already present in the context
dict — no imports from LTM provider internals required.

---

## 2. Scope and Non-Goals

**In scope**: Writing `proactive_drives_participation` into the LTM context data dict;
reading it in `service.py` auto-participation flow; unit tests covering the override and
the default-false no-change case.

**Non-goals**: New rate-limiting for the override path (future work). Changes to
`TriggerEngine` (not needed — the override happens after the trigger check, at the speak
decision). No changes to `health_monitor.py` or `metrics_server.py`.

---

## 3. Requirements

- **REQ-471** — `LongTermMemoryProvider._run_proactive_scope` writes
  `"proactive_drives_participation": self._proactive_drives_participation` into the
  returned `ContextFragment.data` dict alongside `proactive_memory_active`. This key is
  merged into the shared context dict by the pipeline, making it available in `service.py`
  without any provider import.
- **REQ-472** — In `service.py`, in the auto-participation speak decision (after the
  eagerness / score gate check), add an override path:
  ```python
  if (
      not should_speak
      and ctx.get("proactive_memory_active")
      and ctx.get("proactive_drives_participation")
      and trigger_result.trigger_type == "auto_participation"
  ):
      should_speak = True
      logger.debug(
          "auto_participation overridden by proactive match for user=%s",
          username,
      )
  ```
  The override fires only when all four conditions hold: `should_speak` is False (the
  normal eagerness gate blocked it), a proactive fragment was emitted, `drives_participation`
  is True, and the trigger type is `auto_participation`.
- **REQ-473** — Default behaviour is preserved: when `drives_participation = false`
  (the default), `ctx.get("proactive_drives_participation")` is `False` and the override
  block is never entered.
- **REQ-474** — When `proactive.enabled = false` (proactive scope not run), no
  `proactive_memory_active` key is written into the context and the override is never
  entered regardless of `drives_participation`.
- **REQ-475** — Two unit tests in `tests/test_proactive_injection.py`:
  1. `test_drives_participation_override`: eagerness gate fails, proactive fragment present,
     `drives_participation=true` → `should_speak` ends True.
  2. `test_drives_participation_default_no_override`: same conditions but
     `drives_participation=false` (default) → `should_speak` remains False.

---

## 4. Design

### LongTermMemoryProvider._run_proactive_scope

The `proactive_memory_active` key is already written in `data`. Add the companion key:

```python
return [
    ContextFragment(
        name="proactive_memory",
        priority=self._proactive_priority,
        text=doc,
        est_chars=len(doc),
        confidence=conf,
        data={
            "proactive_memory": doc,
            "proactive_memory_active": True,
            "proactive_drives_participation": self._proactive_drives_participation,  # REQ-471
        },
    )
]
```

### service.py — auto-participation speak decision

Locate the block that evaluates `should_speak` for `auto_participation` turns (after the
eagerness gate). Add the override immediately after the gate evaluates to False:

```python
# Existing eagerness gate (Sprint 11):
should_speak = engagement_score >= eagerness_threshold or force_speak

# Sprint 22 (REQ-472): proactive override.
if (
    not should_speak
    and ctx.get("proactive_memory_active")
    and ctx.get("proactive_drives_participation")
    and trigger_type == "auto_participation"
):
    should_speak = True
    logger.debug(
        "auto_participation overridden by proactive match for user=%s", username
    )
```

### Context dict merge

The pipeline already merges `ContextFragment.data` dicts into the shared context. No
pipeline changes are needed — `proactive_drives_participation` arrives automatically once
the fragment `data` dict includes it.

---

## 5. Edge Cases

| Scenario | Expected behaviour |
|---|---|
| `proactive.enabled=false` | No fragment emitted → `proactive_memory_active` absent → no override |
| `proactive.enabled=true`, sim below threshold | No fragment emitted → same as above |
| `drives_participation=false` (default) | `ctx["proactive_drives_participation"]` is False → no override |
| `drives_participation=true`, trigger_type = `mention` | `trigger_type != "auto_participation"` → no override |
| `drives_participation=true`, eagerness gate passes | `should_speak` already True → override skipped (no-op) |
| `drives_participation=true`, eagerness gate fails, strong match | All four conditions → override fires, bot speaks |
