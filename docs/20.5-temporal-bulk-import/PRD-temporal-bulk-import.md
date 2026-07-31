# PRD: Temporal-Accurate Bulk Import

**Sprint**: 20.5 — `20.5-temporal-bulk-import`
**Status**: Next — implement after Sprint 20 (temporal awareness); before Sprint 21 (proactive injection)
**Builds on**: Sprints 8–20 (memory stack, `memory seed` CLI, heuristic/LLM extractors)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)
**REQs**: REQ-445 – REQ-460

---

## 1. Executive Summary

The existing `kryten-llm memory seed --logs` command assigns `created_at = now()` and omits
`last_seen` for every fact it writes — regardless of when the original chat message was
sent. A 45 MB historical chat log spanning months or years is therefore seeded with every
fact appearing to have been observed at seeding time, poisoning Sprint 20's recency ranking
before it can be useful.

The root cause: the log format (`HH:MM:SS <user>: message`) carries only a time-of-day
component, no calendar date. Sprint 20.5 adds a **log-date reconstructor** that reads the
file from the end using the file's mtime as a date anchor, detects midnight crossings by
watching for backward time jumps ≥ 1 hour, and assigns an ISO date to every parsed line.
Both the heuristic and LLM seed paths are then upgraded to write historically accurate
`created_at` / `last_seen` metadata.

Because the in-flight seed run will finish with all facts carrying incorrect timestamps, the
store will be **dropped and recreated** before re-seeding with the upgraded importer.

---

## 2. Problem Statement

### 2.1 Timestamp gap in `_parse_log_file`

`_parse_log_file` (in `__main__.py`) returns:

```python
{"username": str, "message": str, "time": "HH:MM:SS"}
```

No date field. Both seed paths (`_seed_via_heuristic`, `_seed_via_llm`) then write:

```python
"created_at": datetime.now(timezone.utc).isoformat()   # seeding time ≠ message time
# "last_seen" absent entirely in heuristic mode
```

### 2.2 Impact on recency ranking

Sprint 20 (Sortie 1) fixes `_upsert_facts` to write `last_seen` on live ingestion.
But seeded facts entering via `_seed_via_heuristic` bypass `_upsert_facts` entirely —
they go straight to `vector_store.upsert()` with no `last_seen`. Sprint 20 Sortie 1's
fix does not reach the seed path.

Sprint 20's configurable half-life decay is meaningless if `last_seen` is either absent
or set to today for a fact that is actually three years old.

### 2.3 Accumulation of wrong data

The in-flight LLM-mode seed run will complete with all facts timestamped at seeding time.
Re-using this store for Sprint 20 recency ranking would produce misleading results.
The store must be cleared and re-seeded once the importer is corrected.

---

## 3. Goals and Success Metrics

| Metric | Target |
|--------|--------|
| Date reconstructor correctly assigns dates to lines in a known-dated test fixture | Pass |
| Midnight crossings detected within ±1 day accuracy for logs with normal message density | Pass |
| Heuristic-mode seed writes `created_at` and `last_seen` = reconstructed log datetime | Pass |
| LLM-mode seed writes `created_at` and `last_seen` = reconstructed log datetime | Pass |
| `memory reset --confirm` clears the store and confirms count = 0 | Pass |
| No regression: seed without `--date-from-log` behaves identically to pre-Sprint-20.5 | Pass |

---

## 4. User Stories

- *As a maintainer*, I want facts seeded from a historical chat log to carry the date they
  were originally said, so recency ranking reflects actual temporal distance.
- *As an operator*, I want to clear the store and restart a seed run cleanly so stale
  incorrectly-timestamped data doesn't corrupt the memory quality baseline.
- *As a maintainer*, I want the date reconstruction to be automatic (opt-in flag) so I
  don't need to manually supply a date for every log file.

---

## 5. Technical Architecture

### 5.1 Date reconstruction algorithm (REQ-445 – REQ-449)

The log carries only `HH:MM:SS`. The file's `mtime` (modification time) is used as the
anchor date for the **last** line in the file. The reconstructor scans forward, detecting
where a time-of-day value decreases by more than one hour relative to the previous value —
this indicates a midnight crossing. Each crossing decrements the running date by one day.

```
forward scan:

line  time       Δ from prev    event
----  --------   -----------    -----
  …   23:59:42   +normal        (same day)
  …   00:00:07   −23h53m        MIDNIGHT → date -= 1
  …   00:15:33   +normal        (new day)
```

The result is a list of `(line_no, date)` pairs. A line that carries no parseable timestamp
inherits the date of the nearest preceding line that does.

**Edge cases:**
- Gaps spanning multiple days (no messages for > 24h): only one crossing is detected,
  meaning the date count may be off by the number of silent days. This is a known limitation;
  logs with normal activity density are unaffected.
- Server restarts or log rotation within a day can produce spurious small time-of-day
  jumps; the 1-hour threshold filters these out.
- The mtime anchor may be inaccurate if the file is still being written to. An explicit
  `--log-end-date YYYY-MM-DD` flag overrides mtime.

### 5.2 `_parse_log_file` upgrade (REQ-450 – REQ-451)

New signature:

```python
def _parse_log_file(
    path: Path,
    *,
    log_end_date: date | None = None,
) -> list[dict]:
    ...
```

