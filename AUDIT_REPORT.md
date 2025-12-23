# Audit Report: kryten-llm

**Target:** `d:\Devel\kryten-llm`
**Reference:** `kryten-py` Documentation (v0.1.0)
**Date:** 2025-12-23

## Executive Summary

The `kryten-llm` service exhibits critical API mismatches with the `kryten-py` library, particularly in KeyValue store interactions. It attempts to call methods on `KrytenClient` that do not exist. Additionally, there are anti-patterns in subject construction and redundant component implementations that should be refactored to leverage `kryten-py` features.

## Critical Violations (Breaking Changes)

### 1. Non-Existent KV Store Methods
**Severity:** 🔴 **CRITICAL**
**Location:**
- `kryten_llm/components/trigger_engine.py`: Lines 316, 322, 349
- `kryten_llm/components/context_manager.py`: Line 76

**Issue:**
The code calls `client.get_kv_bucket()`, `client.kv_get()`, and `client.kv_put()`. These methods **do not exist** on the `KrytenClient` class in `kryten-py`.

**Remediation:**
Import helper functions from `kryten.kv_store` and pass the underlying NATS connection.

```python
# Current (Broken)
bucket = await client.get_kv_bucket("name")
val = await client.kv_get(bucket, "key")

# Recommended
from kryten.kv_store import get_or_create_kv_store, kv_get
bucket = await get_or_create_kv_store(client._nats, "name", logger=logger)
val = await kv_get(bucket, "key", logger=logger)
```

## Anti-Patterns & Best Practices

### 2. Manual Subject Construction
**Severity:** 🟡 **MEDIUM**
**Location:** `kryten_llm/components/context_manager.py`: Line 128

**Issue:**
Manually constructing NATS subjects (`f"kryten.events.cytube.{channel}.changemedia"`) bypasses the library's normalization logic (handling dots, casing, etc.).

**Remediation:**
Use `kryten.subject_builder` or the `client.on()` decorator which handles this automatically.

```python
# Recommended
from kryten.subject_builder import build_event_subject
subject = build_event_subject(channel=channel, event_name="changemedia")
```

### 3. Redundant Metrics Server
**Severity:** 🟢 **LOW**
**Location:** `kryten_llm/components/metrics_server.py`

**Issue:**
`kryten-llm` implements its own `aiohttp` metrics server. `kryten-py`'s `LifecycleEventPublisher` already provides hooks for health/metrics endpoints.

**Remediation:**
Ensure port configurations do not conflict. Ideally, consolidate to use the lifecycle publisher's metadata to announce the existing metrics endpoint, which `kryten-llm` appears to be doing correctly via `CommandHandler`.

### 4. Duplicate Event Subscriptions
**Severity:** 🟡 **MEDIUM**
**Location:**
- `service.py`: Subscribes to `changemedia` (Line 93)
- `context_manager.py`: Subscribes to `changemedia` (Line 130)

**Issue:**
The service subscribes to the same event in two places using different methods (`@on` decorator vs manual `subscribe`). This causes double-processing overhead.

**Remediation:**
Consolidate handlers. `ContextManager` logic should be invoked from the main `service.py` handler or registered as a second handler using the standard `@on` decorator.

### 5. Configuration Instantiation
**Severity:** 🟢 **LOW**
**Location:** `service.py`: Line 43

**Issue:**
`KrytenClient` is initialized with a dictionary (`config.model_dump()`).

**Remediation:**
Initialize `KrytenClient` with a `KrytenConfig` object directly for better type safety and validation.

```python
# Recommended
from kryten import KrytenConfig
client_config = KrytenConfig(**self.config.model_dump())
self.client = KrytenClient(client_config)
```

## Action Plan

1.  **Refactor KV Store Access:** Immediately fix `TriggerEngine` and `ContextManager` to use `kryten.kv_store` functions.
2.  **Standardize Subscriptions:** Remove manual `subscribe` calls in components; register all handlers in `service.py` or use `client.on` within components if passed the client instance.
3.  **Use Subject Builder:** Replace string interpolation for NATS subjects.
