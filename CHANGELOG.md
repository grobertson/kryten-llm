# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.10.20] - 2026-08-08

### Changed

- **`asyncpg` and `pgvector` are now core dependencies** (previously optional under
  `kryten-llm[pgvector]`). A plain `pip install kryten-llm` or `pipx install kryten-llm`
  now installs them automatically. The `[pgvector]` extra is retained for backward
  compatibility but is redundant.
- `vector_store.py`: promoted `asyncpg`/`pgvector` imports to module level; removed the
  lazy try/except that instructed users to install the optional extra.

## [0.10.19] - 2026-08-04

### Fixed

- **Release automation** (`release.yml`): added `actions: write` permission so
  `GITHUB_TOKEN` can dispatch `workflow_dispatch` events to trigger `python-publish.yml`.

## [0.10.18] - 2026-08-04

### Fixed

- **Release automation** (`release.yml`): build step is now ordered before the GitHub
  release creation so dist assets are ready to attach; added `gh release upload` to
  attach `.whl`/`.tar.gz` files directly to the GitHub release; replaced the dead
  trailing build step with an explicit `gh workflow run python-publish.yml` dispatch
  (workaround for `GITHUB_TOKEN` not being able to trigger downstream workflows).

## [0.10.17] - 2026-08-04

### Changed

- Bumped minimum `kryten-py` dependency to `>=0.17.3`.

## [0.10.16] - 2026-08-04

### Fixed

- **Zcoin currency context in fact extraction prompt** (`fact_extraction_system.j2`). The
  LLM extractor was producing vague facts like "Has less than 7.5 million of something
  (likely currency or points)" because the model had no knowledge of the channel's virtual
  currency. Fix: the system prompt now identifies **Zcoin** by name, explains its use for
  vanity items and media queuing (250,000 Zcoin per movie), and adds three rules: (1) never
  write "something (likely currency)" — always say Zcoin explicitly; (2) do not store a bare
  Zcoin balance as a durable fact — kryten-economy owns that state; (3) messages that are
  entirely a Zcoin transaction or balance check produce no facts.

- **Wrong KV key for next-queue item on startup** (`context_manager.py`). `load_initial_state`
  was fetching key `"0"` from the playlist bucket as a speculative "next item" lookup.
  Kryten-Robot never writes that key — it writes `"items"` (the full playlist as a JSON array)
  and `"current"` (now-playing). This caused a spurious `ERROR: Failed to get key 0: nats: key
  not found` on every startup even though `next_video` gracefully fell back to `None`. Fix:
  fetch `"items"`, then walk the array to find the entry whose UID follows the current UID,
  correctly resolving the next-in-queue item. Also removed a dead `if "timestamp" in current:
  pass` block left over from earlier speculative code.

## [0.10.15] - 2026-08-04

### Added

- **Media context in live fact extraction**. The live `LLMFactExtractor` now receives
  the title of the currently-playing media via a new optional `media_context` keyword
  argument threaded through `FactExtractor.extract()`, `HeuristicFactExtractor.extract()`,
  and `LLMFactExtractor.extract()`. `_flush_user` snapshots `context_manager.current_video.title`
  at batch-commit time and passes it to `_run_batch`. The `fact_extraction_user.j2`
  template renders a "Currently playing:" preamble when the title is present, enabling
  the LLM to resolve vague statements like "I love this movie" to specific titles.
  The seed path is unaffected (no media context — `media_context=None` default).

- **Cross-user memory retrieval enabled** (`config.json`). `cross_user`, `topical`,
  `room_awareness`, `ambient`, `novelty`, `callback`, and `trace` are now enabled in
  the live config. `topical` and `room_awareness` fire on `trigger`, `mention`, and
  `auto_participation`; `ambient` fires on `auto_participation` after a 20-message
  warm-up. `room_awareness` uses the authoritative Robot userlist KV (`presence_source:
  "userlist"`). `config.example.json`: fixed an invalid JSON orphan brace that made
  the file unparseable; added `top_k` to the `room_awareness` section.

- **429 rate-limit backoff with `Retry-After` support** (`llm_manager.py`,
  `models/config.py`). A new `RateLimitError` exception (carrying an optional
  `retry_after: float`) is raised for HTTP 429 responses, with the `Retry-After`
  header parsed when present. `_try_provider` gains a dedicated `except RateLimitError`
  branch that sleeps for the `Retry-After` duration (if supplied by the API) or falls
  back to the new `RetryStrategy.rate_limit_delay` field (default 60 s). Previously
  429 fell through to the generic 1-second exponential-backoff branch. `config.json`:
  added `retry_strategy` to the extractor `llm` section with `rate_limit_delay: 60.0`.

### Fixed

- **LTM eviction: `score=0.0` shadow bug** (`_enforce_cap`). When a fact was stored via
  the heuristic upsert path, `"score": fact.score` was written to metadata where
  `Fact.score` defaults to `0.0`. In `_eviction_key`, `raw_score is not None` evaluated
  `True` for the explicit `0.0`, so `quality = 0.0` — silently ignoring a
  corroboration-boosted `confidence` of 0.93 and `importance` of 7. A well-established
  user fact (`'lives in Fargo'`, conf=0.93, importance=7) was being evicted ahead of
  genuinely low-quality facts because it happened to carry the heuristic default score.
  Fix: `quality = max(score_from_metadata, confidence × 100)` so the better of the two
  signals always wins regardless of which upsert path created the record.

- **LTM eviction: importance was a pure tiebreaker**. Previously, any difference in
  `quality` between two facts completely dominated `importance`, making corroboration
  count irrelevant for eviction decisions. A fact seen 7 times was no stickier than a
  brand-new one unless their quality was exactly equal. Fix: importance is now blended
  into the composite eviction score as a log-scaled bonus (up to +20 points on the
  0–100 quality scale, normalised against a reference of `importance=10`), consistent
  with how `_rank_with_boost` weights importance during retrieval.

- **Cadence test stub missing `media_context` kwarg**. `_RecordingExtractor.extract()`
  in `tests/test_ltm_cadence.py` lacked the `media_context` keyword argument added to
  the extractor protocol when media-aware extraction was introduced. All 7 cadence tests
  were failing with `TypeError: extract() got an unexpected keyword argument
  'media_context'`. Fix: added `media_context: str | None = None` to the stub
  signature.

- **Checkpoint save `PermissionError` on Windows** (`__main__.py`). `SeedCheckpoint.save()`
  uses `os.replace()` for atomic checkpoint writes. On Windows, antivirus or a file-system
  watcher can hold a transient lock on the destination file, causing `os.replace()` to
  raise `PermissionError` (WinError 5). The error propagated through `asyncio.gather`
  and aborted the entire seed run. Fix: `save()` retries `os.replace` up to three
  times with 100 ms / 200 ms back-off. The call site in `_seed_worker_task` also catches
  any `PermissionError` that survives all retries, logs a warning (noting the batch will
  be re-processed on resume), and continues rather than crashing.

- **Quoted text extracted as high-confidence user facts** (`fact_extraction_system.j2`).
  In a media-watching chat channel, messages in quotation marks are almost always film
  or TV dialogue, character voice jokes, or parody — not genuine personal statements.
  The extraction prompt had no guidance on this. Fix: the system template now explains
  the channel context and adds three explicit rules: (1) messages that are entirely or
  predominantly quoted text produce no facts; (2) mixed messages (user's own words +
  quoted fragment) are extracted normally; (3) facts derived primarily from quoted text
  must carry confidence ≤ 0.3. Four regression tests added to `test_llm_extractor.py`
  that inspect the rendered system prompt.

- **LTM per-turn query vector re-embedded 4× per active scope** (`long_term_memory.py`).
  With `query_mode: "window"` and multiple scopes active (speaker, topical, room,
  callback), `_message_query_vector` was called once per scope — embedding the same
  8-message window up to four times in a single turn. This pushed total embedding time
  to 200–400 ms, consistently blowing the 500 ms `read_timeout_ms` budget and causing
  `LongTermMemoryProvider.provide()` to time out with no facts surfaced. Fix: `_provide_impl`
  now maintains a `_query_vec_cache: dict[int, list[float]]` keyed on `id(req)`;
  `_message_query_vector` populates the cache on first call and returns the cached vector
  on subsequent calls within the same turn; `finally` clears the entry. `read_timeout_ms`
  bumped from 500 ms to 2000 ms to accommodate the multi-scope query budget and cold-start
  ONNX JIT compilation.

