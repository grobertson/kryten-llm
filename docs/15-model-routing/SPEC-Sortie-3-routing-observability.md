# SPEC-Sortie-3: Routing observability

**Sprint**: 15 — Memory-Aware Model Routing
**PRD**: [PRD-model-routing.md](PRD-model-routing.md)
**Status**: Planned
**Estimate**: 2–3h
**Depends on**: Sortie 2 (routing live)
**Requirements**: REQ-320 – REQ-324

---

## 1. Overview

Log and meter every routing decision so operators can observe the signal distribution and
tune thresholds with data. Adds a Prometheus counter + per-tier latency histogram and a
debug log line per turn.

## 2. Scope and Non-Goals

**In scope**: `record_routing_decision(tier, signal)` on `ServiceHealthMonitor`; Prometheus
metric surface; debug log line.

**Non-goals**: A/B comparison; time-series storage; per-provider breakdown (that's Sortie 2's
existing `record_llm_response`).

## 3. Requirements

- **REQ-320** — Per-turn log: `routing: signal=0.72 tier=premium` at DEBUG level (no content).
- **REQ-321** — Prometheus counter `llm_routing_tier_total{tier}` incremented per turn.
- **REQ-322** — Histogram `llm_routing_signal` tracks the signal distribution.
- **REQ-323** — Metrics exported via the existing `/metrics` endpoint.
- **REQ-324** — All metrics default to zero (no routing overhead when not configured).

## 4. Design

```python
def record_routing_decision(self, tier: str, signal: float) -> None:
    self._routing_tier_counts[tier] += 1
    self._routing_signals.append(signal)
```

## 5. Implementation Plan

**Modify**
- `kryten_llm/components/health_monitor.py` — `record_routing_decision`.
- `kryten_llm/service.py` — call after routing decision.
- `kryten_llm/components/metrics_server.py` — expose new metrics.

## 6. Testing Strategy

- `record_routing_decision` increments the correct tier counter.
- Signal appended to the histogram list.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Routing decision logged and metered per turn.
- [ ] Prometheus endpoint exposes `llm_routing_tier_total`.

## 8. Rollout

- Ships with Sortie 2. Metrics visible immediately.

## 9. Documentation

- `CHANGELOG.md` entry.