When `log_end_date` is `None`, behaviour is identical to pre-Sprint-20.5 (no `date` field).

When `log_end_date` is provided:
- The date reconstructor runs (end anchor = `log_end_date` if given, else `path.stat().st_mtime`)
- Each returned message dict gains a `"date"` field: `"YYYY-MM-DD"` ISO string
- The `"time"` field is unchanged

### 5.3 Historical timestamps in `_seed_via_heuristic` (REQ-452 – REQ-453)

When a message dict carries a `"date"` field, the seeder constructs:

```python
historical_ts = f"{msg['date']}T{msg['time']}+00:00"
```

and uses it as both `created_at` and `last_seen` in the upsert metadata.

When no `"date"` field is present, falls back to `datetime.now(timezone.utc).isoformat()`
(existing behaviour — backward-compatible).

### 5.4 Historical timestamps in `_seed_via_llm` (REQ-454 – REQ-456)

LLM mode calls `provider._persist(ef)` which writes `created_at` / `last_seen` internally.
Two changes are needed:

1. Add `historical_ts: str | None = None` field to `ExtractedFact` (the dataclass/Pydantic
   model shared between extractors).
2. In `_seed_via_llm`, before calling `_persist`, compute the batch's representative
   historical timestamp (mean or first line's timestamp) and set `ef.historical_ts`.
3. In `LongTermMemoryProvider._persist`, if `ef.historical_ts` is set, write it as both
   `created_at` and `last_seen` instead of `datetime.now()`.

`historical_ts` defaults to `None` (live ingestion path unchanged).

### 5.5 CLI: `--log-end-date` and `memory reset` (REQ-457 – REQ-460)

**`memory seed` additions:**

```
--log-end-date YYYY-MM-DD   Explicit end-date anchor for midnight-crossing detection.
                             Overrides file mtime. Use when mtime is unreliable (e.g.
                             the log is still being appended to by a live service).
```

When omitted and `log_end_date` reconstruction is desired, file mtime is used automatically.
No flag is needed to opt-in — date reconstruction is always attempted when a log file is
found. If mtime cannot be read, falls back gracefully to current-time behaviour.

**`memory reset` (new subcommand):**

```
kryten-llm memory reset [--config CONFIG] [--confirm]
```

Deletes all documents from the configured store:
- Chroma: deletes and recreates the collection.
- pgvector: truncates the facts table (`TRUNCATE {table}`).

`--confirm` is required; without it the command prints the document count and exits without
changing anything. Prints the pre-reset count and confirms with "Store cleared." on success.

---

## 6. Dependencies

| Sprint | Dependency |
|--------|------------|
| Sprint 8 | `VectorStore.upsert`, `_parse_log_file`, `cmd_memory_seed` |
| Sprint 9 | `_rank_with_boost` uses `last_seen` for recency |
| Sprint 13 | `ExtractedFact` shape (confidence, importance) |
| Sprint 20 | `recency_half_life_days`; `last_seen` required in upsert (Sortie 1) |

Sprint 21 (proactive injection) uses `recency_days` from `ContextFragment`. Accurate
`last_seen` values from Sprint 20.5 are prerequisite for Sprint 21's `recency_days` gate
to be meaningful.

---

## 7. Security and Privacy

- `memory reset --confirm` requires an explicit flag; no accidental destructive execution.
- `log_end_date` is a date string validated against ISO format before use; no injection surface.
- No new data is transmitted externally. Date reconstruction is a local computation.
- Reconstructed timestamps are operational metadata (not PII).

---

## 8. Rollout Plan

1. **Sortie 1** — Date reconstructor module (`log_date_utils.py`) + unit tests.
2. **Sortie 2** — Wire date reconstruction into `_parse_log_file`, `_seed_via_heuristic`,
   and `_seed_via_llm` / `_persist`. Unit tests.
3. **Sortie 3** — CLI: `--log-end-date` flag on `memory seed`; `memory reset --confirm`
   subcommand. Integration test. Update `CHANGELOG.md`.

**Operator runbook (after Sortie 3):**

```bash
# 1. Stop any in-flight seed run (kill the process).
# 2. Reset the store.
kryten-llm memory reset --config config.json --confirm

# 3. Re-seed with accurate timestamps.
#    If the log file is still live (still being written to), supply --log-end-date.
kryten-llm memory seed --logs "chat-messages.log"
#    Or with explicit anchor:
kryten-llm memory seed --logs "chat-messages.log" --log-end-date 2025-06-01
```

---

## 9. Future Enhancements

- Per-file date override map (`{"chat-2024.log": "2024-12-31", ...}`) for archives with
  known end dates.
- Detect date-stamped lines within the log itself (e.g. server join messages that contain
  a full date) and use those as internal anchors, reducing reliance on mtime.
- Multi-day gap detection: if a log contains explicit date markers (e.g. from a different
  log format), use them to count silent days correctly.

---

## 10. Open Questions

**Resolved at creation:**
- Date anchor: file mtime (end of file). CLI override via `--log-end-date`.
- Midnight threshold: 1 hour (filter server restarts; detect real rollovers).
- `created_at` / `last_seen` format: full ISO datetime `YYYY-MM-DDTHH:MM:SS+00:00`.
- After in-flight seed: drop/recreate store, then re-seed.
- Sprint placement: Sprint 20.5, between Sprint 20 and Sprint 21. REQs: 445–460.
