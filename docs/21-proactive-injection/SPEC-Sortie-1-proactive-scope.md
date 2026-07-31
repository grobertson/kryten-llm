# SPEC-Sortie-1: Proactive Scope in LongTermMemoryProvider

**Sprint**: 21 — Proactive Memory Injection
**PRD**: [PRD-proactive-injection.md](PRD-proactive-injection.md)
**Status**: Planned
**Estimate**: 3h
**Depends on**: Sprint 13 (`confidence` metadata, `ContextFragment.confidence`);
  Sprint 18 (calibrated confidence — gate only meaningful post-calibration);
  Sprint 19 (compacted store — recommended before enabling)
**Requirements**: REQ-425 – REQ-430

---

## 1. Overview

Add `_run_proactive_scope` to `LongTermMemoryProvider`. After `_run_speaker_scope` returns
the raw query results, a fast synchronous check tests whether the top-ranked fact's cosine
similarity to the current message meets `proactive_threshold` AND the fact's confidence
meets `proactive_min_confidence`. If both gates pass, a `proactive_memory` `ContextFragment`
is emitted. No extra embedding call — the speaker query vector IS the message embedding.

---

## 2. Scope and Non-Goals

**In scope**: `_run_proactive_scope` method; `_proactive_*` instance variables;
wiring into `_provide_impl`; `_run_speaker_scope` refactor to return raw results for
the proactive check; unit tests.

**Non-goals**: Template changes (Sortie 2). Config model (Sortie 3). Observability metrics
(Sortie 4). Auto-participation counter reset behaviour (deferred future work).

---

## 3. Requirements

- **REQ-425** — `_run_proactive_scope(req, raw_results)` checks the top result (lowest
  distance / highest similarity) against `_proactive_threshold` and
  `_proactive_min_confidence`. Returns a list of `ContextFragment` (empty or one element).
- **REQ-426** — The proactive scope fires only when `_proactive_enabled = True` AND the
  trigger type is in `_proactive_fire_on`.
- **REQ-427** — Similarity gate: `sim = 1 - raw_results[0]["distance"]`;
  if `sim < _proactive_threshold`, return empty list.
- **REQ-428** — Confidence gate: `conf = raw_results[0]["metadata"].get("confidence", 0.0)`;
  if `conf < _proactive_min_confidence`, return empty list.
- **REQ-429** — On success: emit `ContextFragment(name="proactive_memory",
  priority=_proactive_priority, text=doc, est_chars=len(doc), confidence=conf)`.
- **REQ-430** — `_run_speaker_scope` is refactored to return the raw query results alongside
  its existing return value so `_provide_impl` can pass them to `_run_proactive_scope`
  without a second store query.

---

## 4. Design

### `_run_speaker_scope` signature change

The speaker scope currently returns `(list[ContextFragment], set[str], dict[str, float])`.
To avoid a second store query, extend to return the raw results too — but we must avoid
breaking the existing return signature used throughout `_provide_impl`.

**Approach**: return a 4-tuple or add a side-channel. The cleanest change is a 4-tuple:

```python
async def _run_speaker_scope(
    self, req: ContextRequest
) -> tuple[list[ContextFragment], set[str], dict[str, float], list[dict]]:
    """Returns (fragments, surfaced_ids, speaker_signals, raw_results)."""
    ...
    # Existing return at the end:
    return (
        [ContextFragment(...)] + signal_frags,
        surfaced_ids,
        speaker_signals,
        results,   # REQ-430: raw query results for proactive check
    )
```

Update all call sites (`_provide_impl`) to unpack 4 values.

### `_run_proactive_scope`