- **Same-evidence guard on LTM importance bumping** (`long_term_memory.py`). The
  extraction look-back window (`_recent[-lookback:]`) intentionally overlaps between
  consecutive user batches to provide attribution context. A message appearing in two
  overlapping windows was being extracted twice, and each time it produced a DEDUP or
  RELATED hit that bumped the stored fact's importance — racing a fact's importance from
  1 to 3 within 3 minutes from a single chat line. Fix: before calling `_bump_importance`
  in both the DEDUP and RELATED branches of `_persist`, the stored `metadata["evidence"]`
  is compared against the new extraction's evidence message text. If they match, the
  bump is suppressed (re-processing artefact, not genuine new corroboration). Legacy
  records without a stored evidence string are unaffected. Five tests added to
  `test_ltm_scoring.py` (`TestSameEvidenceGuard`).

- **ONNX embedder contacts HuggingFace Hub on every start** (`embedder.py`).
  `SentenceTransformer(model_name)` unconditionally calls the HuggingFace Hub API to
  fetch the model's ETag on every construction — even when the model is already cached.
  This added startup latency and required a network connection on every restart.
  Fix: `_ensure_loaded` first tries `SentenceTransformer(model_name, local_files_only=True)`
  (no network); only on `OSError` / `ValueError` (cache miss on first install) does it
  fall back to a normal download and log the event.

- **Seed `worker_providers` config path resolution** (`__main__.py`). The
  `_build_worker_extractors` helper looked for the seed config at `extractor.seed`
  only, silently ignoring any provider list stored at `extractor.llm.seed` (the
  canonical location documented in `config.example.json`). Fix: seed config is now
  resolved as `_ext_raw.get("seed") or _ext_raw.get("llm", {}).get("seed", {})`,
  accepting either path.

- **Heist/race game commands included in seed batches** (`__main__.py`). Short
  game-participation messages (e.g. `join 100` or `!race 50 red`) were fed to the LLM
  extractor and produced spurious colour-preference and number facts. Fix: a new
  `_is_game_command()` predicate filters messages that start with `join` or `!race`
  and are shorter than 30 characters before batch assembly.

- **Hashtag emotes and standalone reactions included in seed batches** (`__main__.py`).
  Single-token messages that are CyTube image emotes (`#facepalm`) or noise reactions
  (`lol`, `rofl`, `xd`, etc.) produced no useful facts but consumed LLM context
  window. Fix: a new `_is_reaction_noise()` predicate filters these before batch
  assembly. Matched via a `#\S+` regex (hashtag emotes) and a frozen set of common
  reaction tokens (case-insensitive exact match).

- **`None` content crash in LLM chat response path** (`service.py`). After receiving
  an `LLMResponse` object from `llm_manager.generate_response()`, the handler
  extracted `llm_response_obj.content` but did not guard against it being `None`
  (possible when a provider returns a well-formed response envelope with no text
  body). This caused `AttributeError` / `TypeError` downstream in the validator and
  response formatter. Fix: an explicit `if not llm_response:` guard was added
  immediately after the content extraction; it logs a warning including provider and
  model names, records a health monitor error, logs an empty response to the response
  logger, and returns early.

## [0.10.4] - 2026-08-01

### Changed

- **Pre-batch bot filter** (Sprint 25, Sortie 1, REQ-497–500). The LLM seed path now
  filters messages from excluded users (bots) *before* assembling batches, so every
  batch slot contains a human message. Previously, bot messages occupied batch slots
  and were discarded only after the LLM call, wasting 60–70 % of extraction capacity
  on chatty channels. The post-extraction exclude check is retained as a safety net.
  Progress reporting now shows `N human messages (M bot messages filtered)` per file.
  `config.example.json`: added `SaveTheRobots` and `CynthiaRothbot` to the example
  `observe_exclude_users` list.

### Added

- **Checkpoint / resume** (Sprint 25, Sortie 2, REQ-501–509). `memory seed` gains
  three new flags: `--checkpoint PATH` (write a checkpoint JSON after every batch),
  `--resume` (skip already-completed batch offsets on restart), and
  `--reset-checkpoint` (delete the checkpoint file and start fresh). Checkpoints are
  written atomically (tmp → `os.replace`). Offsets reference the post-filter
  human-message list so they survive restarts with the same exclude configuration.
  On batch-size or exclude-list mismatch a warning is emitted rather than a crash.

- **Concurrent LLM workers** (Sprint 25, Sortie 3, REQ-510–518). `memory seed` gains
  `--workers N` (default 1). With N > 1 an `asyncio.Queue` is filled with pre-assembled
  batches and N worker coroutines run concurrently, each wrapping its own
  `LLMFactExtractor` instance. Workers are assigned providers round-robin from the
  optional `extractor.seed.worker_providers` config list (names existing entries in
  `extractor.llm.providers`); if absent all workers share the full provider chain.
  `provider._persist()` remains safe for concurrent use via its existing per-user
  `asyncio.Lock`. Checkpoint writes and `_SeedProgress` advances are serialised by a
  single `asyncio.Lock` shared across workers. `--workers 1` (default) uses the
  sequential code path with no behavioural change beyond the pre-filter.
  `config.example.json`: added `extractor_local_2` (second model slot) and
  `extractor.seed.worker_providers` example.
## [0.10.3] - 2026-07-31

### Changed

- **Reverse-chronological memory seed** (Sprint 24, Sortie 1, REQ-491–496). The
  `kryten-llm memory seed --logs` command (LLM path) now processes log files in
  newest-first order (by `st_mtime` descending) and, within each file, submits batches
  to the LLM extractor newest-batch-first. Each batch window remains internally
  chronological so the extractor receives natural conversation context. Net effect: the
  most recent facts reach the vector store within the first batch of the first file,
  giving the bot useful recency signal from the very start of a seed run instead of
  hours later. Added `_mtime_or_zero()` helper (falls back to 0.0 on `OSError` so
  unstat-able files sort last rather than crashing). The heuristic path, date
  reconstruction, and all Sprint 20.5 timestamp behaviour are unaffected. Three new
  tests in `tests/test_seed_reverse_order.py` (REQ-496).

### Added

- **`--log-level` on all `memory` subcommands** (fix applied alongside Sprint 24).
  `--log-level` previously only worked when placed before the `memory` subcommand
  (`kryten-llm --log-level DEBUG memory seed …`). The flag now also accepts placement
  after the subcommand or leaf command (`kryten-llm memory seed … --log-level DEBUG`)
  using `argparse.SUPPRESS` defaults so sub-parsers never silently overwrite a value
  set by a parent parser. Affects: `memory`, `seed`, `forget`, `stats`, `recall`,
  `eval`, `compact`, `backfill-last-seen`, `reset`.

- **Seed progress reporting** (fix applied alongside Sprint 24). Both seed paths now
  pre-parse all files upfront, log a `Total: N messages across M file(s)` summary at
  INFO level, and emit a `[done/total msgs  pct%  elapsed  ETA  log date ~YYYY-MM-DD]`
  progress line every 10 seconds via `logger.info`. Progress lines honour `--log-level`
  and count backwards through log dates when running in reverse-chronological mode.

## [0.10.1] - 2026-07-31

### Changed

- **Publish-only re-version.** `0.10.0` was committed and tagged in git but never published
  to PyPI. `0.10.1` is functionally identical to `0.10.0` and is the first *published*
  release carrying the Sprint 18–22 feature set (confidence calibration & decay hardening,
  semantic fact compaction, temporal fact awareness, temporal-accurate bulk import, and
  proactive memory injection) together with the Sprint 23 release-gate fixes (static-analysis
  and formatting clean-up, corrected `drives_participation` changelog note). No code changes
  relative to `0.10.0`. See the `[0.10.0]` block below for the full feature detail.

## [0.10.0] - 2026-07-31

### Added

- **Proactive Memory Injection** (Sprint 21, Sorties 1–4, REQ-425–444). After
  `_run_speaker_scope` returns, a fast post-retrieval check tests whether the speaker's
  top-ranked fact meets both a cosine-similarity gate and a confidence gate. When both
  pass, a `proactive_memory` `ContextFragment` is emitted so the LLM can weave the
  connection into its response without requiring an explicit mention. Default-off;
  zero pipeline change unless `context.providers[].proactive.enabled = true`.
  - **Proactive scope** (S1, REQ-425–430): `_run_proactive_scope` in
    `long_term_memory.py` issues its own `k=1` store query using the cached message
    vector (`_last_message_vec`) set by `_run_speaker_scope`. Similarity gate:
    `sim = 1 − distance`; confidence gate reads `metadata.confidence`. Both gates
    must pass or an empty list is returned. Unknown trigger types log a warning but
    are not rejected. `fire_on` defaults to `{mention, trigger_word, auto_participation}`.
  - **Template integration** (S2, REQ-431–434): `PromptBuilder` passes
    `proactive_memory` and `proactive_memory_active` into the template context.
    `trigger.j2` conditionally renders the fragment when `proactive_memory_active`
    is True, allowing LLM prompts to surface the connection naturally.
  - **Config** (S3, REQ-435–439): `proactive` block under each LTM provider config.
    `drives_participation` flag (default false); wired end-to-end in Sprint 22 so a strong
    proactive match on an auto-participation turn can override the eagerness gate and let
    the bot speak. All defaults preserve existing behaviour (enabled: false).
  - **Observability** (S4, REQ-440–444): `record_proactive_injection(triggered, similarity)`
    on `ServiceHealthMonitor` increments per-decision counters and appends a similarity
    sample to a ring buffer. `proactive_memory` fragments are also counted by the
    existing `record_memory_fragment` path so they appear in the `/metrics` fragment-type
    breakdown immediately.

