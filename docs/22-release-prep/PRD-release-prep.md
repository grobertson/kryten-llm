# PRD: Release Prep / Gap Removal

**Sprint**: 22 — `22-release-prep`
**Status**: Next (N+1) — Sorties 1–4 ready; implement after Sprint 21
**Builds on**: Sprints 19–21 (compaction, temporal awareness, proactive injection)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)
**REQs**: REQ-461 – REQ-480

---

## 1. Executive Summary

Sprints 19–21 delivered all planned features and all 83 sprint tests pass. A post-implementation
audit identified three gaps that must be closed before the `[Unreleased]` block is versioned
and shipped: a mis-wired health-monitor counter, two sets of Prometheus metrics that are
tracked in memory but never served, and a config flag (`drives_participation`) that is read,
stored, and documented but never acted on. Sprint 22 closes all three gaps and gates the
release with a full test run, version bump, and CHANGELOG finalisation.

---

## 2. Problem Statement

### 2.1 `record_memory_facts_compacted` routes to the wrong counter

`ServiceHealthMonitor.record_memory_facts_compacted(n)` (`health_monitor.py`) adds `n` to
`_memory_facts_expired_total` instead of a dedicated `_memory_facts_compacted_total`.
This conflates compaction merges with retention deletions. The error is latent now because
neither counter is exposed on `/metrics`, but as soon as the metrics are surfaced the wrong
gauge will be reported.

### 2.2 Sprint 19 and 21 metrics are tracked but never served

`_emit_memory_metrics` in `metrics_server.py` does not emit:
- Sprint 19 compaction facts counter (REQ-398 required it).
- Sprint 21 `llm_proactive_injections_total` counter or `llm_proactive_similarity_avg` gauge
  (REQ-443 required both).

Operators cannot observe compaction sweeper activity or proactive injection rates from
Prometheus, making both features unmonitorable in production.

### 2.3 `drives_participation` is a silent no-op

`_proactive_drives_participation` is read from config, stored on `LongTermMemoryProvider`,
and documented in `config.example.json`. No code path reads it. An operator who sets
`proactive.drives_participation: true` expecting the bot to speak on strong proactive
matches during auto-participation turns will see no effect.

### 2.4 No versioned release since `[0.9.4]`

Sprints 18–21 added significant features. The `[Unreleased]` CHANGELOG block needs to be
versioned (`0.10.0` — minor bump for the combined feature set) and a release tag cut.

---

## 3. Goals and Success Metrics

| Metric | Target |
|--------|--------|
| `_memory_facts_compacted_total` is a separate counter from `_memory_facts_expired_total` | Pass |
| `/metrics` emits `llm_memory_facts_compacted_total` | Pass |
| `/metrics` emits `llm_proactive_injections_total{triggered}` and `llm_proactive_similarity_avg` | Pass |
| Bot speaks on a turn gated by `drives_participation=true` when `proactive_memory_active` is set | Pass |
| Bot stays silent when `drives_participation=false` (default) regardless of proactive match | Pass |
| All existing tests pass | Pass |
| `pyproject.toml` version = `0.10.0` | Pass |
| CHANGELOG `[Unreleased]` block renamed to `[0.10.0] - 2026-07-31` | Pass |

---

## 4. User Stories

- *As an operator*, I want `llm_memory_facts_compacted_total` to count compacted facts, not
  inflate the expired-facts gauge, so my dashboards are accurate.
- *As an operator*, I want Prometheus metrics for compaction and proactive injection so I can
  monitor both features without reading log files.
- *As a community member*, I want `drives_participation: true` to cause the bot to interject
  when it recalls something highly relevant, even if it wouldn't otherwise have spoken.
- *As a maintainer*, I want a clean versioned release after Sprints 18–21 so I can ship
  the feature set and let downstream consumers (api-gate, webqueue) reference a stable version.

---

## 5. Technical Architecture

### 5.1 Counter fix (`_memory_facts_compacted_total`)

