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
No refactor of `_run_speaker_scope`'s return signature.

---

## 3. Requirements

- **REQ-425** — `_run_proactive_scope(req)` issues its **own** `store.query` using the
  cached message vector (`self._last_message_vec`) to find the speaker's closest fact.
  Returns a list of `ContextFragment` (empty or one element). No change to
  `_run_speaker_scope`'s return signature.
- **REQ-426** — The proactive scope fires only when `_proactive_enabled = True` AND the
  trigger type is in `_proactive_fire_on`. If `self._last_message_vec` is `None` (no
  embedding was computed this turn), return empty.
- **REQ-427** — The proactive query fetches `k=1` from the store filtered to the current
  speaker. Similarity gate: `sim = 1 - results[0]["distance"]`;
  if `sim < _proactive_threshold`, return empty list.
- **REQ-428** — Confidence gate: `conf = results[0]["metadata"].get("confidence", 0.0)`;
  if `conf < _proactive_min_confidence`, return empty list.
- **REQ-429** — On success: emit `ContextFragment(name="proactive_memory",
  priority=_proactive_priority, text=doc, est_chars=len(doc), confidence=conf)`.
- **REQ-430** — `_run_speaker_scope` is **not** refactored. `_run_proactive_scope`
  reuses `self._last_message_vec` (already written by `_run_speaker_scope`). The extra
  `k=1` store query is the accepted trade-off for a clean signature.

---

## 4. Design

### `_run_proactive_scope`

```python
async def _run_proactive_scope(
    self,
    req: "ContextRequest",
) -> list["ContextFragment"]:
    """Emit a proactive_memory fragment when the speaker's closest fact is
    topically relevant to the current message (REQ-425–429).

    Runs its own k=1 store query using the cached message vector from
    _run_speaker_scope. One extra store round-trip; no signature change.
    """
    if not self._proactive_enabled:
        return []
    trigger_type = str((req.trigger or {}).get("type", ""))
    if trigger_type not in self._proactive_fire_on:
        return []
    vec = self._last_message_vec          # set by _run_speaker_scope (REQ-430)
    if vec is None:
        return []
    results = await self._store.query(
        vector=vec, k=1, where={"user": req.username}
    )
    if not results:
        return []
    top = results[0]
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

### `_provide_impl` wiring (no signature change to `_run_speaker_scope`)

```python
async def _provide_impl(self, req: ContextRequest) -> list[ContextFragment]:
    speaker_frags, speaker_ids, speaker_signals = \
        await self._run_speaker_scope(req)         # unchanged return signature
    fragments: list[ContextFragment] = list(speaker_frags)
    surfaced: set[str] = set(speaker_ids)

    if self._proactive_enabled:
        p_frags = await self._run_proactive_scope(req)   # REQ-425
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
