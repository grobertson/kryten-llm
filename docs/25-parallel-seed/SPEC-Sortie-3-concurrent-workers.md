# SPEC-Sortie-3: Concurrent LLM Workers

**Sprint**: 25 — Parallel Seed + Checkpoint/Resume
**PRD**: [PRD-parallel-seed.md](PRD-parallel-seed.md)
**Status**: Planned
**Estimate**: 4h
**Depends on**: Sorties 1 and 2 (pre-filter defines batch content; checkpoint defines
resume logic that workers must respect)
**Requirements**: REQ-510 – REQ-518

---

## 1. Overview

Replace the sequential batch loop in `_seed_via_llm` with a concurrent worker pool
when `--workers N > 1`. Each worker is an independent `LLMFactExtractor` instance
that pulls batches from an `asyncio.Queue`. Workers optionally pin to specific
provider entries in `extractor.llm.providers` via a `seed.worker_providers` config
list, enabling explicit round-robin routing to multiple LM Studio model slots.

The sequential path (`--workers 1`, the default) is unchanged except for the Sortie 1
pre-filter; existing behaviour, tests, and performance characteristics are preserved.

---

## 2. Requirements

### CLI

- **REQ-510** — Add `--workers N` (type `int`, default `1`) to the `seed` subparser.
  Validated: must be ≥ 1. Values > 8 emit a WARNING (not an error).
  Add `_add_log_level` call as with other leaf parsers (already done in Sprint 24).

### Config schema

