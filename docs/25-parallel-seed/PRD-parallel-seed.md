# PRD: Parallel Seed + Checkpoint/Resume

**Sprint**: 25 — `25-parallel-seed`
**Status**: Planned
**Builds on**: Sprint 24 (reverse-chronological seed)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)
**REQs**: REQ-497 – REQ-518
**Target version**: 0.10.4

---

## 1. Executive Summary

The `kryten-llm memory seed --logs` command (LLM path) has three interrelated problems
that together make a 541k-message, single-file seed run impractically slow and
irresumable:

1. **Batch dilution**: Bot messages (VHSOracle, ZcoinBank, etc.) occupy slots in every
   batch before being sent to the LLM extractor. Because facts attributed to bots are
   discarded post-extraction, bot-heavy exchanges produce near-zero fact yield per LLM
   call while consuming the same wall-clock time as human-rich batches.

2. **Sequential extraction**: One LLM call at a time, leaving available GPU compute
   (3 × 24 GB P40s, two LM Studio model instances each with 4 parallel slots) almost
   entirely idle between calls.

3. **No resume**: Any interruption — power loss, OOM, intentional stop for
   experimentation — forces a full restart from the most-recent batch, discarding
   potentially many hours of already-completed work.

Sprint 25 addresses all three in three focused sorties. The goal is a 2× or greater
end-to-end speedup with the ability to stop and resume at batch granularity.

---

## 2. Problem Statements

### 2.1 Bot message dilution (Sortie 1)

With `batch_max_size: 6`, a typical 6-message window drawn from a channel where
VHSOracle is active might contain 4 bot messages and 2 human messages. The LLM sees
all 6, produces 0–1 storable facts (for the 2 human speakers), and the caller discards
any bot-attributed facts — all for the same latency as a batch of 6 human messages.

Effective throughput in human-relevant facts per LLM call is 60–70 % lower than the
configured batch size implies.

**Fix**: filter excluded users from the message list *before* building batches. Each
batch of `batch_max_size` will contain only human messages. Bot messages stop consuming
LLM context. The post-extraction exclude check is retained as a safety net.

**Also**: `SaveTheRobots` and `CynthiaRothbot` are missing from the current
`observe_exclude_users` list. Facts attributed to these bots are currently persisted.
The config must be corrected; the pre-filter fix automatically handles any future names
added to the list.

### 2.2 Sequential LLM extraction (Sortie 3)

Each `await extractor.extract(batch, "")` is an HTTP call to LM Studio with typical
latency 5–30 s. Between calls the event loop is idle. The hardware supports N concurrent
calls:

- Two model instances (`gemma-4-26b-a4b-it-heretic` and `gemma-4-26b-a4b-it-heretic:2`)
  each reporting 4 internal parallel slots in LM Studio.
- Practical target: **4 concurrent workers** (2 per model), hardware limit ≈ 8.

The implementation uses an `asyncio.Queue` of pre-assembled batches and N worker
coroutines, each wrapping its own `LLMFactExtractor` instance pinned to one provider
entry in the extractor's `llm.providers` map.

The `_persist` path already uses per-user `asyncio.Lock` and is safe for concurrent
writes without modification.

### 2.3 No resume (Sortie 2)

A checkpoint JSON file tracks which batch offsets (into the post-filtered human-message
list) have been completed. On `--resume`, completed offsets are skipped. The file is
written atomically (write to `.tmp`, then `os.replace()`) after each batch so a crash
mid-batch at most replays one batch.

---

## 3. Goals and Success Metrics

| Metric | Target |
|--------|--------|
| Batches sent to LLM contain only human messages | Pass |
| `SaveTheRobots` and `CynthiaRothbot` added to `observe_exclude_users` in `config.example.json` | Pass |
| `--checkpoint PATH --resume` resumes from a partially-completed run, skipping completed offsets | Pass |
| Checkpoint file is absent before first run and grows monotonically during run | Pass |
| `--workers 4` with two worker_providers runs 4 concurrent LLM calls and completes faster than `--workers 1` | Pass |
| `--workers 1` (default) behaviour is identical to pre-Sprint-25 except for the pre-filter | Pass (no regression) |
| All existing tests pass; new tests added for pre-filter, checkpoint, and worker pool | Pass |
| `uv run black . && uv run ruff check --fix . && uv run mypy kryten_llm && uv run pytest` clean | Pass |