- **Temporal-Accurate Bulk Import** (Sprint 20.5, Sorties 1–3, REQ-445–460). Fixes the
  `memory seed --logs` command's timestamp gap: every fact written from a historical log
  now carries historically accurate `created_at` / `last_seen` rather than the seeding
  timestamp. Prerequisite for Sprint 20 recency ranking to be meaningful on seeded stores.
  - **Log-date reconstructor** (S1, REQ-450–451): `kryten_llm/components/memory/log_date_utils.py`
    — `time_str_to_seconds` and `assign_dates`. Reads the log backward from the file's
    mtime as a date anchor, detects midnight crossings via backward time-jumps ≥ 1 hour,
    and assigns an ISO date string (`"YYYY-MM-DD"`) to each parsed chat line. Unit tests
    in `tests/test_log_date_utils.py` (18 cases).
  - **Seed path upgrade** (S2, REQ-452–455): `_parse_log_file` gains a `log_end_date`
    parameter and attaches a `"date"` field to each returned message dict using the
    reconstructor. Both `_seed_via_heuristic` and `_seed_via_llm` paths write
    `created_at = last_seen = historical_ts` instead of `datetime.now()`. LLM mode:
    `ExtractedFact.historical_ts` carries the reconstructed timestamp into `_persist`.
    Existing behaviour preserved when `log_end_date` is absent (no `--date-from-log` flag).
  - **Store reset** (S3, REQ-459): `memory reset --confirm` CLI subcommand clears the
    entire vector store and confirms the resulting fact count is 0. Without `--confirm`,
    only the current fact count is reported (safe dry-run default).

- **Temporal Fact Awareness** (Sprint 20, Sorties 1–4, REQ-405–424). Three targeted
  fixes to the recency ranking and template presentation layers. Sprint 18's
  `ConfidenceDriftSweeper` handles passive decay; this sprint improves retrieval ranking
  and temporal hedging, and fixes a long-standing gap where heuristic-mode facts never
  participated in recency ranking.
  - **Configurable recency half-life** (S1, REQ-405–409): `RetrievalBoostConfig` gains
    `recency_half_life_days: float = 0.0`. When 0, the legacy `1/(1+age_days)` formula
    is used unchanged. When > 0, `_recency_factor` uses `exp(-age_days / half_life_days)`.
    Recommended starting value: 90. Fixes `_upsert_facts` (heuristic mode) to write
    `last_seen = now` on every upsert (REQ-407) — previously absent, causing all
    heuristic-mode facts to score 0.0 on recency.
  - **Recency days on ContextFragment** (S2, REQ-410–414): `ContextFragment` gains an
    optional `recency_days: int | None` field. `_run_speaker_scope` computes it from the
    top-ranked fact's `last_seen` (or `created_at` fallback) and packs it into the fragment
    and the template data dict. `trigger.j2` can now conditionally add temporal hedging
    phrases ("you mentioned a while back…") when `temporal_hedge_enabled = true` and
    `recency_days ≥ old_threshold_days`. Temporal hedge config block: `hedge_enabled`
    (false), `recent_threshold_days` (7), `old_threshold_days` (90).
  - **Backfill CLI** (S3, REQ-415–419): `memory backfill-last-seen [--dry-run]` iterates
    all facts in the store and sets `last_seen = created_at` for any fact missing
    `last_seen`. Safe to run on a live store; dry-run reports the count without writing.
  - **Config / eval** (S4, REQ-420–424): `config.example.json` documents
    `recency_half_life_days` and the `temporal` hedging block. `tests/test_temporal_ranking.py`
    covers the recency formula (12 cases), the `last_seen` backfill, and the temporal
    hedging data path.

- **Semantic Fact Compaction** (Sprint 19, Sorties 1–4, REQ-385–404). Background sweeper
  that clusters near-duplicate facts by cosine similarity and merges each cluster into a
  single canonical fact. Default-off; zero response-path latency. Prerequisite for
  Sprint 21 proactive injection to be meaningful on long-running stores.
  - **CompactionSweeper** (S1, REQ-385–389): `CompactionSweeper` in
    `kryten_llm/components/memory/retention.py`. Fetches all facts per user,
    re-embeds fact texts, runs full pairwise union-find clustering (O(N²)), and merges
    each multi-member cluster: canonical text = highest-importance fact; summed importance
    capped at `importance_cap`; importance-weighted confidence average. Per-user user lock
    ensures no cross-user merges. `dry_run=True` logs the plan without writing. Never
    raises into the service loop.
  - **`memory compact` CLI** (S2, REQ-390–394): `kryten-llm memory compact [--dry-run]
    [--user USER] [--threshold FLOAT]`. Runs one compaction pass offline against the
    configured store. `--dry-run` shows per-cluster merge plans without writing.
    `--threshold` overrides the config value for a single run.
  - **Config + service wiring** (S3, REQ-395–399): `CompactionConfig` in `models/config.py`
    — `enabled` (false), `interval_hours` (24.0), `merge_threshold` (0.85),
    `min_facts_to_compact` (10), `importance_cap` (10000). Wired into `service.py` as a
    background task (alongside `RetentionSweeper` and `ConfidenceDriftSweeper`).
    `record_memory_facts_compacted(n)` on `ServiceHealthMonitor`.
  - **Eval fixture** (S4, REQ-400–404): `tests/test_compaction_eval.py` seeds a
    near-duplicate fixture, runs a compaction pass, and asserts Sprint 12 `recall@5`
    is not reduced post-compaction. `tests/test_compaction.py` covers the sweeper
    algorithm and merge logic (14 unit cases).

### Configuration schema additions (Sprint 21 — config-schema change)

- `context.providers[].proactive` block: `enabled` (false), `threshold` (0.80),
  `min_confidence` (0.70), `priority` (39), `fire_on` (["mention", "trigger_word",
  "auto_participation"]), `drives_participation` (false).

### Configuration schema additions (Sprint 20 — config-schema change)

- `extractor.retrieval_boost.recency_half_life_days` (0.0 — legacy formula until set > 0).
- `context.providers[].temporal` block: `hedge_enabled` (false), `recent_threshold_days`
  (7), `old_threshold_days` (90).

### Configuration schema additions (Sprint 19 — config-schema change)

- Top-level `compaction` block: `enabled` (false), `interval_hours` (24.0),
  `merge_threshold` (0.85), `min_facts_to_compact` (10), `importance_cap` (10000).

- **Confidence Calibration & Decay Hardening** (Sprint 18, Sorties 1–3). Adds empirical
  calibration tooling to the eval harness, importance-gated contradiction decay, and a
  temporal confidence drift sweep. All hardening features default off; calibration is
  a read-only eval tool with no runtime impact.
  - **Calibration metric** (S1, REQ-370–374): `score_calibration(records)` function and
    `CalibrationReport` dataclass added to `tests/eval/scorers.py`. Groups stored facts by
    confidence tier (low/mid/high) and measures whether mean importance increases with
    confidence (using corroboration count as a proxy for fact correctness). `passes_baseline`
    is True when high-confidence facts have ≥ mean importance vs low-confidence.
  - **Importance-gated decay** (S2, REQ-375–379): `importance_gated_decay: bool` config field
    (default False) under `context.providers[].confidence`. When True, effective contradiction
    decay = `decay / max(importance, 1)` — a fact corroborated 10 times decays at 1/10th the
    rate of a newly-inserted one. Floor still applied after gating.
  - **Temporal confidence drift** (S3, REQ-380–384): `ConfidenceDriftSweeper` background task
    in `kryten_llm/components/memory/retention.py`. Nudges confidence downward for facts
    dormant longer than `drift_after_days` at `drift_rate_per_day` per day, floored at
    `confidence_floor`. Controlled by new `confidence_drift` config block (default disabled).
    Complementary to contradiction decay and retention deletion.

### Configuration schema additions (Sprint 18 — config-schema change)

- Top-level `confidence_drift` block: `enabled` (false), `drift_after_days` (30.0),
  `drift_rate_per_day` (0.001), `confidence_floor` (0.1), `interval_hours` (24.0).