- **REQ-511** — An optional `seed` block may be added under `extractor` in the LTM
  provider config:
  ```json
  "extractor": {
    ...
    "seed": {
      "worker_providers": ["extractor_local", "extractor_local_2"]
    }
  }
  ```
  `worker_providers` is a list of provider-name strings, each of which must exist as
  a key in `extractor.llm.providers`. If absent or empty, all workers use the full
  provider chain (round-robin across the configured `provider_priority` list, or
  LM Studio's internal parallelism if pointing to one endpoint).

  This key is read only by the seed command; it has no effect on the live bot's
  extractor.

### Worker builder

- **REQ-512** — Add helper `_build_worker_extractors(ext_cfg, provider_cfg_raw, n_workers, logger)
  -> list[LLMFactExtractor]` to `__main__.py`:

  ```python
  def _build_worker_extractors(
      ext_cfg,            # ExtractorConfig Pydantic object from provider._ext_cfg
      provider_cfg: dict, # raw dict from config for the LTM provider
      n_workers: int,
      logger: logging.Logger,
  ) -> list[LLMFactExtractor]:
      from kryten_llm.components.memory.llm_extractor import LLMFactExtractor
      from kryten_llm.components.llm_manager import LLMManager

      seed_cfg: dict = provider_cfg.get("extractor", {}).get("seed", {})
      worker_provider_names: list[str] = seed_cfg.get("worker_providers", [])
      all_providers = ext_cfg.llm.providers  # dict[str, LLMProvider]

      workers: list[LLMFactExtractor] = []
      for i in range(n_workers):
          if worker_provider_names:
              name = worker_provider_names[i % len(worker_provider_names)]
              if name not in all_providers:
                  raise ValueError(
                      f"seed.worker_providers[{i % len(worker_provider_names)}]: "
                      f"'{name}' not found in extractor.llm.providers"
                  )
              providers = {name: all_providers[name]}
              priority = [name]
          else:
              providers = dict(all_providers)
              priority = list(ext_cfg.llm.provider_priority or providers.keys())

          manager = LLMManager.for_extractor(
              providers=providers,
              provider_priority=priority,
              retry_strategy=ext_cfg.llm.retry_strategy,
          )
          workers.append(LLMFactExtractor(manager, ext_cfg, logger))
      return workers
  ```

### Worker coroutine

- **REQ-513** — Add `async def _seed_worker_task(worker_id, extractor, queue, provider,
  args, exclude, progress, checkpoint, ckpt_lock, stats) -> None` to `__main__.py`:

  ```python
  async def _seed_worker_task(
      worker_id: int,
      extractor: "LLMFactExtractor",
      queue: asyncio.Queue,
      provider: "LongTermMemoryProvider",
      args: argparse.Namespace,
      exclude: set[str],
      progress: _SeedProgress,
      checkpoint: SeedCheckpoint | None,
      ckpt_lock: asyncio.Lock,
      stats: _SeedWorkerStats,
  ) -> None:
      while True:
          item = await queue.get()
          if item is None:
              break
          start, batch, batch_ts = item

          try:
              extracted = await extractor.extract(batch, "")
          except Exception as exc:
              logger.warning("Worker %d: extract failed for offset %d: %s", worker_id, start, exc)
              extracted = []

          for ef in extracted:
              if ef.target_user.lower() in exclude:
                  stats.excluded += 1
                  continue
              ef.historical_ts = batch_ts
              if not args.dry_run:
                  try:
                      await provider._persist(ef)
                  except Exception as exc:
                      logger.warning("Worker %d: persist failed: %s", worker_id, exc)
                      continue
              stats.facts += 1

          async with ckpt_lock:
              progress.advance(len(batch))
              if checkpoint:
                  checkpoint.mark_done(start)
                  checkpoint.save(args.checkpoint)
              if progress.should_report():
                  log_date = batch_ts.split("T")[0] if batch_ts else None
                  logger.info(progress.format(log_date))

          stats.batches += 1
  ```

- **REQ-514** — `_SeedWorkerStats` is a simple dataclass:
  ```python
  @dataclass
  class _SeedWorkerStats:
      batches: int = 0
      facts: int = 0
      excluded: int = 0
  ```
  Shared across workers; individual fields are only mutated inside `async with ckpt_lock`
  (atomicity guaranteed by asyncio's cooperative scheduling — no separate lock needed).

### Main loop — concurrent path

- **REQ-515** — When `args.workers > 1`, replace the sequential `for start in reversed(batch_starts)`
  loop with:

  ```python
  queue: asyncio.Queue = asyncio.Queue()
  ckpt_lock = asyncio.Lock()
  stats = _SeedWorkerStats()

  # Enqueue all pending batches (skipping already-done offsets from checkpoint)
  skipped_offsets = 0
  for start in reversed(batch_starts):
      if checkpoint and checkpoint.is_done(start):
          progress.advance(min(batch_size, len(human_messages) - start))
          skipped_offsets += 1
          continue
      batch = human_messages[start : start + batch_size]
      batch_ts = next(
          (f"{m['date']}T{m['time']}+00:00" for m in batch if m.get("date")), None
      )
      await queue.put((start, batch, batch_ts))

  if skipped_offsets:
      logger.info("Skipped %d already-completed batches (checkpoint resume).", skipped_offsets)

  # Sentinels — one per worker
  for _ in worker_extractors:
      await queue.put(None)

  # Launch workers
  tasks = [
      asyncio.create_task(
          _seed_worker_task(i, worker_extractors[i], queue, provider, args,
                            exclude, progress, checkpoint, ckpt_lock, stats)
      )
      for i in range(len(worker_extractors))
  ]
  await asyncio.gather(*tasks)

  total_batches += stats.batches
  total_facts += stats.facts
  total_excluded += stats.excluded
  file_facts = stats.facts
  ```

- **REQ-516** — When `args.workers == 1`, the existing sequential loop (with Sortie 2
  checkpoint integration) is used directly. The `_build_worker_extractors` helper is
  called with `n_workers=1` and `worker_extractors[0]` substitutes for
  `provider._extractor` in the sequential loop, ensuring the provider-routing logic
  is consistent between sequential and concurrent paths.

### config.example.json

- **REQ-517** — Add a second extractor provider entry `extractor_local_2` to demonstrate
  multi-slot configuration:
  ```json
  "extractor_local_2": {
    "name": "extractor_local_2",
    "type": "openai_compatible",
    "base_url": "http://localhost:1234/v1",
    "api_key": "...",
    "model": "gemma-4-26b-a4b-it-heretic:2",
    "temperature": 0.1,
    "max_tokens": 1200,
    "timeout_seconds": 75,
    "max_retries": 1,
    "priority": 2
  }
  ```
  Add the matching `seed` block:
  ```json
  "seed": {
    "worker_providers": ["extractor_local", "extractor_local_2"]
  }
  ```
  Add a `_comment` explaining that `worker_providers` is seed-only and has no effect
  on the live bot extractor.

- **REQ-518** — Document `--workers` and `--checkpoint / --resume` in the seed
  subcommand's help strings (already done via `add_argument` help= strings).

---

## 3. Correctness guarantees

| Concern | Guarantee |
|---|---|
| Concurrent `_persist` for different users | Safe: per-user lock inside `_persist` already serialises same-user writes |
| Concurrent `_persist` for same user | Serialised by `_persist_lock(user)` in `LongTermMemoryProvider` |
| Checkpoint file corrupted by concurrent writes | Safe: all writes inside `async with ckpt_lock` |
| `_SeedProgress` counters race | Safe: `advance()` only called inside `ckpt_lock` |
| LLMFactExtractor `_downgraded` flag | Benign race: flag is a one-way door to True; worst case, two workers both downgrade simultaneously — correct outcome |
| Queue drained before sentinels emitted | Sentinels are enqueued after all batch items; workers will consume all real items first |

---

## 4. Tests (`tests/test_seed_workers.py`)

- `test_two_workers_both_called`: with 4 batches and 2 workers, both extractors receive
  calls (neither is starved).
- `test_workers_provider_routing`: with `worker_providers = ["p1", "p2"]` and 4 workers,
  workers 0 and 2 use `p1`; workers 1 and 3 use `p2`.
- `test_workers_unknown_provider_raises`: `_build_worker_extractors` raises `ValueError`
  if a named provider is not in `ext_cfg.llm.providers`.
- `test_workers_resume_skips_done`: 3 batches, 2 already done in checkpoint; only 1
  batch is placed in the queue.
- `test_workers_facts_aggregated`: stats from all workers are combined into final totals.
- `test_workers_1_uses_sequential_path`: with `--workers 1`, the queue is not created;
  the sequential loop runs.

---

## 5. Acceptance Checklist

- [ ] `--workers N` accepted; N > 8 emits WARNING but proceeds
- [ ] 2 workers with 2 providers: each provider gets roughly half the batches
- [ ] `_persist` concurrency safety verified (per-user lock still holds)
- [ ] Checkpoint writes serialised; file not corrupted under 4 workers
- [ ] `--workers 1` produces identical results to pre-Sprint-25 (excluding pre-filter)
- [ ] `config.example.json` shows `extractor_local_2` + `seed.worker_providers`
- [ ] 6 new tests in `tests/test_seed_workers.py`, all passing
- [ ] black / ruff / mypy / pytest clean
- [ ] Manual smoke-test: `--workers 2 --checkpoint ./ckpt.json`, interrupt after ~10 batches,
  resume with `--resume`, confirm skipped count matches interrupted batch count