---

## 4. User Stories

- *As an operator*, I want every LLM call to be filled with human conversation content
  so I get maximum fact yield per GPU second.
- *As an operator*, I want to stop a 120-hour seed run at hour 12, fix something, and
  resume from batch 2,000 rather than batch 0.
- *As an operator*, I want to run 4 concurrent LLM workers across two model instances
  to use the available GPU headroom and finish seeding in a fraction of the current time.

---

## 5. Architecture

### 5.1 Pre-batch filter (Sortie 1, REQ-497–500)

In `_seed_via_llm`, immediately after parsing a file:

```python
human_messages = [m for m in messages if m["username"].lower() not in exclude]
```

All downstream logic (batch assembly, progress counting, checkpoint offset tracking)
operates on `human_messages`. The `exclude` set is already populated from
`provider._observe_exclude`. The progress reporter now shows both human-message count
and the number of bot messages filtered.

### 5.2 Checkpoint (Sortie 2, REQ-501–509)

**File format** (`seed-checkpoint.json`):
```json
{
  "version": 1,
  "file": "/abs/path/to/chat-messages.log",
  "batch_size": 6,
  "exclude_users": ["vhsoracle", "zcoinbank", ...],
  "completed_offsets": [90696, 90690, 90684]
}
```

`completed_offsets` is a list of human-message-list start indices that have been fully
processed and persisted. The file is written atomically after each batch.

**CLI additions to `seed`**:
- `--checkpoint PATH` — path to checkpoint file (default: `<log-parent>/<logname>.seed-checkpoint.json`)
- `--resume` — load checkpoint and skip completed offsets
- `--reset-checkpoint` — delete checkpoint file and start fresh (requires `--checkpoint`)

**`SeedCheckpoint` class** lives in `kryten_llm/__main__.py` (seed-internal, no public API).

### 5.3 Concurrent workers (Sortie 3, REQ-510–518)

**CLI addition**:
```
--workers N    (default: 1; seed subcommand only)
```

**Config addition** (optional; under `extractor`):
```json
"seed": {
  "worker_providers": ["extractor_local", "extractor_local_2"]
}
```

`worker_providers` names entries already present in `extractor.llm.providers`. Worker `i`
uses `worker_providers[i % len(worker_providers)]`. If `seed.worker_providers` is absent
or empty, all workers use the full provider chain (LM Studio's internal parallelism
handles distribution).

**Worker pool design**:
- One `asyncio.Queue` of `(offset, batch, batch_ts)` tuples.
- N worker coroutines, each with its own `LLMFactExtractor` instance.
- Sentinels (`None`) drain workers after all batches are enqueued.
- An `asyncio.Lock` protects checkpoint writes and `_SeedProgress.advance()`.
- `provider._persist()` is called from workers concurrently; its existing per-user
  lock handles safety without modification.
- With `--workers 1`, the queue/gather path is bypassed and the original sequential
  loop runs (preserves exact pre-Sprint-25 behaviour with only the pre-filter applied).

### 5.4 `config.example.json` update

Add `extractor_local_2` (second model slot) to the example and document `seed.worker_providers`.
Add `SaveTheRobots` and `CynthiaRothbot` to the example `observe_exclude_users`.

---

## 6. Scope

**In scope**: `kryten_llm/__main__.py`; `config.example.json`; new test files.

**Out of scope**:
- `LongTermMemoryProvider._persist` — no changes.
- `LLMManager` — no changes.
- Heuristic seed path — no changes.
- Live bot ingestion path — no changes.
- Batch-size tuning — left to operator judgment (the pre-filter effectively increases
  human-message density per LLM call without requiring a config change).