- `context.providers[].confidence.importance_gated_decay` (false) — per-provider flag.

 Validates and documents the
  deployment pattern for running two kryten-llm instances (primary + secondary bot) against
  a shared fact store. No new architecture — just a tested pattern and operational tooling.
  All features are backward-compatible; single-instance deployments are unaffected.
  - **Shared-store validation** (S1, REQ-340–343): `tests/test_multi_instance.py` — 12 tests
    proving that two `LongTermMemoryProvider` instances sharing a `VectorStore` correctly
    share facts (REQ-340), maintain per-user isolation (REQ-341), propagate `forget_user`
    erasure (REQ-342), and survive concurrent asyncio writes (REQ-343). A silo baseline test
    confirms separate-store isolation is the default.
  - **Deployment guide** (S2, REQ-344): `docs/MULTI_INSTANCE.md` — operator guide covering
    the embedded-Chroma danger, Chroma HTTP server setup, pgvector option, `ignored_users`
    peer exclusion, `forget.user` semantics, example systemd units, and a pre-live checklist.
  - **Store-mode observability** (S3, REQ-345): `store_mode` property on
    `ChromaVectorStore` (`"chroma-embedded"` / `"chroma-http"`) and `PgVectorStore`
    (`"pgvector"`). `FakeStore` reports `"fake"`. `MetricsServer` exposes
    `llm_memory_store_mode{mode="..."}` on `/metrics` so operators can confirm both
    instances are in a concurrency-safe mode.


  `ContextSignal` that aggregates memory richness, fact confidence, budget usage,
  and trigger priority into a `[0, 1]` float used to select a provider tier.
  All features are **default off** (`routing.enabled = false`, `signal_threshold = 0.0`);
  existing deployments see zero behaviour change.
  - **ContextSignal computation** (S1, REQ-310–314): `kryten_llm/components/memory/routing.py`
    — `ContextSignal` dataclass and `compute_signal(cs, weights) → float`. Weights are
    individually configurable (`routing.signal.*`); missing signals degrade gracefully.
    Signal is computed in `service.py` after `pipeline.build()` from fragment count, budget
    fraction, `EngagementSignals.max_importance` (confidence proxy), and trigger priority.
  - **Provider tier routing** (S2, REQ-315–319): `LLMManager.route(signal, config, preferred_tier)`
    returns the provider priority list for the turn. `economy`/`premium` tier maps are
    config-driven; `signal_threshold = 0.0` collapses to single-tier (current behaviour,
    REQ-319). Unknown providers in tiers are silently filtered; premium→economy fall-through
    on exhaustion (REQ-317). `LLMRequest.provider_list` carries the tier decision into
    `generate_response` without touching `preferred_provider`.
  - **Routing observability** (S3, REQ-320–324): `ServiceHealthMonitor.record_routing_decision`
    increments per-tier counter + appends signal sample. `MetricsServer` exposes
    `llm_routing_tier_total{tier}` counter and `llm_routing_signal_avg` / `_count` / `_sum`
    gauges on the existing `/metrics` endpoint.
  - **Per-trigger routing override** (S4, REQ-325–329): `Trigger.preferred_tier` and
    `TriggerResult.preferred_tier` pin a trigger to a specific routing tier, bypassing the
    signal threshold. Unknown tier name → warning + signal routing fallback (REQ-327).
    Default `None` preserves current behaviour (REQ-329).

### Configuration schema additions (Sprint 15 — config-schema change)

- Top-level `routing` block:
  - `enabled` (false) — master switch.
  - `signal_threshold` (0.0) — signal ≥ threshold → premium tier.
  - `tiers` ({}) — `{economy: [...], premium: [...]}` provider lists.
  - `signal.*` — `fragment_count`, `budget_fraction`, `avg_confidence`,
    `trigger_priority` weights; `fragment_count_max` cap (8).
- `triggers[].preferred_tier` (null) — per-trigger tier override.


  `confidence` dimension to the memory system. All features default to current
  behaviour — none changes visible output without explicit config.
  - **Confidence field** (S1, REQ-280–284): `_upsert_facts` (heuristic path) stores
    `confidence = score / 100`; LLM path already stored `ef.confidence`. Existing facts
    lacking the field default to 0.5 everywhere. `tests/eval/harness.seed_store` includes
    the field so the Sprint 12 eval harness can exercise it offline. `ContextFragment` gains
    an optional `confidence: float | None` field (also used by Sortie 5).
  - **Corroboration boost** (S2, REQ-285–289): `_bump_importance` (dedup/related-mention
    path) also increments confidence via `new_conf = conf + step × (1 − conf)` (exponential
    approach capped at 1.0). Default `corroboration_step = 0.05`; step = 0 is transparent.
  - **Contradiction decay** (S3, REQ-290–294): `_novelty_signal` fires a fire-and-forget
    `_apply_confidence_decay(fact_id, decay, floor)` when a contradiction is confirmed.
    Default `contradiction_decay = 0.1`; `confidence_floor = 0.1` prevents adversarial drain.
    Never adds latency to `provide()`.
  - **Confidence-weighted retrieval** (S4, REQ-295–299): `_rank_with_boost` gains a third
    axis `boost.confidence_weight × confidence`. `RetrievalBoostConfig.confidence_weight`
    defaults to 0.0 (transparent). High-confidence facts rank higher when weight > 0.
  - **Hedged template presentation** (S5, REQ-300–309): `_run_speaker_scope` computes avg
    confidence across the ranked facts and attaches it to the `user_memory` `ContextFragment`.
    `templates/trigger.j2` conditionally prefixes "I think" when
    `confidence < hedge_above AND hedge_enabled`. Default `hedge_enabled = false`.

### Configuration schema additions (Sprint 13 — config-schema change)

- `context.providers[].confidence` block: `corroboration_step` (0.05), `contradiction_decay`
  (0.1), `confidence_floor` (0.1), `hedge_enabled` (false), `hedge_above` (0.7).
- `extractor.retrieval_boost.confidence_weight` (0.0 — no change until set > 0).

 An offline evaluation
  suite that makes memory behaviour measurable and regressions detectable — no live NATS,
  Chroma, or pgvector required. All eval tests are excluded from the default `pytest` run
  and collected only via `pytest -m eval`.
  - **Fixture format & loader** (S1, REQ-250–254): JSONL corpus schema for retrieval,
    contradiction, and disclosure scenarios; `FixtureLoader` with schema validation; idempotent
    seeding via `stable_fact_id`; `FakeEmbedder` (keyword-hash, 8-D, no ONNX) and `FakeStore`
    (in-memory cosine distance). Located in `tests/eval/`.
  - **Retrieval scorer** (S2, REQ-255–259): `precision_at_k`, `recall_at_k`, and `MRR`
    functions; `score_retrieval` aggregates over the 10-scenario `retrieval.jsonl` corpus;
    suite fails if recall@5 falls below the 60% baseline. `@pytest.mark.eval` excluded from
    normal pytest.
  - **Contradiction scorer** (S3, REQ-260–264): `score_contradictions` runs the heuristic
    `_is_contradiction` detector against 20 labeled message/fact pairs in `contradiction.jsonl`;
    fails if heuristic recall < 70%. Balanced positive/negative examples.
  - **Disclosure-safety harness** (S4, REQ-265–269): hard privacy regression gate — asserts
    zero silenced-user facts appear in cross-user retrieval output across 5 scenarios, including
    fail-closed gate and empty-silenced-list cases. Any violation causes an immediate assert.
  - **Eval CLI** (S5, REQ-270–275): `kryten-llm memory eval [--fixture-dir DIR] [--json]`
    runs all three scorers, prints a Markdown summary table, and exits non-zero on any failure.
    No config file required. `kryten_llm/eval_runner.py` provides the programmatic API.
  - `pyproject.toml`: `eval` marker registered; default `addopts` excludes `@pytest.mark.eval`.

 Wires the Sprint 8–9 memory signals
  into the auto-participation speak decision so the bot fires more often when it has something
  relevant to say and stays quiet when it doesn't. All new features default to current behavior
  (no change without explicit config).
  - **Engagement score** (S1, REQ-220–225): `kryten_llm/components/memory/engagement.py` —
    `EngagementSignals` dataclass + `compute()` that produces a normalised `[0, 1]` score from
    novelty, topical similarity, ambient mood cosine, and max importance. Per-component weights
    configurable under `auto_participation.engagement`.
  - **Silent-path pre-check** (S2, REQ-230–235): cheap two-signal gate in `TriggerEngine`
    using stale cached signals (no store query, no embedder call — sub-millisecond). Blocks
    auto-participation on low-novelty or low-mood turns. Default off; cold-start always passes.
    Pre-check pass/fail recorded as a metric.
  - **Eagerness knob** (S3, REQ-240–244): `auto_participation.eagerness` threshold gates the
    auto-participation speak decision by engagement score. `force_interval` prevents permanent
    silence if the score never reaches the threshold. Default `eagerness=0` preserves current
    behavior exactly. Score-gate pass/fail recorded as a metric.
  - **Per-user depth bias** (S4, REQ-245–249): `max_bias` multiplicative factor in the
    engagement score boosts turns involving users the bot knows well (high fact count/importance).
    Default `max_bias=1.0` → no bias. Never discloses which facts are held.
  - **Signal pipeline**: `LongTermMemoryProvider` populates `last_engagement_signals` after
    each `provide()` call; the pipeline surfaces them in `build()` under `"_engagement_signals"`;
    `service.py` pops them from the context dict and forwards them to `TriggerEngine` (stale-ok
    pattern — gates the *next* auto-participation turn without adding latency to the current one).

