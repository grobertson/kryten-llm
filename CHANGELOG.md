# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
