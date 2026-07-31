# SPEC-Sortie-2: Expose Proactive Injection Metrics on `/metrics`

**Sprint**: 22 — Release Prep / Gap Removal
**PRD**: [PRD-release-prep.md](PRD-release-prep.md)
**Status**: Planned
**Estimate**: 1h
**Depends on**: Sortie 1 (confirms counter hygiene pattern); Sprint 21 (`record_proactive_injection`, `_proactive_injections_triggered/skipped`, `_proactive_similarities`)
**Requirements**: REQ-466 – REQ-470

---

## 1. Overview

Sprint 21 Sortie 4 (REQ-440–444) specified that `llm_proactive_injections_total` and
`llm_proactive_similarity_avg` must appear on `/metrics`. The health_monitor counters
and ring buffer were implemented correctly; only the metrics-server emission step was
missed. This sortie adds the two missing Prometheus blocks to `_emit_memory_metrics`.

---

## 2. Scope and Non-Goals

**In scope**: `_emit_memory_metrics` extension; unit test asserting the metric lines are
present in the `/metrics` response when counters are non-zero.

**Non-goals**: Compaction metrics (Sortie 1). `drives_participation` wiring (Sortie 3).
No changes to `health_monitor.py` — the counters and ring buffer already exist.

---

## 3. Requirements

- **REQ-466** — `_emit_memory_metrics` emits a `llm_proactive_injections_total` counter
  with a `triggered` label:
  ```
  # HELP llm_proactive_injections_total Proactive injection decisions by outcome
  # TYPE llm_proactive_injections_total counter
  llm_proactive_injections_total{triggered="true"} <N>
  llm_proactive_injections_total{triggered="false"} <N>
  ```
- **REQ-467** — `_emit_memory_metrics` emits a `llm_proactive_similarity_avg` gauge:
  ```
  # HELP llm_proactive_similarity_avg Rolling mean cosine similarity at proactive decision point
  # TYPE llm_proactive_similarity_avg gauge
  llm_proactive_similarity_avg <F>
  ```
  Value is the mean of `hm._proactive_similarities`; 0.0 when the ring is empty.
- **REQ-468** — Both blocks are placed together at the end of `_emit_memory_metrics`,
  after the retrieval latency block. No interleaving with unrelated metrics.
- **REQ-469** — When `_proactive_injections_triggered == 0` and `_proactive_injections_skipped == 0`
  (proactive is disabled or no turns have occurred), both counter lines emit `0` and
  `llm_proactive_similarity_avg` emits `0.0`. Never omit lines based on value.
- **REQ-470** — New test verifies the Prometheus lines appear in the raw `/metrics` output:
  call `_collect_custom_metrics()` with a stubbed `app` whose health_monitor has
  known counter values, and assert the expected label lines are present.

---

## 4. Design

### metrics_server.py — `_emit_memory_metrics` addition

Append to the end of the method (after the retrieval latency block):

```python
# Sprint 21: proactive injection metrics (REQ-466–469)
lines.append(
    "# HELP llm_proactive_injections_total Proactive injection decisions by outcome"
)
lines.append("# TYPE llm_proactive_injections_total counter")
lines.append(
    f'llm_proactive_injections_total{{triggered="true"}} {hm._proactive_injections_triggered}'
)
lines.append(
    f'llm_proactive_injections_total{{triggered="false"}} {hm._proactive_injections_skipped}'
)
lines.append("")

proactive_samples = list(hm._proactive_similarities)
proactive_avg = sum(proactive_samples) / len(proactive_samples) if proactive_samples else 0.0
lines.append(
    "# HELP llm_proactive_similarity_avg "
    "Rolling mean cosine similarity at proactive decision point"
)
lines.append("# TYPE llm_proactive_similarity_avg gauge")
lines.append(f"llm_proactive_similarity_avg {proactive_avg:.4f}")
lines.append("")
```

---

## 5. Tests

Add to `tests/test_proactive_injection.py` or a new metrics test file:

```python
def test_proactive_metrics_emitted():
    """_emit_memory_metrics must expose proactive counters (REQ-466–469)."""
    import logging
    from kryten_llm.models.config import ServiceMetadata
    from kryten_llm.components.health_monitor import ServiceHealthMonitor
    from kryten_llm.components.metrics_server import MetricsServer
    import types

    hm = ServiceHealthMonitor(ServiceMetadata(), logging.getLogger("test"))
    hm.record_proactive_injection(triggered=True, similarity=0.85)
    hm.record_proactive_injection(triggered=False, similarity=0.60)

    # Minimal app stub
    app = types.SimpleNamespace(
        health_monitor=hm,
        client=None,
        rate_limiter=None,
    )
    server = MetricsServer.__new__(MetricsServer)
    server.app = app

    lines: list[str] = []
    server._emit_memory_metrics(lines, hm)
    combined = "\n".join(lines)

    assert 'llm_proactive_injections_total{triggered="true"} 1' in combined
    assert 'llm_proactive_injections_total{triggered="false"} 1' in combined
    assert "llm_proactive_similarity_avg" in combined
```
