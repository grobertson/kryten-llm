# PRD: Temporal Fact Awareness

**Sprint**: 20 — `20-temporal-awareness`
**Status**: Next (N+1) — Sorties 1–4 ready; implement after Sprint 19
**Builds on**: Sprints 8–19 (memory, quality, governance, eval, confidence,
  model routing, calibration, compaction)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)
**REQs**: REQ-405 – REQ-424

---

## 1. Executive Summary

Facts in the vector store carry `created_at` and `last_seen` timestamps, but the retrieval
layer uses only a hyperbolic `1/(1+age_days)` recency formula with no operator tuning knob.
Additionally, `last_seen` is never written in heuristic-mode upserts — so heuristic-mode
facts always score 0.0 on recency. Sprint 20 fixes this gap in three steps: (1) upgrade the
recency formula to configurable exponential half-life decay; (2) surface a `recency_days`
field on `ContextFragment` so `trigger.j2` can hedge by age band; (3) ensure `last_seen` is
written in all insertion paths and provide a backfill helper for existing stores.

Sprint 18's `ConfidenceDriftSweeper` already handles passive confidence decay for dormant
facts. Sprint 20 does **not** add another drift sweeper — it focuses on the retrieval ranking
and template presentation layers.

---

## 2. Problem Statement

**Audit result** (Open Question from ideation, resolved): `recency_weight` in
`RetrievalBoostConfig` IS computed from timestamps via `_recency_factor` using
`1/(1+age_days)`. Two concrete gaps remain:

1. `_recency_factor` uses a non-configurable hyperbolic formula. At 1 day old, score = 0.5.
   At 90 days old, score = 0.011. The spread is real but cannot be tuned by operators.
2. `_upsert_facts` (heuristic path) writes `created_at` but **not** `last_seen`. So all
   heuristic-mode facts have no `last_seen` and `_recency_factor` returns 0.0 for them —
   effectively disabling recency ranking for heuristic-mode deployments.
3. `ContextFragment` carries no temporal information, so templates cannot hedge by fact age.

**Who benefits**: operators (configurable recency tuning), the community (temporally
grounded hedging), Sprint 21 proactive injection (`recency_days` can gate whether a fact
is fresh enough to surface proactively).

---

## 3. Goals and Success Metrics

| Metric | Target |
|--------|--------|
| Recency ranking: recently-seen fact outranks older same-similarity fact | Pass (when `recency_weight > 0`) |
| `last_seen` written for all new heuristic-mode facts | Pass |
| Temporal hedging fires at correct age bands | Pass |
| Default `recency_half_life_days = 0`: no ranking change | Pass (backward-compatible) |

---

## 4. User Stories

- *As a community member*, I want the bot to acknowledge when something it remembers is old
  ("you mentioned back in the day…"), so its replies feel honest about uncertainty.
- *As an operator*, I want retrieval to prefer recently corroborated facts over stale ones
  when confidence and importance are equal.
- *As a maintainer*, I want a configurable recency half-life so I can tune how aggressively
  old facts are deprioritised without deleting them.
- *As a maintainer*, I want `last_seen` written reliably in all write paths so recency
  ranking works regardless of which extractor mode is in use.

---

## 5. Technical Architecture

### 5.1 Exponential half-life formula

Replace `_recency_factor` in `long_term_memory.py`:
```python
@staticmethod
def _recency_factor(last_seen: str, now: datetime, half_life_days: float = 0.0) -> float:
    if not last_seen: return 0.0
    try:
        ts = datetime.fromisoformat(last_seen)
    except ValueError:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
    if half_life_days > 0:
        return math.exp(-age_days / half_life_days)   # REQ-405
    return 1.0 / (1.0 + age_days)                     # legacy hyperbolic (REQ-409)
```

New field on `RetrievalBoostConfig`:
```python
recency_half_life_days: float = Field(
    default=0.0, ge=0.0,
    description="Exponential recency half-life in days (Sprint 20, REQ-405). "
                "0 = legacy hyperbolic formula. 90 = recommended starting value."
)
```

### 5.2 `last_seen` in heuristic mode