### Configuration schema additions (Sprint 11 — config-schema change)

- `auto_participation.eagerness` (float 0–1, default 0).
- `auto_participation.force_interval` (int ≥ 0, default 0 = disabled).
- `auto_participation.engagement` block: `novelty`, `topical`, `mood`, `importance` weights,
  `max_bias`.
- `auto_participation.precheck` block: `enabled`, `min_novelty`, `min_mood_cosine`.

 Operational privacy controls for
  the long-term memory corpus. All new features are default-off or default-to-conservative.
  - **`forget.user` command** (S1, REQ-170–176): exposes the existing admin-CLI forget as an
    authorised, audited runtime command on `kryten.llm.command`. Caller rank is checked against
    configurable `memory_commands.forget_min_rank` (default 2 = moderator). Every deletion is
    audit-logged. Returns `{"deleted": N}`.
  - **`inspect.user` command** (S5, REQ-210–215): read-only command that returns a user's stored
    facts projected to `{summary, category, created_at, importance}` — no raw embeddings.
    Self-inspection is always allowed; inspecting others requires `forget_min_rank`.
    Capped at `memory_commands.inspect_limit` (default 50).
  - **Retention sweeper** (S2, REQ-180–186): configurable background task that periodically
    expires facts older than `retention.max_age_days` with importance ≤
    `retention.expire_below_importance`. Default disabled; fail-safe (errors never crash the loop);
    emits a `memory_facts_expired_total` metric on each sweep.
  - **PII / secret scrubbing hardening** (S3, REQ-190–195): extends the write-gate
    (`is_safe_message`) with: API key / secret token prefixes (`sk-…`, `ghp_…`, `sk_live_…`,
    etc.), long hex strings (≥ 32 chars), JWT-like blobs, credit-card numbers with Luhn
    validation, IPv4/IPv6 addresses, and explicit geolocation phrases. A labeled fixture corpus
    (`tests/fixtures/pii_corpus.jsonl`) enforces precision ≥ 85% / recall ≥ 90%.
  - **Self-service forget / inspect** (S4, REQ-200–213): when `self_service.enabled` is true,
    users can say `forget me` (configurable phrase) in chat to delete their own facts, or
    `what do you know about me` to receive an in-chat summary. Identity is implicit in the
    CyTube event username; scope is always self-only. Rate-limited by `cooldown_seconds`.
    Default disabled.

### Configuration schema additions (Sprint 10 — config-schema change)

- `retention` block: `enabled` (false), `interval_hours`, `max_age_days`,
  `expire_below_importance`, `batch_size`.
- `memory_commands` block: `forget_min_rank` (2), `inspect_limit` (50).
- `self_service` block: `enabled` (false), `phrase`, `inspect_phrase`, `cooldown_seconds`.
  See `config.example.json` for the new blocks.


  associative-recall surfaces; all default to Sprint 8 behavior.
  - **Observability** (S5): Prometheus `llm_memory_*` series — per-fragment emission counts,
    shadow-mute gate fail-closed events, silenced-user exclusions, presence fallbacks, and
    read-path latency — via the existing metrics server. Optional per-turn `trace` (names/sizes
    only unless `trace.include_content`); default off, no fact content in default logs/metrics.
  - **Cross-user boost ranking** (S1): topical/room/ambient results re-ranked by
    importance+recency (the Phase 7f boost), not just similarity; per-scope `boost_ranking`.
  - **Userlist-based presence** (S2): room-awareness can use the robot's authoritative userlist
    KV (`presence_source: "userlist"`), falling back to the recent-activity heuristic on failure.
  - **Attention pooling** (S4): pluggable `pooling_strategy` (`mean`/`recency`/`attention`) for
    the window query vector and the ambient mood, weighting messages by length/recency/centrality.
  - **Embedding-based contradiction** (S3): `novelty.contradiction_method: "embedding"` scores
    opposition against a negated form of the nearest fact (with a cold-start guard and heuristic
    fallback); read-only, never stores facts.
- **Associative memory — cross-user foundation & topical recall** (Sprint 8, Sorties 0–1).
  The long-term memory provider can now surface facts from the current *discussion*, not just
  the speaker. Opt-in and default-off via `context.providers[].cross_user.enabled`.
  - `topical` recall: on configured trigger types (default `auto_participation`), retrieves
    facts similar to the current message regardless of author and injects a `topical_memory`
    fragment with per-fact attribution (`• [alice] …`).
  - `ModerationGate`: cross-user recall excludes users currently under a moderation action
    (default `ban`/`smute`/`mute`), obtained via kryten-moderator's `entry.list` command
    (`kryten.moderator.command`) — no direct KV access. Fail-closed by default if the
    moderator can't be reached (`moderation_gate.fail_closed`).
  - Vector-store `where` filters now support `$in` and `$ne` operators (pgvector +
    Chroma), fully parameterised.
  - Shadow-muted messages remain excluded from the write path (they never reach `observe()`),
    so silenced users are neither learned from nor surfaced.
- **Associative memory — recall shaping & signals** (Sprint 8, Sorties 2–7). All default-off.
  - `room_awareness` (Sortie 2): facts for other people currently in the room, from recent
    chatters (`room_memory`); silenced users excluded.
  - `retrieval.query_mode: "window"` (Sortie 3): pool the last N chat messages into the query
    vector so recall tracks the ongoing topic, not just the last line.
  - `category_routing` (Sortie 4): present the speaker's facts as labeled sections by
    category, or one independently-trimmable fragment per category.
  - `callback` (Sortie 5): occasionally resurface an old, important, off-topic fact
    (`callback_memory`), probabilistic + cooldown-limited; optional cross-user `scope: "any"`.
  - `novelty` (Sortie 6): read-only `memory_signal` fragment when a message is novel (far from
    everything stored) or a likely contradiction (close-but-opposite); never stores facts.
  - `ambient` (Sortie 7): an EWMA "mood vector" of recent chatter seeds whole-room recall on
    auto-participation once warmed up (`ambient_memory`); shadow-muted messages never shape it.
- **PostgreSQL + pgvector vector-store backend** (`store.backend: "pgvector"`) as a
  concurrency-safe alternative to the embedded Chroma `PersistentClient`, which is
  single-process only and corrupts its HNSW index under concurrent writes. The new backend
  lets the live bot and a long-running `memory seed` job share one database safely, and adds
  transactional integrity plus SQL/JOIN filtering. Enabled via the `kryten-llm[pgvector]`
  extra (`asyncpg`, `pgvector`). Connection config supports `dsn_env` (preferred),
  `dsn`, or discrete `host`/`port`/`user`/`dbname` with `password_env`. See
  `docs/pgvector-setup.md` and `sql/`.
- **Chroma client/server mode** (`store.http_host`/`http_port`) for concurrency without
  switching backends — both processes connect to one `chroma run` server.
- Forward-looking movie/TV recommendation schema sketch for kryten-webqueue
  (`sql/010_webqueue_items.sql`), designed to share the pgvector database.

### Changed

- Per-user cap eviction is now backend-agnostic: it uses the store's `get_all` / `delete_ids`
  methods instead of reaching into Chroma's private `_collection`, so eviction works for both
  the Chroma and pgvector backends.

### Fixed

- pgvector `upsert` now binds `created_at` as a `datetime` (parsed from the ISO string) rather
  than a raw string, which asyncpg rejected for `timestamptz` parameters.

## [0.9.4] - 2026-07-24

### Fixed

- **ChromaDB similarity gate was always rejecting facts** — the collection was created with
  ChromaDB's default L2 distance metric, which produces distances > 1.0 for unit-normalised
  vectors. The gate formula assumed cosine distances in [0, 2]. All collections are now created
  with `hnsw:space: cosine`; startup raises `RuntimeError` with a clear migration hint if an
  existing collection has the wrong metric.

- **LTM cap evicted the oldest facts instead of the lowest-quality ones** — the eviction key
  now sorts by `(score, importance, confidence, created_at)` ascending, so the weakest facts
  are evicted first regardless of age. Age is a tiebreaker only.

- **LLM extractor only extracted facts for the message-triggering user** — the `_focus_only`
  flag and the per-user filter in `_to_facts()` have been removed. The system prompt and user
  prompt now ask for facts about *any* user visible in the window, and all valid attributions
  are returned.

