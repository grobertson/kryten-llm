# SPEC-Sortie-3: Config & from_config Wiring

**Sprint**: 21 — Proactive Memory Injection
**PRD**: [PRD-proactive-injection.md](PRD-proactive-injection.md)
**Status**: Planned
**Estimate**: 2h
**Depends on**: Sorties 1–2; Sprint 10/18 (`LLMConfig` pattern for feature flags)
**Requirements**: REQ-435 – REQ-439

---

## 1. Overview

Add `ProactiveConfig` to `models/config.py`, wire it into `LongTermMemoryProvider.from_config`,
and update `config.example.json`. The proactive feature remains default-off. No service.py
changes are needed: the provider is already started by the context pipeline; the proactive
scope is a pure provider-level feature activated through config.

---

## 2. Scope and Non-Goals

**In scope**: `ProactiveConfig` Pydantic model; `LLMConfig.proactive` field
(top-level convenience) OR provider-level config block under `long_term_memory`; wiring in
`LongTermMemoryProvider.from_config`; `config.example.json`.

**Non-goals**: Observability metrics (Sortie 4). Auto-participation trigger engine changes
(deferred to future sprint). No new service.py sweeper wiring needed.

---

## 3. Requirements

- **REQ-435** — Proactive config is a block under the `long_term_memory` provider config
  (alongside `retrieval`, `confidence`, `topical`, etc.) with key `"proactive"`. Fields:
  `enabled: bool = False`, `threshold: float = 0.80`, `min_confidence: float = 0.70`,
  `priority: int = 39`, `fire_on: list[str] = ["mention", "trigger_word", "auto_participation"]`,
  `drives_participation: bool = False`.
- **REQ-436** — `LongTermMemoryProvider.from_config` reads `pcfg.get("proactive", {})`
  and wires the six instance variables: `_proactive_enabled`, `_proactive_threshold`,
  `_proactive_min_confidence`, `_proactive_priority`, `_proactive_fire_on`,
  `_proactive_drives_participation`.
- **REQ-437** — Default: `enabled: false`. Existing deployments without a `proactive` block
  in their config see no behaviour change.
- **REQ-438** — `fire_on` validation: if any entry is not one of
  `["mention", "trigger_word", "auto_participation", "media_change"]`, log a warning at
  startup but do not reject the config (forward-compatible with new trigger types).
- **REQ-439** — `config.example.json` includes a `proactive` block under the
  `long_term_memory` provider config with all fields and inline comments.

---

## 4. Design

### Provider-level config (not a top-level LLMConfig field)

Proactive is scoped to a specific `long_term_memory` provider instance, not to the service
as a whole. It lives under the provider config dict alongside other provider sections
(`retrieval`, `confidence`, `topical`).

```json
{
  "type": "long_term_memory",
  "enabled": true,
  ...
  "proactive": {
    "enabled": false,
    "threshold": 0.80,
    "min_confidence": 0.70,
    "priority": 39,
    "fire_on": ["mention", "trigger_word", "auto_participation"]
  }
}
```

### from_config wiring

```python
# Sprint 21: proactive memory injection (REQ-435–439).
proactive_cfg = pcfg.get("proactive", {})
provider._proactive_enabled = bool(proactive_cfg.get("enabled", False))
provider._proactive_threshold = float(proactive_cfg.get("threshold", 0.80))
provider._proactive_min_confidence = float(proactive_cfg.get("min_confidence", 0.70))
provider._proactive_priority = int(proactive_cfg.get("priority", 39))
_valid_fire_on = {"mention", "trigger_word", "auto_participation", "media_change"}
fire_on_raw = list(proactive_cfg.get("fire_on", ["mention", "trigger_word", "auto_participation"]))
unknown = [t for t in fire_on_raw if t not in _valid_fire_on]
if unknown:
    logger.warning("proactive.fire_on: unknown trigger types %s (ignored warning, not error)", unknown)
provider._proactive_fire_on = set(fire_on_raw)
provider._proactive_drives_participation = bool(proactive_cfg.get("drives_participation", False))
```

### config.example.json

Under the `long_term_memory` provider block:
```json
"proactive": {
  "enabled": false,
  "threshold": 0.80,
  "min_confidence": 0.70,
  "priority": 39,
  "fire_on": ["mention", "trigger_word", "auto_participation"],
  "drives_participation": false
}
```

---

## 5. Implementation Plan

**Modify** `kryten_llm/components/context/providers/long_term_memory.py`:
- In `from_config`: add proactive wiring block (7 lines, analogous to confidence wiring).

**Modify** `config.example.json`:
- Add `proactive` block under `long_term_memory` provider config.

*Note*: No changes to `kryten_llm/models/config.py` are required — proactive config is
parsed as a raw dict from the provider config (same as `topical`, `room_awareness`, etc.),
consistent with the existing pattern for sub-configs in `long_term_memory`. A typed Pydantic
`ProactiveConfig` model can be added later as a code-quality improvement if desired.

---

## 6. Testing Strategy

- `from_config` with `"proactive": {"enabled": true, "threshold": 0.75}`:
  `provider._proactive_enabled == True`, `provider._proactive_threshold == 0.75`.
- `from_config` without a `proactive` block: `provider._proactive_enabled == False`
  (all defaults); no error.
- Unknown `fire_on` entry: warning logged; entry still included in `_proactive_fire_on`.
- `config.example.json` parses without error.

---

## 7. Acceptance Criteria

- [ ] `from_config` with explicit proactive config wires all 5 fields correctly.
- [ ] `from_config` without proactive block: defaults apply, no exception.
- [ ] Unknown `fire_on` entry: logged as warning; not raised.
- [ ] `config.example.json` passes `test_config.py`.
- [ ] Integration: provider built from config with `enabled: true` emits `proactive_memory`
  fragment when conditions are met.

---

## 8. Rollout

Default `enabled: false`. Operator enables via:
```json
"proactive": {"enabled": true, "threshold": 0.85, "min_confidence": 0.70}
```
No service restart required beyond normal config reload.

---

## 9. Documentation

`CHANGELOG.md` entry.
`config.example.json` proactive block with inline comments:
- `threshold`: "Cosine similarity required to fire. Start at 0.85 and tune down."
- `min_confidence`: "Minimum fact confidence gate. Requires Sprint 18 calibration."
