# PRD: Reverse-Chronological Memory Seed

**Sprint**: 24 — `24-reverse-seed`
**Status**: Planned
**Builds on**: Sprint 20.5 (temporal-accurate bulk import); Sprint 22/23 (release prep)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)
**REQs**: REQ-491 – REQ-496
**Target version**: 0.10.3

---

## 1. Executive Summary

The `kryten-llm memory seed --logs` command (LLM path) currently processes log files in
ascending alphabetical order and, within each file, sends the oldest messages first. When
seeding 7+ months of historical logs against a live channel, this means the bot has no
recent memory for days — the most contextually valuable facts (what users said last week)
are the last to be written.

Sprint 24 inverts the processing order: log files are sorted by modification time
descending (newest first), and within each file the LLM extraction batches are also
processed in reverse order (most recent batch first, each batch internally
chronological). The date-reconstruction and `_SeedProgress` subsystems are unaffected.
The heuristic path is out of scope.

---

## 2. Problem Statement

### 2.1 Forward processing leaves the bot blind during seeding

A typical seed run on 7 months of logs takes hours. With forward processing, the bot's
memory is populated exclusively with ancient facts for the bulk of that time — facts from
months-old conversations that may no longer reflect active users. The most recent, most
relevant facts (what people said yesterday, last week) don't land until the very end.

Because the bot is live during seeding (designed for concurrency), it operates with a
distorted or empty recency signal for the duration of the run. Recency ranking (Sprint 20)
and proactive injection (Sprint 21) are both meaningless until the recent facts arrive.

### 2.2 Forward file sort compounds the problem

The glob is sorted alphabetically. For date-named log files (e.g. `2024-03-15.log`),
alphabetical order is chronological order — so the oldest file is processed first. This
amplifies the recency problem at the file level.

### 2.3 No gaps concern for this corpus

The logs are continuous: every session produces at minimum `[server]` status lines
(matched by `_SERVER_RE`). The midnight-crossing date-reconstruction algorithm
(`log_date_utils.assign_dates`) handles these correctly — server lines get
`time = None` and inherit the nearest preceding line's date. There are no silent
multi-day gaps to account for.

---

## 3. Goals and Success Metrics

| Metric | Target |
|--------|--------|
| After seeding 3 files, facts from the newest file are in the store before any facts from the oldest | Pass |
| Within a file, the most recent batch's facts are written before the oldest batch's facts | Pass |
| Date reconstruction, `historical_ts` on `ExtractedFact`, and all Sprint 20.5 timestamp behaviour are unaffected | Pass (no regression) |
| `_SeedProgress` counters and ETA remain accurate with reverse-order processing | Pass |
| `uv run black . && uv run ruff check --fix . && uv run mypy kryten_llm && uv run pytest` all clean | Pass |

---

## 4. User Stories

- *As an operator*, I want the most recent facts in the memory store as quickly as
  possible so the bot appears contextually aware from the first minutes of a seed run.
- *As a maintainer*, I want recency ranking (Sprint 20) and proactive injection (Sprint 21)
  to be meaningful as soon as possible during a re-seed, not hours later.

---

## 5. Technical Architecture

### 5.1 Log format (confirmed)

```
HH:MM:SS <username>: message text
HH:MM:SS <[server]>: server/status message
```

`_LINE_RE` matches user messages; `_SERVER_RE` matches server lines. The date
reconstructor already handles both correctly. No format changes needed.

### 5.2 File sort order (REQ-491)

`_seed_via_llm` re-sorts `all_file_data` after the pre-parse step using each file's
`st_mtime` descending. The sort happens post-parse so `stat()` calls are guaranteed safe
(the files have just been successfully read).

```python
all_file_data.sort(
    key=lambda item: item[0].stat().st_mtime,
    reverse=True,
)
```

The `cmd_memory_seed` pre-sort (alphabetical `sorted(...)`) is unchanged — it controls
display order during glob expansion, and the LLM path overrides it at extraction time.
The heuristic path retains alphabetical order (out of scope).

### 5.3 Per-file reverse batch processing (REQ-492)

After parsing a file, `_parse_log_file` returns messages in forward chronological order
with `"date"` fields already attached. The batch loop is changed from:

```python
# Old — forward order
for i in range(0, len(messages), batch_size):
    batch = messages[i : i + batch_size]
```

to:

```python
# New — newest batch first; each batch internally chronological
batch_starts = list(range(0, len(messages), batch_size))
for start in reversed(batch_starts):
    batch = messages[start : start + batch_size]
```

This preserves within-batch chronological order so the LLM extractor sees a natural
conversation window. Only the order in which windows are submitted to the extractor is
reversed.

### 5.4 `batch_ts` behaviour (REQ-493)

`batch_ts` is currently the timestamp of the first dated message in each batch (the
earliest message in that window). This is correct for all processing orders: each batch
represents a time-bounded conversation window and its historical anchor should be the
start of that window, not the end. No change.

With reverse batch processing, the first report from `_SeedProgress.format(log_date)`
will show the most recent date in the file — giving the operator an immediate confirmation
that reverse-chronological processing is active.

### 5.5 Date reconstruction unchanged (REQ-494)

`_parse_log_file` and `log_date_utils` are untouched. The mtime-anchored forward-scan
crossing algorithm assigns dates to all message dicts before any batching occurs. Reversing
the batch order has no effect on date accuracy.

### 5.6 `_SeedProgress` unchanged (REQ-495)

`_SeedProgress.total` is computed from pre-parsed message counts. `advance(len(batch))`
is called after each batch regardless of order. ETA and elapsed-time calculations are
unaffected. The displayed `log_date` will now count backwards (most recent → oldest),
which is the correct representation of reverse-chronological progress.

---

## 6. Scope

**In scope**: `kryten_llm/__main__.py` — `_seed_via_llm` only.

**Out of scope**:
- `_seed_via_heuristic` — no change; heuristic seeding order is a separate concern.
- `_parse_log_file`, `log_date_utils.py`, `ExtractedFact` — no change.
- `LongTermMemoryProvider._persist` — no change.
- CLI flags (`--forward` / `--reverse` toggle) — not needed; reverse-chronological is
  always correct for this corpus. Add a flag only if a concrete use case for forward
  order on the LLM path emerges.

---

## 7. Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| LLM extractor receives a batch whose messages have no `"date"` field (mtime unavailable) | Low | `batch_ts` already handles this with a `None` fallback; `historical_ts = None` falls back to `datetime.now()` in `_persist` — same as pre-Sprint-20.5 |
| stat() on a just-parsed file fails the mtime sort | Very low | Files were read moments before; wrap `stat()` with a try/except and fall back to path-alphabetical sort for that file |
| Existing tests assert forward processing order | Low | Audit tests before implementing; update any order-dependent assertions |
