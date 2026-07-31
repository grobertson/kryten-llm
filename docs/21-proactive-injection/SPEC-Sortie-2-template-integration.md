# SPEC-Sortie-2: Template Integration

**Sprint**: 21 — Proactive Memory Injection
**PRD**: [PRD-proactive-injection.md](PRD-proactive-injection.md)
**Status**: Planned
**Estimate**: 1–2h
**Depends on**: Sortie 1 (`proactive_memory` fragment emitted by the provider);
  Sprint 13 (template rendering context, `trigger.j2` structure)
**Requirements**: REQ-431 – REQ-434

---

## 1. Overview

Update `trigger.j2` and `system.j2` to handle the `proactive_memory` fragment. When a
`proactive_memory` fragment is present in the rendering context, `trigger.j2` inserts it
as a contextual hint before the response. `system.j2` receives a `proactive_memory_active`
flag that nudges the LLM to weave the memory naturally if relevant.

---

## 2. Scope and Non-Goals

**In scope**: `trigger.j2` proactive block; `system.j2` proactive hint; wiring of
`proactive_memory` and `proactive_memory_active` into the template rendering context
(via `ContextPipeline` or the prompt builder); unit tests for template rendering.

**Non-goals**: Config model (Sortie 3). Observability (Sortie 4). No changes to
`fact_extraction_*.j2` or `media_change.j2`.

---

## 3. Requirements

- **REQ-431** — `trigger.j2` renders a `proactive_memory` block when the variable
  `proactive_memory` is set and non-empty.
- **REQ-432** — `system.j2` renders a proactive hint when `proactive_memory_active` is `True`.
- **REQ-433** — The prompt builder (or `ContextPipeline`) extracts the `proactive_memory`
  fragment text from the context fragment list and passes it as `proactive_memory` (string)
  and `proactive_memory_active` (bool) to the Jinja2 render context.
- **REQ-434** — When `proactive_memory` is absent or empty, the templates are unchanged
  relative to current behaviour.

---

## 4. Design

### trigger.j2 addition

Add after the `user_memory` block and before the end of the template:

```jinja2
{% if proactive_memory %}
(Something relevant about you just came to mind: {{ proactive_memory }})
{% endif %}
```

### system.j2 addition

Add to the system prompt, near the memory/context instructions:

```jinja2
{% if proactive_memory_active %}
A memory about the current speaker has been flagged as topically relevant to what they
just said. If it fits naturally into your response, weave it in. Don't force the
connection if it doesn't add value.
{% endif %}
```

### Rendering context wiring

Inspect how `user_memory` (string) and `confidence` are currently passed to the Jinja2
rendering context. The `proactive_memory` fragment follows the same path:

1. `ContextPipeline._collect_fragments()` already collects all provider fragments.
2. The prompt builder extracts named fragments by `fragment.name`.
3. Extend the fragment-extraction logic to also extract:
   ```python
   proactive_frag = next(
       (f for f in fragments if f.name == "proactive_memory"), None
   )
   render_vars["proactive_memory"] = proactive_frag.text if proactive_frag else ""
   render_vars["proactive_memory_active"] = proactive_frag is not None
   ```

Locate the exact extraction point in `kryten_llm/components/context/pipeline.py` or the
prompt builder and apply the addition there.

---

## 5. Implementation Plan

**Modify** `templates/trigger.j2`:
- Add `{% if proactive_memory %}` block.

**Modify** `templates/system.j2`:
- Add `{% if proactive_memory_active %}` block.

**Modify** `kryten_llm/components/context/pipeline.py` (or the prompt builder):
- Extract `proactive_memory` and `proactive_memory_active` from the fragment list and pass
  to the render context (same pattern as `user_memory`).

---

## 6. Testing Strategy

Test the templates in isolation with Jinja2 rendering (same pattern as `test_prompt_builder.py`):

- `proactive_memory = "loves samurai films"` → rendered output contains the proactive block.
- `proactive_memory = ""` or `proactive_memory` absent → no proactive block in output.
- `proactive_memory_active = True` → system prompt contains the weave-in hint.
- `proactive_memory_active = False` → system prompt unchanged.
- Full pipeline test: `LongTermMemoryProvider` with `proactive_enabled=True` emits fragment
  → pipeline passes `proactive_memory` to template → rendered prompt contains the text.

---

## 7. Acceptance Criteria

- [ ] `trigger.j2` renders proactive block when `proactive_memory` is set.
- [ ] `trigger.j2` unchanged when `proactive_memory` is absent/empty.
- [ ] `system.j2` renders hint when `proactive_memory_active=True`.
- [ ] `system.j2` unchanged when `proactive_memory_active=False`.
- [ ] Pipeline correctly maps `proactive_memory` fragment → template variable.

---

## 8. Rollout

Template changes are gated by `proactive_memory` being absent by default (no `proactive`
config yet — Sortie 3). Existing template rendering is unchanged.

---

## 9. Documentation

`CHANGELOG.md` entry.
Update `docs/user-guide-templates.md` with `proactive_memory` and `proactive_memory_active`
template variable descriptions.
