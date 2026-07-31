# SPEC-Sortie-3: Compaction Config & Service Integration

**Sprint**: 19 — Semantic Fact Compaction
**PRD**: [PRD-fact-compaction.md](PRD-fact-compaction.md)
**Status**: Planned
**Estimate**: 2h
**Depends on**: Sorties 1–2; Sprint 10 (`service.py` sweeper wiring pattern, Sprint 18
  `ConfidenceDriftConfig` as direct template)
**Requirements**: REQ-395 – REQ-399

---

## 1. Overview

Add `CompactionConfig` to `models/config.py`, add a `compaction` field to `LLMConfig`,
wire `CompactionSweeper` into `service.py` following the `ConfidenceDriftSweeper` pattern,
add `record_memory_facts_compacted` to `HealthMonitor`, and update `config.example.json`.
Default off — zero impact on existing deployments.

---

## 2. Scope and Non-Goals

**In scope**: `CompactionConfig` Pydantic model; `LLMConfig.compaction`; `service.py`
sweeper start/stop; `HealthMonitor.record_memory_facts_compacted`; `config.example.json`.

**Non-goals**: Eval fixture (Sortie 4). CLI changes (Sortie 2 already done).

---

## 3. Requirements

- **REQ-395** — `CompactionConfig` fields: `enabled: bool = False`,
  `interval_hours: float = 24.0`, `min_facts_to_compact: int = 10`,
  `merge_threshold: float = 0.85` (validated `ge=0.5, le=1.0`),
  `importance_cap: int = 10000`.
- **REQ-396** — `LLMConfig` gains `compaction: CompactionConfig = Field(default_factory=CompactionConfig)`.
- **REQ-397** — `service.py._start_sweepers()` (or equivalent) starts `CompactionSweeper`
  when `config.compaction.enabled` is True and a `LongTermMemoryProvider` is found.
  Logs a warning and skips if no provider is found.
- **REQ-398** — `HealthMonitor.record_memory_facts_compacted(n: int = 1)` increments
  `_memory_facts_compacted_total`. Accessible in `/metrics` response.
- **REQ-399** — `config.example.json` includes a `compaction` block with all fields and
  inline comments explaining `merge_threshold` and `min_facts_to_compact`.

---

## 4. Design

### CompactionConfig

```python
class CompactionConfig(BaseModel):
    """Semantic fact compaction sweeper (Sprint 19, REQ-395–399).

    When enabled, a background task periodically merges near-duplicate facts within
    each user's corpus. Default off so existing deployments are unaffected.

    merge_threshold: cosine similarity at or above which two facts are considered
        equivalent and merged. 0.85 = conservative (catches only close paraphrases).
        Lower values merge more aggressively.
    """

    enabled: bool = Field(default=False, description="Enable compaction sweeper (default off)")
    interval_hours: float = Field(default=24.0, ge=0.1, description="Sweep interval in hours")
    min_facts_to_compact: int = Field(
        default=10, ge=2,
        description="Skip users with fewer facts than this (avoids trivial runs)"
    )
    merge_threshold: float = Field(
        default=0.85, ge=0.5, le=1.0,
        description=(
            "Cosine similarity threshold for merging. "
            "0.85 = conservative; dedup_novelty_max corresponds to ~0.92."
        ),
    )
    importance_cap: int = Field(
        default=10000, ge=1,
        description="Upper bound on merged importance (mirrors ScoringConfig.importance_cap)"
    )
```

### service.py wiring

Follows the Sprint 18 `ConfidenceDriftSweeper` pattern exactly:

```python
# Sprint 19: Start compaction sweeper when configured (Sortie 3, REQ-395–399).
if self.config.compaction.enabled:
    from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider
    from kryten_llm.components.memory.retention import CompactionSweeper

    comp_provider = None
    for provider in self._context_pipeline.providers:
        if isinstance(provider, LongTermMemoryProvider):
            comp_provider = provider
            break
    if comp_provider is not None:
        ccfg = self.config.compaction
        self._compaction_sweeper = CompactionSweeper(
            store=comp_provider._store,
            embedder=comp_provider._embedder,
            interval_hours=ccfg.interval_hours,
            min_facts_to_compact=ccfg.min_facts_to_compact,
            merge_threshold=ccfg.merge_threshold,
            importance_cap=ccfg.importance_cap,
            health_monitor=self.health_monitor,
        )
        self._compaction_sweeper.start()
        logger.info("Compaction sweeper started (threshold=%.2f)", ccfg.merge_threshold)
    else:
        logger.warning(
            "Compaction sweeper configured but no LongTermMemoryProvider found; "
            "sweeper not started."
        )
```

Also wire the stop in `service.stop()`:
```python
if hasattr(self, "_compaction_sweeper"):
    await self._compaction_sweeper.stop()
```

### HealthMonitor

```python
# In __init__ (alongside _memory_facts_expired_total):
self._memory_facts_compacted_total: int = 0

def record_memory_facts_compacted(self, n: int = 1) -> None:
    """Record facts merged by the compaction sweeper (Sprint 19, REQ-398)."""
    self._memory_facts_compacted_total += n
```

Include `_memory_facts_compacted_total` in the `/metrics` response (alongside
`_memory_facts_expired_total`).

### config.example.json

```json
"compaction": {
  "enabled": false,
  "interval_hours": 24,
  "min_facts_to_compact": 10,
  "merge_threshold": 0.85,
  "importance_cap": 10000
}
```

---

## 5. Implementation Plan

**Modify** `kryten_llm/models/config.py`:
- Add `CompactionConfig` class (after `ConfidenceDriftConfig` or `RetentionConfig`).
- Add `compaction: CompactionConfig` field to `LLMConfig` (with comment `# Sprint 19`).

**Modify** `kryten_llm/service.py`:
- Start `CompactionSweeper` in `_start_sweepers` (or wherever retention/drift sweepers start).
- Stop it in `stop()`.

**Modify** `kryten_llm/components/health_monitor.py`:
- Add `_memory_facts_compacted_total` counter and `record_memory_facts_compacted` method.
- Include it in the metrics output.

**Modify** `config.example.json`:
- Add `compaction` block.

---

## 6. Testing Strategy

- `CompactionConfig()` default: `enabled=False`, `merge_threshold=0.85`.
- `CompactionConfig(merge_threshold=0.4)` raises `ValidationError` (below 0.5 minimum).
- `config.example.json` parses without error (add to `test_config.py`).
- `HealthMonitor.record_memory_facts_compacted(5)` → `_memory_facts_compacted_total == 5`.
- `service.py` with `compaction.enabled=True` but no LTM provider: logs warning, no crash.

---

## 7. Acceptance Criteria

- [ ] `CompactionConfig` validates with all defaults.
- [ ] `merge_threshold=0.4` raises `ValidationError`.
- [ ] `config.example.json` passes `test_config.py`.
- [ ] `record_memory_facts_compacted(5)` increments counter to 5.
- [ ] `enabled=False` default: no `CompactionSweeper` started.

---

## 8. Rollout

Default `enabled: false`. Operator sets `enabled: true` to activate. No store migration.

---

## 9. Documentation

`config.example.json` `compaction` block with inline comments.
`CHANGELOG.md` entry: `feat: CompactionConfig + service wiring (Sprint 19, Sortie 3, REQ-395–399)`.