```python
def _run_proactive_scope(
    self,
    req: "ContextRequest",
    raw_results: list[dict],
) -> list["ContextFragment"]:
    """Emit a proactive_memory fragment when the top speaker fact is topically
    relevant to the current message (REQ-425–429).

    Synchronous — no new embedding call needed (the query IS the message vec).
    """
    if not self._proactive_enabled or not raw_results:
        return []
    trigger_type = str((req.trigger or {}).get("type", ""))
    if trigger_type not in self._proactive_fire_on:
        return []
    top = raw_results[0]
    sim = max(0.0, 1.0 - float(top.get("distance", 1.0)))
    if sim < self._proactive_threshold:
        return []
    conf = float(top.get("metadata", {}).get("confidence", 0.0))
    if conf < self._proactive_min_confidence:
        return []
    doc = str(top.get("document", ""))
    if not doc:
        return []
    return [ContextFragment(
        name="proactive_memory",
        priority=self._proactive_priority,
        text=doc,
        est_chars=len(doc),
        confidence=conf,
    )]
```

### `_provide_impl` wiring

```python
async def _provide_impl(self, req: ContextRequest) -> list[ContextFragment]:
    speaker_frags, speaker_ids, speaker_signals, raw_results = \
        await self._run_speaker_scope(req)                         # REQ-430
    fragments: list[ContextFragment] = list(speaker_frags)
    surfaced: set[str] = set(speaker_ids)

    if self._proactive_enabled:
        p_frags = self._run_proactive_scope(req, raw_results)      # REQ-425
        fragments.extend(p_frags)

    # ... existing topical/room/callback/ambient scopes unchanged ...
```

### `__init__` additions

```python
# Sprint 21: proactive memory injection (REQ-425–430).
self._proactive_enabled: bool = False
self._proactive_threshold: float = 0.80
self._proactive_min_confidence: float = 0.70
self._proactive_priority: int = 39
self._proactive_fire_on: set[str] = {"mention", "trigger_word", "auto_participation"}
```

These are wired from `pcfg.get("proactive", {})` in `from_config` (Sortie 3).

---

## 5. Implementation Plan

**Modify** `kryten_llm/components/context/providers/long_term_memory.py`:
1. `__init__`: add `_proactive_*` fields.
2. `_run_speaker_scope`: return 4-tuple adding `raw_results`.
3. `_provide_impl`: unpack 4-tuple; call `_run_proactive_scope`.
4. Add `_run_proactive_scope` method.

Note: `_run_speaker_scope` is also called by tests directly. Update those tests to unpack
4 values.

**New tests** in `tests/test_proactive_injection.py`.

---

## 6. Testing Strategy

Use `FakeEmbedder` and in-memory store. Inject mock raw results directly.

- **Both gates pass** (`sim=0.85 ≥ threshold=0.80, conf=0.75 ≥ min_conf=0.70`):
  `proactive_memory` fragment emitted.
- **Similarity gate fails** (`sim=0.70 < 0.80`): empty list.
- **Confidence gate fails** (`conf=0.60 < 0.70`): empty list.
- **`proactive_enabled=False`**: empty list regardless of similarity/confidence.
- **Trigger type not in `fire_on`**: empty list.
- **Empty `raw_results`**: empty list.
- **Empty `document` string on top result**: empty list.
- **`_run_speaker_scope` returns 4-tuple**: existing tests unpack 4 values without error.

---

## 7. Acceptance Criteria

- [ ] Both gates pass → `proactive_memory` fragment with correct text and confidence.
- [ ] Similarity gate fails → empty list.
- [ ] Confidence gate fails → empty list.
- [ ] `proactive_enabled=False` → empty list.
- [ ] Trigger type not in `fire_on` → empty list.
- [ ] Existing `_provide_impl` tests pass (4-tuple unpacking change is backward-compatible).

---

## 8. Rollout

`_proactive_enabled = False` default. No `from_config` wiring yet (Sortie 3). Tests use
direct `__init__` field assignment to enable.

---

## 9. Documentation

`CHANGELOG.md` entry: `feat: proactive scope in LongTermMemoryProvider (Sprint 21, Sortie 1, REQ-425–430)`.