`_upsert_facts` must write `"last_seen": now` in every upserted fact's metadata (REQ-407).
Currently only LLM-mode `_persist` and `_bump_importance` write `last_seen`.

### 5.3 `recency_days` on ContextFragment

Add `recency_days: int | None = None` to `ContextFragment.`

In `_run_speaker_scope`, after ranking, set:
```python
top_meta = ranked[0].get("metadata", {}) if ranked else {}
top_ts = top_meta.get("last_seen") or top_meta.get("created_at")
recency_days = _days_since(top_ts)  # int | None
```

Pass `recency_days` into the emitted `ContextFragment`.

### 5.4 Template hedging (trigger.j2)

```jinja2
{% if user_memory %}
{% if temporal_hedge_enabled %}
  {% if recency_days is not none and recency_days >= temporal_old_threshold %}
(From some time ago — things may have changed) {{ user_memory }}
  {% elif recency_days is not none and recency_days >= temporal_recent_threshold %}
(A while back) {{ user_memory }}
  {% else %}
{{ user_memory }}
  {% endif %}
{% elif confidence is defined and confidence is not none and confidence < hedge_above and hedge_enabled %}
I think {{ user_memory }}
{% else %}
{{ user_memory }}
{% endif %}
{% endif %}
```

Temporal hedging is gated behind `temporal_hedge_enabled: false` (default). Thresholds
`temporal_recent_threshold` (default 7 days) and `temporal_old_threshold` (default 90 days)
are provider-config fields.

### 5.5 `last_seen` backfill helper

`kryten-llm memory backfill-last-seen [--config CONFIG]` — iterates all facts without
`last_seen`, sets `last_seen = created_at` (or `datetime.now()` if no `created_at`),
and logs the count. Safe to re-run (skips facts that already have `last_seen`).

---

## 6. Dependencies

| Sprint | Dependency |
|--------|------------|
| Sprint 9 | `_rank_with_boost`, `RetrievalBoostConfig` |
| Sprint 13 | `confidence`, `importance` metadata fields |
| Sprint 18 | `ConfidenceDriftSweeper` (temporal drift already handled) |
| Sprint 19 | Compaction reduces near-duplicate clutter before temporal ranking matters |

No new sweeper class needed: S18's `ConfidenceDriftSweeper` covers passive confidence decay.

---

## 7. Security and Privacy

`last_seen` is an operational timestamp. `recency_days` in the template is derived from
metadata, not from user-visible text. No new PII surface. Backfill helper operates locally
on the store and never transmits data externally.

---

## 8. Rollout Plan

1. **Sortie 1**: `last_seen` written in heuristic mode + `_recency_factor` signature change.
   Default `half_life_days = 0` → no ranking change for existing deployments.
2. **Sortie 2**: `recency_days` on `ContextFragment`; template hedging. Default
   `temporal_hedge_enabled: false`.
3. **Sortie 3**: `last_seen` backfill CLI helper; verify heuristic path writes `last_seen`.
4. **Sortie 4**: `config.example.json` updates; eval test for recency ordering.

**Operator tuning**: set `recency_half_life_days: 90` to enable exponential decay. Run
backfill helper once on existing stores. Enable `temporal_hedge_enabled: true` to see
age-band hedging.

---

## 9. Future Enhancements

- Per-category recency half-lives (preferences decay faster than biographical facts).
- Sprint 21 proactive injection: use `recency_days` to gate whether a proactively-matched
  fact is fresh enough to surface (very old facts might not warrant proactive injection).
- `inspect.user` output includes `last_seen` age.

---

## 10. Open Questions

**Resolved at promotion:**
- Is `recency_weight` already computed from timestamps? → **Yes** (`_recency_factor` uses
  `last_seen`); Sprint 20 refines the formula and fixes the heuristic-path gap.
- Does S20 add another drift sweeper? → **No**; S18's `ConfidenceDriftSweeper` covers this.
- Default `half_life_days`? → 0.0 (backward-compatible default); 90 days recommended start.
- Temporal vs confidence hedging interaction? → Temporal hedging is gated separately
  (`temporal_hedge_enabled`). Confidence hedging (`hedge_enabled`) remains independent; if
  both are enabled, temporal takes precedence (it wraps the user_memory block).