Add `self._memory_facts_compacted_total: int = 0` to `ServiceHealthMonitor.__init__`.
Change `record_memory_facts_compacted` to increment it instead of `_memory_facts_expired_total`.
Expose as `llm_memory_facts_compacted_total` in `_emit_memory_metrics`.

### 5.2 Metrics exposure (Sortie 1 + 2 combined)

Extend `_emit_memory_metrics` in `metrics_server.py`:
```python
# Sprint 19: compaction
lines.append("# HELP llm_memory_facts_compacted_total Facts merged by CompactionSweeper")
lines.append("# TYPE llm_memory_facts_compacted_total counter")
lines.append(f"llm_memory_facts_compacted_total {hm._memory_facts_compacted_total}")
lines.append("")

# Sprint 21: proactive injection
lines.append("# HELP llm_proactive_injections_total Proactive injection decisions by outcome")
lines.append("# TYPE llm_proactive_injections_total counter")
lines.append(f'llm_proactive_injections_total{{triggered="true"}} {hm._proactive_injections_triggered}')
lines.append(f'llm_proactive_injections_total{{triggered="false"}} {hm._proactive_injections_skipped}')
lines.append("")

samples = list(hm._proactive_similarities)
avg = sum(samples) / len(samples) if samples else 0.0
lines.append("# HELP llm_proactive_similarity_avg Rolling mean cosine similarity at proactive check")
lines.append("# TYPE llm_proactive_similarity_avg gauge")
lines.append(f"llm_proactive_similarity_avg {avg:.4f}")
lines.append("")
```

### 5.3 `drives_participation` wiring (Sortie 3)

The cleanest integration point is `service.py`'s auto-participation flow, after
`pipeline.build()` returns the context dict. The `proactive_memory_active` key is already
written by `LongTermMemoryProvider` into the fragment `data` dict and is therefore available
in the merged context. The `drives_participation` setting is similarly written into the
context data as `proactive_drives_participation` (added to the provider's `data` dict in
`_run_speaker_scope` / `_run_proactive_scope`). `service.py` then reads both flags:

```python
# After the eagerness gate fails on an auto_participation turn:
if (
    ctx.get("proactive_memory_active")
    and ctx.get("proactive_drives_participation")
    and trigger_type == "auto_participation"
):
    # Override: proactive match is strong enough to drive a response.
    should_speak = True
```

This keeps service.py free of direct imports from the LTM provider module.

### 5.4 Release gate (Sortie 4)

- Bump `version` in `pyproject.toml` from `0.9.4` → `0.10.0`.
- Rename `## [Unreleased]` in `CHANGELOG.md` to `## [0.10.0] - 2026-07-31` and add a new
  empty `## [Unreleased]` header above it.
- Run `uv run black .`, `uv run ruff check --fix .`, `uv run mypy kryten_llm`,
  `uv run pytest` — all must pass clean.
- Tag `v0.10.0`.

---

## 6. Dependencies

- Sprint 19 (compaction) — `_memory_facts_compacted_total` and metrics exposure require
  the compaction sweeper already in place. ✅ Done.
- Sprint 21 (proactive injection) — counter and `drives_participation` wiring require
  `_proactive_injections_triggered/skipped` on health_monitor and `_proactive_drives_participation`
  on the provider. ✅ Both in place.
- No new external library dependencies.

---

## 7. Security and Privacy

No new data surfaces, no new config that handles user data. The `drives_participation` flag
controls response generation gating only — it does not alter what data is stored or retrieved.
Metric labels carry no user-identifying information.

---

## 8. Rollout Plan

All four sorties are additive and backward-compatible. No config migration required; no
service restart required between sorties. The release gate (Sortie 4) cuts `v0.10.0`.

---

## 9. Future Enhancements

- Sprint 23+: Per-user `drives_participation` override via `memory_commands` so power users
  can opt in/out without touching service config.
- Rate-limit the `drives_participation` override (e.g. once per N turns) to prevent the
  proactive path from dominating auto-participation entirely.

---

## 10. Open Questions

None. All three gaps are well-understood and the fixes are straightforward.
