# SPEC-Sortie-2: Retention sweeper

**Sprint**: 10 — Memory Privacy & Governance
**PRD**: [PRD-memory-privacy.md](PRD-memory-privacy.md)
**Status**: Planned
**Estimate**: 3–5h
**Depends on**: Sprint 8 (store `get_all`/`delete_ids`, `created_at`/`importance` metadata)
**Requirements**: REQ-180 – REQ-189

---

## 1. Overview

Add a periodic **retention sweeper** that expires stale, low-value facts so the memory corpus
doesn't grow unbounded or retain sensitive data indefinitely. Expiry is by age and/or low
importance, using metadata already stored (`created_at`, `importance`).

## 2. Scope and Non-Goals

**In scope**: a background sweep task; age + importance expiry policy; batch delete via
`delete_ids`; config window; default-off / generous default.

**Non-goals**: per-category policies (Sprint 12/E); deletion by content; real-time expiry.

## 3. Requirements

- **REQ-180** — A periodic task sweeps the store on a configurable interval.
- **REQ-181** — A fact is eligible for expiry when `age > max_age_days` AND
  `importance <= expire_below_importance` (both configurable; either can be disabled).
- **REQ-182** — Expiry uses `get_all` to find candidates and `delete_ids` to remove them in
  bounded batches.
- **REQ-183** — Sweeper is fail-safe: errors are logged and never crash the service loop.
- **REQ-184** — Default disabled (or a very generous default window) so existing deployments
  don't silently lose data.
- **REQ-185** — Each sweep logs a summary (scanned, expired) and increments a metric.
- **REQ-186** — Retention config is a schema change → versioned and documented.

## 4. Design

A lightweight async loop (started with the service) that, every `interval_hours`, scans user
facts and deletes those matching the policy:

```python
cutoff = now - timedelta(days=max_age_days)
expired = [r["id"] for r in await store.get_all()
           if _parse(r["metadata"].get("created_at")) < cutoff
           and int(r["metadata"].get("importance", 1)) <= expire_below_importance]
for batch in chunk(expired, 500):
    await store.delete_ids(batch)
```

Runs off the critical path; guarded by try/except; respects a max batch size to bound load.

## 5. Implementation Plan

**New**
- `components/memory/retention.py` — `RetentionSweeper` (start/stop, one `sweep()` pass).

**Modify**
- `service.py` — start/stop the sweeper when configured.
- `models/config.py` — `retention` block (`enabled`, `interval_hours`, `max_age_days`,
  `expire_below_importance`, `batch_size`).
- `config.example.json` — `retention` block (default disabled).
- `components/health_monitor.py` — `memory_facts_expired_total` counter.

## 6. Testing Strategy

- Old, low-importance fact expired; recent or high-importance fact retained.
- Disabling either criterion (age-only / importance-only) works.
- Batch delete respects `batch_size`.
- Sweep error is caught and logged (loop survives).
- Default-off → no deletions.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Configurable sweeper expires only eligible facts.
- [ ] Never crashes the service; emits a per-sweep summary + metric.
- [ ] Off by default.

## 8. Rollout

- Ship default-off; enable per deployment with a generous window first.
- Watch the expiry counter and store size after enabling.

## 9. Documentation

- `docs/user-memory-explained.md`: retention policy + config.
- `docs/config-migration` note for the schema addition.
- `CHANGELOG.md` entry.
