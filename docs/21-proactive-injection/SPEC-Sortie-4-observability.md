# SPEC-Sortie-4: Observability — Metrics & Debug Logging

**Sprint**: 21 — Proactive Memory Injection
**PRD**: [PRD-proactive-injection.md](PRD-proactive-injection.md)
**Status**: Planned
**Estimate**: 1–2h
**Depends on**: Sorties 1–3 (proactive scope, template, config all in place)
**Requirements**: REQ-440 – REQ-444

---

## 1. Overview

Add proactive injection observability to `HealthMonitor`: a counter for injection events
(labelled by whether the injection was triggered) and a similarity value ring buffer for
average/p95 tracking. Add a debug log line per turn when proactive is enabled. Expose
Prometheus metrics for `llm_proactive_injections_total` and
`llm_proactive_similarity_avg`.

---

## 2. Scope and Non-Goals

**In scope**: `HealthMonitor.record_proactive_injection(triggered, similarity)`;
`_memory_proactive_injections_*` counters/ring; Prometheus metric exposure; debug log
in `_run_proactive_scope`; unit tests.

**Non-goals**: Auto-participation reason logging (deferred). No new Prometheus metrics
server changes — only new counters added to the existing `/metrics` response.

---

## 3. Requirements

- **REQ-440** — `HealthMonitor.record_proactive_injection(triggered: bool, similarity: float)`
  increments `_proactive_injections_triggered` (when `triggered=True`) or
  `_proactive_injections_skipped` (when `triggered=False`), and appends `similarity`
  to a ring buffer `_proactive_similarities` (maxlen=256).
- **REQ-441** — `_run_proactive_scope` calls `self._monitor.record_proactive_injection`
  at every decision point:
  - `triggered=True` when a `proactive_memory` fragment is emitted.
  - `triggered=False` when either gate (similarity or confidence) fails (one call per turn,
    not one per gate failure).
- **REQ-442** — Debug log in `_run_proactive_scope` on every decision when
  `logger.isEnabledFor(logging.DEBUG)`:
  ```
  proactive: user=X sim=0.812 threshold=0.800 conf=0.750 min_conf=0.700 triggered=True fact="..."
  ```
  Text truncated to 60 characters. Log even when not triggered (to aid tuning).
- **REQ-443** — Prometheus `/metrics` response includes:
  - `llm_proactive_injections_total{triggered="true"}` and `{triggered="false"}`.
  - `llm_proactive_similarity_avg` (mean of `_proactive_similarities` ring; 0.0 when empty).
- **REQ-444** — `record_proactive_injection` is a no-op when `monitor` is None (the
  provider operates with `health_monitor=None` in tests; this must not raise).

---

## 4. Design

### HealthMonitor additions

```python
# In __init__ (alongside _memory_facts_compacted_total etc.):
self._proactive_injections_triggered: int = 0
self._proactive_injections_skipped: int = 0
self._proactive_similarities: deque[float] = deque(maxlen=256)

def record_proactive_injection(self, triggered: bool, similarity: float) -> None:
    """Record a proactive injection decision (Sprint 21, REQ-440).

    triggered=True when the proactive_memory fragment was emitted;
    triggered=False when a gate (similarity or confidence) blocked it.
    """
    if triggered:
        self._proactive_injections_triggered += 1
    else:
        self._proactive_injections_skipped += 1
    self._proactive_similarities.append(similarity)
```

### `_run_proactive_scope` additions

```python
def _run_proactive_scope(
    self,
    req: "ContextRequest",
    raw_results: list[dict],
) -> list["ContextFragment"]:
    if not self._proactive_enabled or not raw_results:
        return []
    trigger_type = str((req.trigger or {}).get("type", ""))
    if trigger_type not in self._proactive_fire_on:
        return []
    top = raw_results[0]
    sim = max(0.0, 1.0 - float(top.get("distance", 1.0)))
    conf = float(top.get("metadata", {}).get("confidence", 0.0))
    triggered = sim >= self._proactive_threshold and conf >= self._proactive_min_confidence
    doc = str(top.get("document", "")) if triggered else ""

    # REQ-442: debug log every decision
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "proactive: user=%s sim=%.3f threshold=%.2f conf=%.3f min_conf=%.2f "
            "triggered=%s fact=%r",
            req.username, sim, self._proactive_threshold,
            conf, self._proactive_min_confidence,
            triggered, doc[:60],
        )

    # REQ-441: record decision
    if self._monitor is not None:
        self._monitor.record_proactive_injection(triggered=triggered, similarity=sim)

    if not triggered or not doc:
        return []
    return [ContextFragment(
        name="proactive_memory",
        priority=self._proactive_priority,
        text=doc,
        est_chars=len(doc),
        confidence=conf,
    )]
```

This consolidates the gate logic and reduces code duplication vs. the Sortie 1 design.

### Prometheus /metrics

In the metrics response builder (wherever `llm_memory_facts_expired_total` is emitted),
add:
```python
f"llm_proactive_injections_total{{triggered=\"true\"}} {self._proactive_injections_triggered}\n"
f"llm_proactive_injections_total{{triggered=\"false\"}} {self._proactive_injections_skipped}\n"
f"llm_proactive_similarity_avg "
f"{(sum(self._proactive_similarities) / len(self._proactive_similarities)) if self._proactive_similarities else 0.0:.4f}\n"
```

---

## 5. Implementation Plan

**Modify** `kryten_llm/components/health_monitor.py`:
- Add `_proactive_injections_triggered`, `_proactive_injections_skipped`,
  `_proactive_similarities` in `__init__`.
- Add `record_proactive_injection` method.
- Add metrics to the `/metrics` response builder.

**Modify** `kryten_llm/components/context/providers/long_term_memory.py`:
- Update `_run_proactive_scope` to include the log line and `record_proactive_injection`
  call (refining Sortie 1's implementation).

---

## 6. Testing Strategy

- `record_proactive_injection(triggered=True, similarity=0.85)`:
  `_triggered == 1`, `_skipped == 0`, `_similarities == [0.85]`.
- `record_proactive_injection(triggered=False, similarity=0.72)`:
  `_triggered == 0`, `_skipped == 1`, `_similarities == [0.72]`.
- `monitor=None` in `_run_proactive_scope`: no `AttributeError` (REQ-444).
- Debug log: with `logger.DEBUG` enabled, log line is emitted on every proactive decision.
- `/metrics` response: contains both `llm_proactive_injections_total` lines.
- `llm_proactive_similarity_avg` = 0.0 when ring is empty.

---

## 7. Acceptance Criteria

- [ ] `record_proactive_injection(True, 0.85)` increments triggered counter.
- [ ] `record_proactive_injection(False, 0.72)` increments skipped counter.
- [ ] `monitor=None`: no error in `_run_proactive_scope`.
- [ ] Debug log emitted at every proactive decision (when DEBUG level).
- [ ] `/metrics` includes both `llm_proactive_injections_total` gauge lines.
- [ ] `llm_proactive_similarity_avg` = 0.0 on empty ring.

---

## 8. Rollout

Default-off (`proactive.enabled = false`): counters remain 0, no log lines. Metrics
exposure is additive and harmless when all counters are 0.

---

## 9. Documentation

`CHANGELOG.md` entry: `feat: proactive injection observability (Sprint 21, Sortie 4, REQ-440–444)`.
Update `docs/DEPLOYMENT.md` with the new Prometheus metric names and their interpretation
(high `skipped` count → threshold too high; high `triggered` count → tune threshold up if
response quality is poor).