- **`observe()` was only called on triggered messages** — the LTM observation pipeline now
  fires on every accepted chat message (moved before the trigger check), not just the ones
  that produced an LLM response. This means facts are collected from all conversation, not
  only the moments the bot was directly addressed.

- **Media-change trigger fired on reconnect/restart** — `TriggerEngine.check_media_change()`
  now skips the LLM call when the incoming title matches the already-tracked title, eliminating
  false-positive "media changed" responses on reconnect.

- **Shadow-muted CyTube users were processed normally** — CyTube sets `meta.shadow: true` on
  `chatMsg` events from shadow-muted users but leaves filtering to clients. Messages with
  `meta.shadow=True` are now dropped in `MessageListener.filter_message()` before reaching
  the trigger engine or LTM pipeline. Requires kryten-py ≥ 0.17.1 (new `ChatMessageEvent.shadow`
  field); a `getattr` fallback keeps the service running against older installed versions.

- **Every message was added to chat history twice** — `ChatHistoryProvider` had `writes=True`
  and an `observe()` that called `context_manager.add_chat_message()`. `service.py` was already
  doing the same call synchronously one step earlier (before prompt building, so the current
  message is in context). `ChatHistoryProvider` is now read-only (`writes=False`); history
  writes happen in exactly one place.

- **ONNX / sentence-transformers log noise** — noisy third-party loggers
  (`sentence_transformers`, `transformers`, `onnxruntime`, `huggingface_hub`, `filelock`, `PIL`)
  are now suppressed to WARNING level at module import time in the embedder.

- **`mediaUpdate` events flooded DEBUG logs** — position updates are now logged at most once
  every 10 events (counter-based throttle).

### Added

- **`ignored_users` config field** — top-level `list[str]` (default `[]`). Messages from any
  listed username are silently dropped by `MessageListener` before any processing (LTM
  observation, trigger check, response generation). Case-insensitive. Set to `["ZcoinBank"]`
  in the shipped `config.json` to silence the economy bot entirely.

- **Before/after debug logging for all fact write paths** — at `--log-level DEBUG`, every
  fact mutation now logs what changed:
  - `_upsert_facts` (heuristic): per-fact line with user, category, summary snippet, score
  - `_persist_extracted_fact` (LLM): `DEDUP`/`RELATED`/`NEW` prefix with existing/new summary
    and similarity/novelty scores
  - `_bump_importance`: `importance N → M` with the triggering evidence snippet
  - `_enforce_cap`: per-evicted-fact line with category, summary, score, importance,
    confidence, and creation date

- **`observe_exclude_users` in LTM write config** — users listed here are excluded from the
  LTM observation (write) path only; they are still visible in chat history. Defaults to `[]`;
  set to `["ZcoinBank", "VHSOracle"]` in the shipped `config.json`.

### Changed

- **Fact-extraction LLM prompts moved to Jinja2 templates** — `_SYSTEM_PROMPT`, the per-batch
  user prompt, and the JSON repair re-prompt are now rendered from
  `templates/fact_extraction_system.j2`, `templates/fact_extraction_user.j2`, and
  `templates/fact_extraction_repair.j2` respectively. This makes all LLM prompts in the service
  editable without touching Python code. Inline fallbacks are retained if templates cannot be
  loaded at runtime.

- **Removed game-context explanation block from `trigger.j2`** — the in-prompt description of
  ZcoinBank's heist/racing mechanics has been removed now that ZcoinBank messages are fully
  dropped at the listener level.

- **Removed "join" / "!race" game participation token filters from `MessageListener`** —
  superseded by `ignored_users`.

- **kryten-py dependency bumped to ≥ 0.17.1** — `ChatMessageEvent.shadow` is required for the
  shadow-mute filter to function.

## [0.9.3] - 2026-07-22

*(Rolled into 0.9.4 — never published to PyPI.)*

## [0.9.2] - 2026-07-19

### Fixed

- **Critical: long-term memory facts were never injected into LLM prompts** — `PromptBuilder`
  extracted `chat_history`, `current_video`, etc. from the context dict but silently discarded
  the `user_memory` key returned by `LongTermMemoryProvider`. The `trigger.j2` template also
  lacked a `{% if user_memory %}` block. Both gaps are now closed: facts retrieved from ChromaDB
  are passed to the template and rendered in every prompted response.
- **`memory seed` log parser matched zero lines** — `_LINE_RE` and `_SERVER_RE` were written for
  a `[bracketed-timestamp] <user> msg` format; actual CyTube logs use `HH:MM:SS <user>: msg`.
  Both regexes updated to match the real format.

### Added

- **`memory recall` CLI subcommand** — simulates the provider read path from the command line:
  `uv run kryten-llm memory recall --user <name> --query <text> [--top-k N] [--min-similarity F]`.
  Shows exactly which facts would be surfaced for a given user and query, with similarity scores,
  category, and seed score for each result. Facts excluded by the similarity gate are also shown
  with a hint to lower `--min-similarity`.
- **LTM debug logging in service** — at `--log-level DEBUG`, each response now logs either the
  full `user_memory` block injected for the triggering user, or a "no facts surfaced" note, with
  a correlation ID for tracing across log lines.

### Improved

- **`memory seed` output** — replaced per-fact tqdm progress bars with a clean per-user summary
  (`username: N fact(s) written`). Also batches all embeddings for a user into a single
  `embedder.embed()` call instead of one call per fact.
- **Embedder tqdm suppressed** — `show_progress_bar=False` passed to both `SentenceTransformer`
  `.encode()` calls so batch-progress bars never appear in CLI or service output.

## [0.9.1] - 2026-07-16

### Fixed

- **Release fix**: v0.9.0 tag pre-existed before the PR merge, causing Release Automation to skip
  creating the GitHub Release and the PyPI publish workflow never fired. This patch bump re-runs
  the full release pipeline so the package is available on PyPI.

## [0.9.0] - 2026-07-15

### Added

- **Phase 7f — LLM-Driven Fact Extractor (independent connection, scored extraction)**
  - `LLMFactExtractor` (`kryten_llm/components/memory/llm_extractor.py`) — a pluggable,
    swap-by-config alternative to the heuristic extractor. Sends a look-back window of chat to a
    **dedicated LLM connection** and emits paraphrased, attributed, scored candidate facts as
    strict JSON (REQ-010 to REQ-015).
  - `ExtractedFact` dataclass carrying the LLM-emitted `confidence` and `sentiment` scores
    (side-effect free; `novelty`/`importance` remain the provider's responsibility, REQ-010).
  - **Structured output** with configurable mode `auto | json_schema | prompt`: native
    `response_format` json-schema when supported, with a one-time automatic downgrade to prompt
    mode and a single bounded JSON-repair re-prompt; unrepairable output drops the batch and logs
    (fail-open, REQ-013/REQ-014).
  - **Dedicated, isolated extractor connection** via `LLMManager.for_extractor(...)`: the
    extractor's providers live under `extractor.llm` and load into a *separate* `LLMManager`
    with no reference to `llm_providers` / `default_provider`. A misconfigured `extractor.llm` is
    a hard error, never a silent fallback (REQ-001/REQ-002).
  - **Scoring & persistence** in `LongTermMemoryProvider`: confidence gate (REQ-030), mechanical
    `novelty = 1 − similarity` (REQ-032), dedup/merge on near-duplicates (REQ-033), related-mention
    salience (REQ-034), novel insert with `importance = 1` (REQ-035), capped monotonic `importance`
    (REQ-036), extended fact metadata `confidence|sentiment|novelty_at_write|importance|last_seen|
    embedder_id` (REQ-038), and importance+recency retrieval boost (REQ-037).
  - **Extraction cadence**: per-user message batching with size- and idle-based flush, a heuristic
    pre-gate, off-critical-path background execution, and bounded in-flight batches per user
    (REQ-020 to REQ-023, CON-004).
  - New config models under `kryten_llm/models/config.py`: `ExtractorConfig`, `ExtractorLLMConfig`,
    `StructuredOutputConfig`, `AttributionConfig`, `SentimentConfig`, `ScoringConfig`,
    `CadenceConfig`, `RetrievalBoostConfig`.
  - `ChromaVectorStore.get_metadata` / `update_metadata` for metadata-only importance updates.
  - Documentation: LLM-extractor section in `docs/MEMORY_SETUP.md` and a fully-documented
    (disabled-by-default) example in `config.example.json`.

### Changed

- `LLMRequest` gains an optional, backward-compatible `response_format` field; the
  OpenAI-compatible call path forwards it only when set (message generation is unaffected).
- `LLMRequest.temperature` / `max_tokens` are now optional (`None`): when unset, the selected
  provider's own configured values are used (each provider in a fallback chain honours its own
  sampling settings). Callers that pass explicit values are unchanged. Incidentally, the
  media-change response path — which previously omitted these and fell back to the `LLMRequest`
  hardcoded defaults — now correctly uses its provider's configured `temperature`/`max_tokens`.

