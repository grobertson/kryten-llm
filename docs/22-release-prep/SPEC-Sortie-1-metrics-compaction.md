# SPEC-Sortie-1: Fix `record_memory_facts_compacted` & Expose Compaction Metrics

**Sprint**: 22 — Release Prep / Gap Removal
**PRD**: [PRD-release-prep.md](PRD-release-prep.md)
**Status**: Planned
**Estimate**: 1h
**Depends on**: Sprint 19 (`CompactionSweeper`, `record_memory_facts_compacted`)
**Requirements**: REQ-461 – REQ-465

---

## 1. Overview

`ServiceHealthMonitor.record_memory_facts_compacted` currently increments
`_memory_facts_expired_total` — the wrong counter. This sortie adds a dedicated
`_memory_facts_compacted_total` counter, corrects the method, and exposes it on
`/metrics` as `llm_memory_facts_compacted_total`. This is the only metrics change in
this sortie; Sprint 21 proactive metrics are handled in Sortie 2.

---

## 2. Scope and Non-Goals

**In scope**: `ServiceHealthMonitor.__init__` counter addition; `record_memory_facts_compacted`
fix; `_emit_memory_metrics` extension; unit test for the new counter and Prometheus line.

**Non-goals**: Proactive injection metrics (Sortie 2). `drives_participation` wiring (Sortie 3).
No changes to `CompactionSweeper` or `service.py`.

---

## 3. Requirements

- **REQ-461** — Add `self._memory_facts_compacted_total: int = 0` to
  `ServiceHealthMonitor.__init__` (alongside `_memory_facts_expired_total`). The two
  counters must be independent.
- **REQ-462** — `record_memory_facts_compacted(n)` increments `_memory_facts_compacted_total`
  (not `_memory_facts_expired_total`). Guard: `if n > 0` (unchanged behaviour).
- **REQ-463** — `_emit_memory_metrics` in `metrics_server.py` emits:
  ```
  # HELP llm_memory_facts_compacted_total Facts merged/deleted by CompactionSweeper
  # TYPE llm_memory_facts_compacted_total counter
  llm_memory_facts_compacted_total <N>
  ```
  Placed after `llm_memory_facts_expired_total` (if exposed) or after the existing
  retrieval latency block. Counter = 0 when the sweeper has never run or is disabled.
- **REQ-464** — No existing test is broken. The `_memory_facts_expired_total` counter
  is unchanged in value for all existing call paths (only `record_memory_facts_expired`
  touches it going forward).
- **REQ-465** — New unit test in `tests/test_compaction.py` (or a new
  `tests/test_health_monitor_sprint22.py`): verifies that after calling
  `record_memory_facts_compacted(5)`, `_memory_facts_compacted_total == 5` and
  `_memory_facts_expired_total == 0`.

---

## 4. Design

### health_monitor.py

```python
# In __init__, after _memory_facts_expired_total:
self._memory_facts_compacted_total: int = 0  # REQ-461

# record_memory_facts_compacted — corrected:
def record_memory_facts_compacted(self, n: int = 1) -> None:
    """Record *n* facts merged/deleted by the compaction sweeper (Sprint 19, REQ-398)."""
    if n > 0:
        self._memory_facts_compacted_total += n  # REQ-462 (was: _memory_facts_expired_total)
```

### metrics_server.py — `_emit_memory_metrics`

Add after the existing `llm_memory_presence_fallback_total` block (or after the retrieval
latency block — keep the section coherent):

```python
lines.append("# HELP llm_memory_facts_compacted_total Facts merged/deleted by CompactionSweeper")
lines.append("# TYPE llm_memory_facts_compacted_total counter")
lines.append(f"llm_memory_facts_compacted_total {hm._memory_facts_compacted_total}")
lines.append("")
```

---

## 5. Tests

`tests/test_compaction.py` (or a new file) — add:

```python
def test_compaction_counter_is_separate_from_expired():
    from kryten_llm.models.config import ServiceMetadata
    import logging
    hm = ServiceHealthMonitor(ServiceMetadata(), logging.getLogger("test"))
    hm.record_memory_facts_compacted(5)
    assert hm._memory_facts_compacted_total == 5
    assert hm._memory_facts_expired_total == 0

def test_expired_counter_unaffected_by_compaction():
    from kryten_llm.models.config import ServiceMetadata
    import logging
    hm = ServiceHealthMonitor(ServiceMetadata(), logging.getLogger("test"))
    hm.record_memory_facts_expired(3)
    hm.record_memory_facts_compacted(2)
    assert hm._memory_facts_expired_total == 3
    assert hm._memory_facts_compacted_total == 2
```
