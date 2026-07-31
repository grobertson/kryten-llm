# SPEC-Sortie-3: Store-Mode Observability

**Sprint**: 17 — Multi-Instance Shared Memory
**PRD**: [PRD-cross-channel.md](PRD-cross-channel.md)
**Status**: Planned
**Estimate**: 1–2h
**Depends on**: Sortie 2 (deployment guide describes what the metric represents)
**Requirements**: REQ-345

---

## 1. Overview

Add a `store_mode` property to each `VectorStore` backend and expose it on the `/metrics`
endpoint as `llm_memory_store_mode{mode="..."}`. Allows operators to confirm at a glance
that both bot instances are running in HTTP/pgvector mode rather than embedded Chroma.

## 2. Scope and Non-Goals

**In scope**: `store_mode` property on `ChromaVectorStore` and `PgVectorStore`; metric in
`MetricsServer`; test.

**Non-goals**: Alerting rules. Grafana dashboard. Storing mode in health monitor state
(it's derivable from the store object directly).

## 3. Requirements

- **REQ-345** — `llm_memory_store_mode{mode="<backend>"}` gauge exported on `/metrics`
  where `<backend>` is one of `chroma-embedded`, `chroma-http`, `pgvector`, or `fake`.

## 4. Design

```python
# ChromaVectorStore
@property
def store_mode(self) -> str:
    return "chroma-http" if self._http_host else "chroma-embedded"

# PgVectorStore
@property
def store_mode(self) -> str:
    return "pgvector"
```

In `MetricsServer._emit_component_metrics`:
```python
# Walk context pipeline for the first LTM provider; read its store mode.
if self.app._context_pipeline is not None:
    for provider in self.app._context_pipeline.providers:
        if isinstance(provider, LongTermMemoryProvider):
            mode = getattr(provider._store, "store_mode", "unknown")
            lines.append("# HELP llm_memory_store_mode Active memory store backend")
            lines.append("# TYPE llm_memory_store_mode gauge")
            lines.append(f'llm_memory_store_mode{{mode="{mode}"}} 1')
            break
```

## 5. Implementation Plan

**Modify**
- `kryten_llm/components/memory/vector_store.py` — `store_mode` property on
  `ChromaVectorStore` and `PgVectorStore`.
- `kryten_llm/components/metrics_server.py` — `_emit_component_metrics` addition.
- `tests/eval/harness.py` — `store_mode = "fake"` property on `FakeStore`.

## 6. Testing Strategy

Add to `tests/test_multi_instance.py`:
- `test_store_mode_chroma_embedded` — `ChromaVectorStore(path=...)._http_host == ""` → mode
  is `"chroma-embedded"`.
- `test_store_mode_chroma_http` — `ChromaVectorStore(http_host="localhost", ...)` → mode
  is `"chroma-http"`.
- `test_store_mode_fake` — `FakeStore().store_mode == "fake"`.
- `test_metrics_emit_store_mode` — `_emit_store_mode_metric` produces
  `llm_memory_store_mode` line.

## 7. Acceptance Criteria

- [ ] `store_mode` property exists on both Chroma and pgvector backends.
- [ ] `FakeStore` has `store_mode = "fake"`.
- [ ] `/metrics` output contains `llm_memory_store_mode{mode="..."}`.
- [ ] All new tests pass.

## 8. Rollout

Additive metric; no breaking change. Ships with Sortie 2.

## 9. Documentation

`CHANGELOG.md` entry.