### Fixed (post-implementation review hardening)

- **CON-001 privacy gate is now unconditional.** Messages failing the safety gate are dropped
  *before* entering the extraction look-back window, so PII can no longer reach the extractor LLM
  as context (previously the safety check only ran under `heuristic_pregate`, and unsafe messages
  could still ride along in the attribution window).
- **Look-back window is trimmed to `attribution.lookback_messages`** before being sent to the
  extractor (previously the whole rolling buffer, up to `batch_max_size * 2`, was sent) (REQ-011/023).
- **Per-user extraction buffer is now bounded** (`batch_max_size * max_inflight_batches_per_user`),
  so a hung/slow extractor deferred by the in-flight cap can no longer grow it without limit (CON-004).
- **Importance counter is race-free**: a per-user lock serialises the query→decide→write critical
  section in `_persist`, keeping dedup decisions and the `importance` counter consistent under the
  concurrent batches allowed by `max_inflight_batches_per_user`.
- **Retrieval boost is effective**: in LLM mode the provider over-fetches candidates before applying
  the importance/recency boost, so salient facts just outside the pure-similarity top-K can surface
  (REQ-037).
- `EXTRACTOR_REGISTRY` + `register_extractor` added (spec §4.3): extractors self-register, unknown
  `extractor.type` values fail fast with the list of known types, and the type is validated before
  any embedder/store construction.

### Notes

- The LLM extractor is **opt-in**: it is active only when `long_term_memory` is enabled **and**
  `extractor.type == "llm"`. The default heuristic extractor reproduces Phase 7 behaviour exactly
  (CON-002), so existing deployments are unchanged.

## [0.8.0] - 2026-07-12

### Added

- **Phase 7 — Pluggable Context Providers & Long-Term Memory (ChromaDB)**

  #### Context provider framework (Phase 7a)
  - New `ContextProvider` protocol, `ContextFragment`, and `ContextRequest` dataclasses
    (`kryten_llm/components/context/base.py`).
  - `ContextPipeline` registry/orchestrator that loads providers from config, merges fragments,
    enforces a global character budget (trimming lowest-priority fragments first), and is
    fail-open per provider (REQ-001 through REQ-007).
  - `VideoContextProvider` and `ChatHistoryProvider` built-in providers that wrap the existing
    `ContextManager` — identical output to Phase 6 when memory is disabled (REQ-007).
  - `service.py` now builds a `ContextPipeline` on startup and uses it for both observing
    (off the critical path) and building context per request.
  - Backwards-compatible: if `context.providers` is absent from config, the pipeline defaults
    to `[video, chat_history]` (REQ-007).

  #### Memory core (Phase 7b)
  - `Embedder` protocol with `OnnxEmbedder` (in-process, default) and
    `OpenAICompatibleEmbedder` (LM Studio / Ollama / OpenAI) backends (REQ-020, REQ-021).
  - `VectorStore` protocol with `ChromaVectorStore` implementation.  Embedder-identity
    guard on collection open — hard-fails if the embedder changes (REQ-022).
  - `Fact` dataclass and `FactExtractor` protocol (REQ-030).
  - `HeuristicFactExtractor` — pattern-matching extractor salvaged from the
    `user-extraction/factfinder.py` prototype: candidate filter, scorer, categoriser,
    deduplicator (REQ-031).
  - `safety.py` privacy gate: blocks messages containing emails, URLs, phone numbers,
    6+ digit strings, address keywords, drug references, and explicit age disclosures
    from being stored as facts (CON-001).  **Bug fix**: drug and explicit-age branches
    now return `False` (exclusionary) — the prototype incorrectly returned `True`.
  - `EMBEDDER_REGISTRY`, `VECTOR_STORE_REGISTRY`, and `PROVIDER_REGISTRY` for
    extensibility.

  #### Seeding CLI (Phase 7c)
  - `kryten-llm memory seed --logs <glob> [--dry-run]` — bulk-imports facts from
    historical chat log files; idempotent via stable SHA-based fact IDs (REQ-040, REQ-041).
  - `kryten-llm memory forget <user>` — deletes all facts for a user (CON-003, REQ-042).
  - `kryten-llm memory stats` — shows total fact count (REQ-042).
  - Progress summary printed on completion (GUD-003).

  #### Live long-term memory provider (Phase 7d)
  - `LongTermMemoryProvider` context provider: observe path (async, fire-and-forget),
    provide path (read-timeout-bounded, fail-open), per-user fact cap enforcement (REQ-010
    through REQ-016, GUD-001, GUD-002).

  #### Pluggable backends / packaging (Phase 7e)
  - Optional `[memory]` install extra: `pip install kryten-llm[memory]` adds
    `chromadb` and `sentence-transformers` (CON-005).
  - `openai_compatible` embedder backend for remote / cross-network embedding servers.
  - Embedder-identity mismatch is detected at collection-open time and raises loudly
    rather than silently mixing vector spaces (REQ-022).

  #### Configuration
  - `context.providers` list added to `ContextConfig` (optional, default `null`).
  - `config.example.json` updated with the long-term memory provider block
    (`enabled: false` by default — opt-in per CON-002).

  #### Tests
  - `tests/test_memory_safety.py` — 40 tests for the PII safety gate including all
    exclusionary categories and the prototype bug fix.
  - `tests/test_heuristic_extractor.py` — tests for scoring, categorisation, candidate
    filtering, stable IDs, deduplication, and the full extractor async interface.
  - `tests/test_context_pipeline.py` — pipeline fail-open, budget trimming, write routing,
    default provider instantiation, and backwards-compatible context shape.

### Changed

- **kryten-py alignment**: Raised the minimum `kryten-py` requirement to `>=0.17.0`
  to match the deployed library and its built-in outbound chat throttling.
- **Chat throttling**: The service now forwards `chat_min_delay` and `chat_jitter`
  from its config into the `KrytenConfig` used by `KrytenClient`, so the library's
  global anti-flood spacing between `send_chat`/`send_pm` calls is configurable
  instead of relying on hidden defaults.
- **Split-message pacing**: Multi-part responses now subtract the library's
  `chat_min_delay` baseline from `split_delay_seconds` so the two delays no longer
  stack; effective spacing between parts stays at ~`split_delay_seconds`.
- **Config**: Surfaced top-level `chat_min_delay` (default `1.0`) and `chat_jitter`
  (default `0.5`) in `config.json` and `config.example.json`.

### Fixed

- **Mypy** — resolved 25 type errors introduced with Phase 7 code so the full CI
  matrix (`3.10 / 3.11 / 3.12`) passes cleanly with `warn_return_any = true`:
  - `vector_store.py`, `embedder.py`: typed `_client`, `_collection`, and `_model`
    attributes as `Any` (chromadb / sentence-transformers types are not always
    available at type-check time); fixed `# type: ignore` comments to cover both
    `import-not-found` and `import-untyped` error codes for optional deps.
  - `base.py`, `embedder.py`, `vector_store.py`: changed provider/embedder/store
    registries from `dict[str, type]` to `dict[str, Any]` so `from_config` calls
    on registry entries type-check cleanly; factory functions use `cast()` on the
    return value.
  - `command_handler.py`: added `TYPE_CHECKING`-guarded import of `LLMConfig` and
    typed the `get_config` callback as `Callable[[], LLMConfig]`, allowing
    `_require_config()` to return `LLMConfig`; `model_copy()` results are now cast
    so downstream attribute access is fully typed; fixed sort-key lambda annotation.
  - `service.py`: typed `_context_pipeline` attribute as `ContextPipeline | None`
    (imported under `TYPE_CHECKING`) to resolve the incompatible-assignment and
    `None`-attribute errors.
- **Black** — reformatted 8 source files (`pipeline.py`, `embedder.py`,
  `heuristic_extractor.py`, `vector_store.py`, `long_term_memory.py`,
  `health_monitor.py`, `metrics_server.py`, `service.py`) that were added in Phase 7
  without a prior `black` pass.
- **Docs** — added `docs/MEMORY_SETUP.md` covering installation, configuration
  reference, CLI usage, NATS command API, privacy/safety gate, and operational notes
  for the Phase 7 long-term memory subsystem.
- **CI** — the `[memory]` optional extra now only installs on Python 3.11+ in the
  CI matrix; `onnxruntime >= 1.24` (a transitive dep of `sentence-transformers`)
  does not ship Python 3.10 wheels. The base package continues to support Python
  3.10+; the `[memory]` extra requires Python 3.11+.

## [0.7.0] - 2026-03-14

### Added

