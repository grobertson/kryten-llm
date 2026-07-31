# PRD: Proactive Memory Injection

**Sprint**: 21 — `21-proactive-injection`
**Status**: Planned (N+2) — Sorties 1–4 ready; implement after Sprints 19 & 20
**Gate**: Sprint 18 ✅ complete. Sprint 19 (compaction) must be complete before enabling
  in production. Sprint 20 (temporal awareness) recommended before enabling.
**Builds on**: Sprints 8–20
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)
**REQs**: REQ-425 – REQ-444

---

## 1. Executive Summary

Every LLM response is trigger-driven. Memory is consulted only when the bot is mentioned or
a trigger word fires. This leaves genuinely relevant facts latent: the bot knows a user loves
samurai films, hears them say "we should watch more samurai stuff," but stays silent because
no one addressed it. Proactive injection adds a fast post-retrieval check: after the standard
speaker-scope memory pull, if the top-ranked speaker fact has cosine similarity ≥
`proactive_threshold` to the current message AND confidence ≥ `proactive_min_confidence`,
it is emitted as a `proactive_memory` context fragment. The LLM then naturally weaves the
connection into its response. Default-off; requires a clean, well-calibrated store (S18+S19).

---

## 2. Problem Statement

The bot has years of learned facts that only surface when users explicitly invoke it. The
memory system's ROI depends on those facts being recalled when topically relevant — not only
on demand. Proactive injection is the mechanism that bridges this gap without requiring a
mention. It is strictly speaker-focused (the current speaker's own facts), never crosses
user boundaries, and is gated by confidence to prevent dubious interjections.

---

## 3. Goals and Success Metrics

| Metric | Target |
|--------|--------|
| `proactive_memory` fragment emitted when sim ≥ threshold & conf ≥ gate | Pass |
| No fragment when either gate fails | Pass |
| Rate limits respected: no new response turns created | Pass |
| Debug log emitted per proactive decision | Pass |
| Default `enabled: false`: no change to existing pipeline | Pass |

---

## 4. User Stories

- *As a community member*, I want the bot to connect what I'm saying to things it already
  knows about me, even when I haven't addressed it, so conversations feel personal.
- *As a community member*, I want proactive injection to feel natural, not intrusive — the
  bot should interject only when the connection is genuinely strong.
- *As an operator*, I want a configurable relevance threshold so I can start conservative
  and tune with observed data.
- *As an operator*, I want proactive injection to respect all existing rate limits and
  cooldowns so it cannot circumvent them.
- *As a maintainer*, I want proactive injection decisions to be observable (logs, metrics)
  so I can tell when and why a memory was injected.

---

## 5. Technical Architecture

### 5.1 Proactive scope in `_provide_impl`

After `_run_speaker_scope` returns `speaker_results` (the raw query results), add:

```python
if self._proactive_enabled and speaker_results:
    p_frags = self._run_proactive_scope(req, speaker_results)
    fragments.extend(p_frags)
```

`_run_proactive_scope` is synchronous (no new embedder call needed — the query vector IS
the message embedding, already computed in `_run_speaker_scope`):

```python
def _run_proactive_scope(
    self, req: ContextRequest, speaker_results: list[dict]
) -> list[ContextFragment]:
    if not self._proactive_enabled:
        return []
    trigger_type = str((req.trigger or {}).get("type", ""))
    if trigger_type not in self._proactive_fire_on:
        return []
    top = speaker_results[0]
    sim = max(0.0, 1.0 - float(top.get("distance", 1.0)))
    if sim < self._proactive_threshold:
        return []
    conf = float(top.get("metadata", {}).get("confidence", 0.0))
    if conf < self._proactive_min_confidence:
        return []
    doc = str(top.get("document", ""))
    if not doc:
        return []
    if self._monitor is not None:
        self._monitor.record_proactive_injection(triggered=True, similarity=sim)
    logger.debug(
        "proactive: user=%s fact=%r similarity=%.3f threshold=%.2f triggered=True",
        req.username, doc[:60], sim, self._proactive_threshold,
    )
    return [ContextFragment(
        name="proactive_memory",
        priority=self._proactive_priority,
        text=doc,
        est_chars=len(doc),
        confidence=conf,
    )]
```

`speaker_results` is the raw `results` list from `_store.query()` — pass it alongside
the existing return from `_run_speaker_scope`. This requires a small refactor of
`_run_speaker_scope` to return the raw results (or pass them separately).

### 5.2 Template integration

`trigger.j2` addition:
```jinja2
{% if proactive_memory %}
(Just to mention: {{ proactive_memory }})
{% endif %}
```

`system.j2` addition when `proactive_memory_active` is set:
```jinja2
{% if proactive_memory_active %}
A memory about this user has been surfaced because it's relevant to what they just said.
If it fits naturally, weave it in — but only if it adds genuine value.
{% endif %}
```

### 5.3 Config block

```json
"proactive": {
  "enabled": false,
  "threshold": 0.80,
  "min_confidence": 0.70,
  "priority": 39,
  "fire_on": ["mention", "trigger_word", "auto_participation"]
}
```

`fire_on` list controls which trigger types allow proactive injection. All three are enabled
by default; operators can restrict to `["mention"]` for a conservative start.

### 5.4 Observability

`HealthMonitor.record_proactive_injection(triggered: bool, similarity: float)`:
- Increments `_proactive_injections_total` (labelled `triggered=true/false`).
- Appends `similarity` to `_proactive_similarities` ring buffer for avg/p95.

Prometheus metrics: `llm_proactive_injections_total{triggered}`,
`llm_proactive_similarity` (histogram).

---

## 6. Dependencies

| Sprint | Dependency |
|--------|------------|
| Sprint 13 | `confidence` metadata field |
| Sprint 18 | Calibrated confidence (mandatory gate — `min_confidence = 0.70` is only meaningful after calibration) |
| Sprint 19 | Compacted store (recommended — post-compaction canonical facts are more reliable for proactive injection) |
| Sprint 20 | `recency_days` on `ContextFragment` (future enhancement: gate proactive on recency) |

---

## 7. Security and Privacy

Proactive injection is strictly speaker-scoped — only the current speaker's own facts are
checked. No cross-user data is surfaced. The confidence gate (≥ 0.70) prevents unverified
or contested facts from being injected. Rate limits are unconditionally respected: proactive
injection enriches existing triggered turns; it never creates new response turns.

---

## 8. Rollout Plan

1. **Sortie 1**: Proactive scope in `_provide_impl`. Default-off. Unit tests validate
   threshold and confidence gate.
2. **Sortie 2**: Template integration (`trigger.j2`, `system.j2`). Default-off blocks.
3. **Sortie 3**: `ProactiveConfig` in `models/config.py`; `from_config` wiring.
4. **Sortie 4**: `HealthMonitor` observability; Prometheus metrics; debug log.
5. **Operator opt-in**: Enable with `threshold: 0.85` (high, conservative). Observe
   `llm_proactive_injections_total`. Tune threshold down to 0.80 after quality validation.

---

## 9. Future Enhancements

- Auto-participation replacement: when `proactive_memory` fires on an auto-participation
  turn, use it as the explicit reason for speaking rather than the message-count threshold.
  Requires trigger engine changes; deferred to a follow-up sprint.
- Per-user proactive threshold (users who dislike proactive interjections can opt out).
- `recency_days` gate: only proactively inject facts seen within `proactive_max_recency_days`
  (ensures proactive facts are current, not ancient history).
- Cross-channel proactive injection: explicitly requires Sprint 17 consent gate.

---

## 10. Open Questions

**Resolved at promotion:**
- New trigger type or augment existing turn? → Augment existing turn (Sprint 21 scope).
  Creating a `proactive` trigger type is the auto-participation replacement extension (deferred).
- Auto-participation counter reset? → Yes, counter resets normally in Sprint 21. The
  "don't reset on proactive reason" behaviour is part of the deferred extension.
- Default `proactive_threshold`? → 0.80. `proactive_min_confidence` → 0.70.
- Cross-channel proactive injection? → Explicitly out of scope; requires S17 consent gate.
