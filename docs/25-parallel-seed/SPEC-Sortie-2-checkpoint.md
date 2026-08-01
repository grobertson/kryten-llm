# SPEC-Sortie-2: Checkpoint / Resume

**Sprint**: 25 — Parallel Seed + Checkpoint/Resume
**PRD**: [PRD-parallel-seed.md](PRD-parallel-seed.md)
**Status**: Planned
**Estimate**: 3h
**Depends on**: Sortie 1 (pre-filter defines the offset space)
**Requirements**: REQ-501 – REQ-509

---

## 1. Overview

Add checkpoint/resume to `_seed_via_llm` so an interrupted seed run can be restarted
from the last completed batch rather than from scratch. The checkpoint is a JSON file
written atomically after each batch. Offsets reference positions in the post-filter
human-message list so the checkpoint remains valid across restarts with the same exclude
configuration.

---

## 2. Requirements

- **REQ-501** — Add three arguments to the `seed` subparser:
  - `--checkpoint PATH` (type `Path`, default `None`): path to the checkpoint file.
    If absent, no checkpoint is written or read.
  - `--resume` (flag): load the checkpoint at `--checkpoint PATH` and skip completed
    offsets. Error if `--checkpoint` is not also provided.
  - `--reset-checkpoint` (flag): delete the checkpoint file at `--checkpoint PATH` and
    start fresh. Error if `--checkpoint` is not also provided.

- **REQ-502** — `SeedCheckpoint` is a dataclass defined in `kryten_llm/__main__.py`.
  It is seed-internal; not part of any public API.

  ```python
  @dataclass
  class SeedCheckpoint:
      version: int = 1
      file: str = ""          # absolute path of the log file being seeded
      batch_size: int = 0     # batch_max_size at checkpoint creation time
      exclude_users: list[str] = field(default_factory=list)  # sorted lowercased names
      completed_offsets: set[int] = field(default_factory=set)
  ```

- **REQ-503** — `SeedCheckpoint.load(path: Path) -> SeedCheckpoint` reads JSON and
  returns a populated instance. If the file does not exist, returns a fresh instance.
  If the file is malformed JSON, logs a warning and returns a fresh instance (never
  raises).

- **REQ-504** — `SeedCheckpoint.save(path: Path) -> None` writes the checkpoint
  atomically:
  1. Serialise to JSON (`completed_offsets` as a sorted list for stable diffs).
  2. Write to `path.with_suffix(".seed-checkpoint.tmp")`.
  3. `os.replace(tmp, path)` — atomic on POSIX and Windows (same volume).

- **REQ-505** — `SeedCheckpoint.mark_done(offset: int) -> None` adds `offset` to
  `completed_offsets`. The caller is responsible for calling `save()` afterward.
  These are separate so Sortie 3 can batch the save inside the checkpoint lock.

- **REQ-506** — `SeedCheckpoint.is_done(offset: int) -> bool` returns `True` if
  `offset` is in `completed_offsets`.

- **REQ-507** — In `_seed_via_llm`, after pre-filtering but before the batch loop,
  initialise the checkpoint:
  ```python
  checkpoint: SeedCheckpoint | None = None
  if args.checkpoint:
      if getattr(args, "reset_checkpoint", False):
          args.checkpoint.unlink(missing_ok=True)
      if getattr(args, "resume", False):
          checkpoint = SeedCheckpoint.load(args.checkpoint)
          logger.info(f"Resuming from checkpoint: {len(checkpoint.completed_offsets):,} batches already done")
      else:
          checkpoint = SeedCheckpoint()
      checkpoint.file = str(log_path.resolve())
      checkpoint.batch_size = batch_size
      checkpoint.exclude_users = sorted(exclude)
  ```

- **REQ-508** — In the batch loop, wrap each batch in:
  ```python
  if checkpoint and checkpoint.is_done(start):
      progress.advance(len(batch))   # count skipped batches in progress
      total_batches += 1
      continue
  # … extract, persist …
  if checkpoint:
      checkpoint.mark_done(start)
      checkpoint.save(args.checkpoint)
  ```

- **REQ-509** — At the end of a successful run, if a checkpoint file exists, print a
  notice: `"Seed complete. Checkpoint at {path} may be removed or kept for re-run safety."`.
  Do NOT auto-delete the checkpoint (operator choice).

---

## 3. Checkpoint file naming

Default path when `--checkpoint` is omitted: `None` (no checkpoint). The operator must
explicitly opt in. Suggested convention (document in help text):

```
--checkpoint ./seed-checkpoint.json
```

The `.seed-checkpoint.tmp` sibling is the in-flight atomic write target; it is deleted
by `os.replace()` and should never persist on disk unless the process dies mid-write
(in which case it is stale and can be deleted manually).

---

## 4. Edge cases

| Situation | Behaviour |
|---|---|
| `--resume` without an existing checkpoint file | `SeedCheckpoint.load` returns fresh instance; run proceeds normally from the start (no error — idempotent) |
| Checkpoint `batch_size` differs from current config | Log a warning: `"Checkpoint batch_size {n} ≠ current {m}; offsets may not align — consider --reset-checkpoint"` |
| Checkpoint `exclude_users` differs from current exclude | Log a warning: offsets reference the old filtered list |
| Process killed mid-write of `.tmp` | Old checkpoint survives; at most one batch is replayed on resume |
| `--reset-checkpoint` without `--checkpoint` | `argparse` error before reaching `_seed_via_llm` |

---

## 5. Tests (`tests/test_seed_checkpoint.py`)

- `test_checkpoint_save_load`: write a checkpoint, load it back, assert offsets preserved.
- `test_checkpoint_atomic_write`: verify `.tmp` file does not persist after `save()`.
- `test_checkpoint_skip_done`: seed with 3 batches, mark offsets 0 and 2 done; assert
  only batch 1 is sent to the extractor on resume.
- `test_checkpoint_progress_counts_skipped`: skipped batches still advance
  `_SeedProgress.done` so ETA remains accurate.
- `test_checkpoint_malformed_json`: malformed file → warning, fresh instance, no crash.
- `test_reset_checkpoint`: `--reset-checkpoint` deletes the file; subsequent run
  starts from scratch.

---

## 6. Acceptance Checklist

- [ ] `--checkpoint / --resume / --reset-checkpoint` accepted by argparse
- [ ] Completed batches are skipped on resume; progress counter stays accurate
- [ ] Checkpoint file is written atomically; no `.tmp` left on disk after successful write
- [ ] Warnings emitted on batch_size / exclude mismatch
- [ ] 6 new tests, all passing
- [ ] black / ruff / mypy / pytest clean