- **Expanded Prometheus Metrics**: Comprehensive observability for Grafana dashboards
  - Trigger metrics: fires by type (mention/trigger_word/auto_participation/media_change),
    fires by name, trigger check-to-fire ratio
  - Per-user response counters for tracking top chatters
  - Rate limit hit counters by reason, cooldown blocks by type (global/user/mention/trigger)
  - Token usage tracking by provider/model with prompt, completion, and total breakdowns
  - Average tokens per request gauges (prompt and completion separately)
  - Response time percentiles (p50/p90/p99/avg) per provider/model
  - Response length statistics (avg/max/min characters)
  - Validation failure counters by reason
  - Spam detection counters by reason
  - Media change tracking (observed vs triggered)
  - Live rate limiter window gauges (current vs configured max per minute/hour)
  - Configuration boundary metrics as Grafana threshold guide marks
    (max message length, validation min/max, user max per hour)
- **Grafana Dashboard**: Full `data/grafana-llm-dashboard.json` with 40+ panels across 8 rows
  - Service Overview: status, NATS, uptime, error rate, message/response counts
  - Activity Over Time: messages/responses rate, trigger fires by type (stacked)
  - LLM Provider Performance: status lights, response time percentiles, request/failure rates
  - Token Usage & Costs: avg tokens, cumulative usage, distribution donuts, response length
    with config limits as threshold markers
  - Triggers & Engagement: type distribution, by-name bar gauge, fire rate gauge, top chatters
  - Rate Limiting & Cooldowns: blocks by reason, current/max gauges, cooldown breakdown
  - Spam & Validation: totals, by-reason breakdowns, trend lines
  - Media & Context: media changes, chat history buffer, context log depth
  - Configuration Boundaries: table of active config limits for reference
- **Token Breakdown in LLMResponse**: Added `prompt_tokens` and `completion_tokens` fields
  to `LLMResponse` dataclass, extracted from OpenAI API usage response

### Changed

- **Health Monitor**: Extended `ServiceHealthMonitor` with 15+ new recording methods for
  fine-grained metric collection across the entire message processing pipeline
- **Metrics Server**: Complete rewrite of `_collect_custom_metrics()` — now emits 50+
  Prometheus metrics organized into logical sections (core, providers, triggers, rate limits,
  tokens, response times, lengths, validation, spam, media, users, config boundaries)
- **Health Endpoint**: `_get_health_details()` now includes trigger fires, rate limit hits,
  spam detected, validation failures, media changes, and unique user count
- **Service Pipeline**: Instrumented all pipeline decision points with metric recording —
  trigger check/fire, spam detection, rate limit blocks, cooldown hits, LLM response details,
  validation failures, user response tracking, and media change events

## [0.5.1] - 2026-03-10

### Fixed

- **Heartbeat Publishing**: Fixed service heartbeats never being sent to NATS
  - `ServiceConfig` was not being constructed from `service_metadata`; `self.config.service`
    was always `None` because the `model_dump()` transform that maps `service_metadata` →
    `service` is only invoked during serialization, not during `KrytenClient` construction
  - Now explicitly builds a `ServiceConfig` from `service_metadata` fields and passes it to
    `KrytenConfig`, enabling kryten-py's built-in heartbeat, lifecycle, and discovery systems
  - Health and metrics ports from `MetricsConfig` are now forwarded to `ServiceConfig`

### Changed

- **Documentation**: Corrected NATS subject format in README and DEPLOYMENT docs
  - Heartbeat subject is `kryten.lifecycle.llm.heartbeat` (not `kryten.heartbeat.llm`)
  - Default heartbeat interval is 10s, not 30s (30s is the kryten-py default; the LLM
    service overrides it via `heartbeat_interval_seconds` in `service_metadata`)
- **DEPLOYMENT.md**: Expanded `service_metadata` example with all configurable fields

## [0.4.0] - 2025-12-31

### Changed
- **Release**: Minor version bump for coordinated ecosystem release.

## [0.3.4] - 2025-12-31

### Fixed

- **CI/CD**: Fixed GitHub Actions workflow to trigger on tag pushes
  - Added `push: tags: ['kryten-llm-v*', 'v*']` trigger to `python-publish.yml`
  - Ensures PyPI release runs automatically when a version tag is pushed

## [0.3.3] - 2025-12-31

### Maintenance

- **Code Standardization**: Full codebase standardization
  - Applied `black` formatting to all files
  - Resolved all `ruff` linting issues
  - Fixed `mypy` type checking errors
  - Updated configuration to handle missing type stubs for `kryten` package

## [0.3.2] - 2025-12-30

### Fixed

- **Version Consistency**: Aligned __init__.py version with pyproject.toml

## [0.3.1] - 2025-12-23

### Fixed

- **Missing Changelog Entry**: Added missing changelog entry for version 0.3.0
  - Version 0.3.0 was released without proper changelog documentation
  - This patch ensures all releases are properly documented

## [0.3.0] - 2025-12-23

### Fixed

- **KV Store JSON Serialization**: Fixed JSON parsing error in trigger engine state persistence
  - Added `as_json=True` parameter to `kv_put` call for proper serialization
  - Ensures media state is correctly saved and loaded from NATS JetStream KV store
- **NATS Subject Construction**: Addressed manual subject construction findings from audit report
  - Updated heartbeat.py to use `normalize_token` for service name normalization
  - Added subject_builder import to service.py for future lifecycle subject improvements
- **Service Shutdown**: Fixed RuntimeError on Ctrl+C shutdown
  - Wrapped metrics server stop in try/except block to handle unregistration errors

### Changed

- **Version Management**: Updated to version 0.3.0
  - pyproject.toml is now the single source of truth for version
  - Version automatically synced to __init__.py via manage_version.py script
  - Config files properly ignored by git (config.json, config-*.json)

## [0.2.6] - 2025-12-22

### Added

- **Media Change Triggers**: Added support for triggering responses on significant media changes
  - Configurable duration threshold (default 30 mins)
  - Context-aware prompts with previous media and chat history
  - State persistence across restarts
- **Context-Aware Triggers**: Added recent chat history to trigger contexts
  - Efficient deque-based message buffering
  - Configurable history depth
- **Version Management**: Centralized versioning in `pyproject.toml`
  - Automated sync to `__init__.py`
  - Version consistency verification tests

## [0.2.4] - 2025-12-13

### Fixed

- **ChannelConfig Access**: Fixed dict-style access `channel_config["channel"]` to attribute access `channel_config.channel`
  - Matches kryten-py's Pydantic ChannelConfig model
- **Logging Conflict**: Renamed `message` to `original_message` in error handler's log extra
  - Fixes `KeyError: "Attempt to overwrite 'message' in LogRecord"` error

## [0.2.3] - 2025-12-13

### Changed

- Re-release of 0.2.2 with version sync fix included in package

## [0.2.2] - 2025-12-13

### Fixed

- **Shutdown Flush Timeout**: Updated kryten-py dependency to >=0.9.4
  - Fixes "nats: flush timeout" error on service shutdown
  - kryten-py 0.9.1+ includes proper timeout handling in disconnect()
- **Version Sync**: Service version now sourced from `__version__` in `__init__.py`
  - Version reported to kryten-robot stays in sync with package version
  - Config version is overridden at runtime to match package version
  - Simplified version handling (removed VERSION file reading)

## [0.2.1] - 2025-12-13

### Fixed

- **Robot Startup Re-registration**: Now subscribes to `kryten.lifecycle.robot.startup`
  - Service re-announces itself when kryten-robot restarts
  - Fixes "Heartbeat from unregistered service" warnings
  - Handler already existed but subscription was missing

## [0.2.0] - 2025-12-12

### Fixed

- **Windows Signal Handling**: Added platform detection for proper signal handler registration
  - Uses `signal.signal()` on Windows instead of `loop.add_signal_handler()`
  - Prevents `NotImplementedError` on Windows startup

- **ChannelConfig Access**: Fixed attribute access for channel configuration
  - Changed from dict-style `channel_config['domain']` to attribute access `channel_config.domain`
  - Matches kryten-py's Pydantic model structure

- **NATS Anti-Pattern Removal**: Removed all direct NATS client access
  - Replaced `self.client._nats.subscribe()` with `self.client.subscribe()`
  - Updated ContextManager to accept KrytenClient instead of raw NATS client
  - All NATS operations now go through kryten-py wrappers

### Changed

- **kryten-py Dependency**: Updated to require kryten-py >= 0.9.0
  - Uses new `subscribe()` method from KrytenClient

## [0.1.1] - Unreleased

### Added
- Initial skeleton implementation
- Basic service structure with KrytenClient integration
- Event handlers for `chatMsg` and `addUser` events
- Configuration management system
- CI workflow with Python 3.10, 3.11, and 3.12 support
- PyPI publishing workflow with trusted publishing
- Startup scripts for PowerShell and Bash
- Systemd service manifest
- Documentation structure
