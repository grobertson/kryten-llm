# SPEC-Sortie-5: Memory observability

**Sprint**: 9 — Memory Quality & Observability
**PRD**: [PRD-memory-quality.md](PRD-memory-quality.md)
**Status**: Planned
**Estimate**: 3–4h
**Depends on**: Sprint 8 (fragments to observe); `health_monitor` / `metrics_server`
**Requirements**: REQ-160 – REQ-169
**Recommended first** — enable before the other Sprint 9 sorties so their impact is measurable.

---

## 1. Overview

Add memory-specific telemetry so operators can see what the memory system injects, how often
each fragment type fires, how the shadow-mute gate behaves, and how long retrieval takes.
Optionally, a per-turn *fragment trace* (behind a debug flag) records which facts were
injected — for tuning, never on by default.

## 2. Scope and Non-Goals

**In scope**: Prometheus counters/latency for memory fragments and the gate; optional debug
fragment trace with privacy safeguards.

**Non-goals**: dashboards/alerts (ops concern); logging fact contents at default levels.

## 3. Requirements

- **REQ-160** — Counter per fragment type emitted (`user_memory`, `topical_memory`,
  `room_memory`, `ambient_memory`, `callback_memory`, `memory_signal`).
- **REQ-161** — Counter for moderation-gate fail-closed events and silenced-user exclusions.
- **REQ-162** — Retrieval latency metric (histogram or summary) for the provider read path.
- **REQ-163** — Counter for presence-source fallbacks (Sortie 2) and pooling strategy in use.
- **REQ-164** — Optional per-turn fragment trace behind `trace.enabled` (default false).
- **REQ-165** — Default log/metric levels expose **no** fact contents or usernames; the
  content trace requires the explicit debug flag and honors the shadow-mute/privacy posture.
- **REQ-166** — Metrics integrate with the existing `metrics_server` exposition (no new port).

## 4. Design

Extend `health_monitor` with memory counters and a latency accumulator, exposed by
`metrics_server` alongside existing `llm_*` metrics:

```
llm_memory_fragment_emitted_total{type="topical_memory"}   N
llm_memory_gate_fail_closed_total                          N
llm_memory_silenced_excluded_total                         N
llm_memory_presence_fallback_total                         N
llm_memory_retrieval_seconds{quantile="0.95"}             ...
```

Optional trace: when `trace.enabled`, append a structured debug log line per turn listing
fragment names, fact ids, and scores (ids/scores, **not** raw content unless a separate
`trace.include_content` is set — off by default and privacy-flagged).

## 5. Implementation Plan

**Modify**
- `components/health_monitor.py` — memory counters + latency accumulator.
- `components/metrics_server.py` — expose the new series.
- `long_term_memory.py` — increment counters at fragment emission / gate / fallback points;
  optional trace hook.
- `models/config.py` — `trace` block (`enabled`, `include_content`).
- `config.example.json` — `trace` additions.

## 6. Testing Strategy

- Emitting a topical fragment increments the right counter.
- Gate fail-closed increments its counter.
- Latency metric records a value on the read path.
- `trace.enabled=false` produces no trace line; default trace never contains fact content.
- Metrics appear in the `metrics_server` output.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] All new counters/latency visible via the existing metrics endpoint.
- [ ] No fact content or username in default metrics/logs.
- [ ] Debug trace gated and privacy-safe.

## 8. Rollout

- Enable first in Sprint 9 so subsequent sorties are measurable.
- Keep `trace` off in production except for short tuning windows.

## 9. Documentation

- `docs/DEPLOYMENT.md` / monitoring docs: new metric names and meanings.
- `config.example.json` comments for `trace`.
- `CHANGELOG.md` entry.
