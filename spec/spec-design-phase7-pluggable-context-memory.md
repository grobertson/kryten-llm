---
title: Phase 7 - Pluggable Context Providers & Long-Term Memory (ChromaDB)
version: 0.1 (draft)
date_created: 2026-07-11
last_updated: 2026-07-11
owner: kryten-llm development team
tags: [design, phase7, memory, context, chromadb, embeddings, plugin]
---

# Introduction

This specification defines the design for Phase 7 of kryten-llm: a **pluggable context
provider** architecture and a **long-term memory** subsystem backed by a vector store
(ChromaDB by default). It generalises the current hard-wired `ContextManager` (video +
rolling chat buffer) into a registry of composable providers that are declared and
configured entirely from `config.json`.

The immediate product goal is a **Minimum Viable Product (MVP)**: give the bot durable,
per-user memory ("remembers facts about people across restarts and sessions") while
reusing the heuristic fact-extraction logic already prototyped in
`user-extraction/factfinder.py`. LLM-based extraction and richer retrieval are designed
for but deferred behind stable interfaces.

## 1. Purpose & Scope

### Purpose
Enable kryten-llm to:
1. Compose prompt context from **multiple independent providers** selected/ordered via config.
2. Maintain **short-term memory** (existing rolling chat buffer) as one provider.
3. Maintain **long-term memory** (durable, semantically-searchable user facts) as a new provider.
4. Support **pluggable embedding backends** (local ONNX, cross-network local servers such as
   LM Studio / Ollama, and remote APIs such as OpenAI / Anthropic).
5. Support a **pluggable fact extractor** — heuristic for the MVP, LLM-based later — behind one interface.
6. **Seed** long-term memory offline from existing chat log files via a CLI command.

### Scope
This specification covers:
- A `ContextProvider` plugin interface and a `ContextPipeline` registry/orchestrator.
- Refactor of the existing video + chat-history `ContextManager` into built-in providers
  (backwards compatible, no behavioural change when memory is disabled).
- A `LongTermMemoryProvider` backed by a `VectorStore` abstraction (ChromaDB default impl).
- An `Embedder` abstraction with three reference backends.
- A `FactExtractor` abstraction with a heuristic implementation salvaged from `factfinder.py`.
- Configuration schema additions.
- A `kryten-llm memory seed` CLI subcommand.
- Requirements, interfaces, phased rollout, testing strategy, and risks.

### Out of Scope (this phase)
- Conversation summarisation / episodic memory compression (future phase).
- Cross-channel identity resolution beyond simple username keying.
- UI / dashboards for browsing stored memories.

### Assumptions
- Phases 1–6 are complete; `LLMManager`, `PromptBuilder` (Jinja2), and the existing
  `ContextManager` behave as in the current codebase.
- The service runs as a long-lived process with a writable data directory.
- `factfinder.py` is a **prototype**, not production code; only its logic is salvaged.

### Intended Audience
Developers implementing Phase 7, architects reviewing the plugin model, QA writing test plans.

## 2. Definitions

| Term | Definition |
|------|------------|
| **Context Provider** | A plugin that contributes one or more context fragments to a prompt build. |
| **Context Pipeline** | Registry + orchestrator that loads providers from config and merges their output. |
| **Context Fragment** | A named, ordered, budgeted piece of context (text or structured) for the prompt. |
| **Short-Term Memory (STM)** | Volatile, recent-message context (the existing rolling deque). |
| **Long-Term Memory (LTM)** | Durable, semantically-retrievable facts persisted in a vector store. |
| **Vector Store** | Backend that stores embeddings + metadata and supports similarity search (ChromaDB). |
| **Embedder** | Component turning text into vectors; pluggable backend (ONNX / local server / API). |
| **Fact** | A short, paraphrased, privacy-filtered statement attributed to a user. |
| **Fact Extractor** | Component that turns raw messages into candidate `Fact` records (heuristic or LLM). |
| **Seeding** | Offline bulk import of facts from historical chat log files. |
| **Memory Key** | The identity a fact is stored under (MVP: canonical username). |

## 3. Requirements, Constraints & Guidelines

### 3.1 Context Provider Framework

- **REQ-001**: The system MUST define a `ContextProvider` interface that all context sources implement.
- **REQ-002**: The system MUST load the set of active providers, their order, and per-provider
  settings **from `config.json`** (no code change to enable/disable/reorder providers).
- **REQ-003**: Each provider invocation MUST receive a `ContextRequest` (username, cleaned message,
  trigger metadata, channel) and return zero or more `ContextFragment` objects.
- **REQ-004**: A single provider failure or timeout MUST NOT block response generation; the pipeline
  MUST log and continue with the remaining fragments (fail-open).
- **REQ-005**: The pipeline MUST enforce a global context character budget
  (reuse `context.context_window_chars`) by trimming lowest-priority fragments first.
- **REQ-006**: Providers MUST declare whether they are **read** (contribute context) and/or
  **write** (observe/ingest messages), so the pipeline can route the message stream appropriately.
- **REQ-007**: The existing video context and chat-history buffer MUST be re-expressed as built-in
  providers with identical output when memory features are disabled (regression-safe default).

### 3.2 Long-Term Memory Provider

- **REQ-010**: A `LongTermMemoryProvider` MUST persist user facts in a `VectorStore` and survive restarts.
- **REQ-011**: On each qualifying inbound message, the provider MUST (asynchronously, off the
  response critical path) run the configured `FactExtractor` and upsert new facts.
- **REQ-012**: When building context, the provider MUST retrieve the top-K facts for the triggering
  user (and optionally facts semantically related to the current message) and emit them as a fragment.
- **REQ-013**: The provider MUST deduplicate facts before writing (normalised-text + embedding-distance
  threshold) to avoid unbounded growth.
- **REQ-014**: The provider MUST enforce a per-user cap on stored facts (configurable), evicting the
  lowest-scored/oldest facts when exceeded.
- **REQ-015**: Fact writes MUST pass the privacy/safety filter (Section 3.5) before persistence.
- **REQ-016**: All fact records MUST carry metadata: `user`, `category`, `source` (live|seed),
  `created_at`, `score`, and truncated `evidence` (line/time/message) for auditability.

### 3.3 Pluggable Embeddings

- **REQ-020**: The system MUST define an `Embedder` interface (`embed(texts) -> list[vector]`,
  plus `dimension` and `id`).
- **REQ-021**: The system MUST provide at least three backends, selected by config `type`:
  - `onnx` (in-process local model, default; no network, no API key),
  - `openai_compatible` (cross-network local server: LM Studio, Ollama, vLLM, or remote OpenAI),
  - `anthropic` (or other remote API) — may be stubbed if no first-class embeddings endpoint exists.
- **REQ-022**: The active embedder identity (model + dimension) MUST be recorded with the collection;
  a mismatch on startup MUST fail loudly (or trigger an explicit re-embed migration), never silently
  mix vector spaces.
- **REQ-023**: Embedding calls MUST be batched and MUST NOT run on the response critical path for writes.

### 3.4 Pluggable Fact Extraction

- **REQ-030**: The system MUST define a `FactExtractor` interface
  (`extract(messages, user) -> list[Fact]`).
- **REQ-031**: The MVP MUST ship a `HeuristicFactExtractor` that reuses the salvaged logic from
  `factfinder.py` (candidate filtering, scoring, categorisation, dedup) — see Section 6.
- **REQ-032**: The interface MUST support a future `LLMFactExtractor` that calls `LLMManager` with a
  distillation prompt; swapping extractors MUST be a config change only.
- **REQ-033**: The extractor MUST be side-effect free (pure transform); persistence is the provider's job.

### 3.5 Privacy, Safety & Constraints

- **CON-001**: Messages containing emails, URLs, phone numbers, physical-address keywords, or long
  digit strings MUST NOT be stored as facts (salvaged `safe_message_text` gate; drug/explicit-age
  handling made **exclusionary** — see Section 6 note on the prototype bug).
- **CON-002**: LTM writes MUST be opt-in via config (`memory.long_term.enabled`, default `false`)
  so existing deployments are unaffected until explicitly enabled.
- **CON-003**: A user-facing purge path MUST exist: delete all facts for a given user
  (`kryten-llm memory forget <user>`), supporting "forget me" requests.
- **CON-004**: ChromaDB is the default `VectorStore`, but the interface MUST allow alternative
  backends without touching provider logic.
- **CON-005**: New heavy dependencies (`chromadb`, ONNX runtime) SHOULD be an **optional extra**
  (`pip install kryten-llm[memory]`) so the base install stays light.
- **GUD-001**: Reads block the prompt build only for a short, configurable timeout; writes are fire-and-forget.
- **GUD-002**: Keep fragment text compact (bulleted facts), since prompt budget is shared with video/chat.

## 4. Architecture & Interfaces

### 4.1 Context pipeline (data flow)

```
inbound chatmsg
      │
      ▼
 service.py ──► ContextPipeline.observe(msg)      # WRITE providers ingest (async, off critical path)
      │                └─► LongTermMemoryProvider.observe() ─► FactExtractor ─► Embedder ─► VectorStore.upsert
      │
 (trigger fires)
      ▼
 ContextPipeline.build(ContextRequest) ──► [ProviderA.provide(), ProviderB.provide(), ...]  # READ
      │            ├─ VideoContextProvider      -> fragment("video")
      │            ├─ ChatHistoryProvider       -> fragment("recent_chat")
      │            └─ LongTermMemoryProvider     -> fragment("user_memory")   # VectorStore.query + Embedder
      ▼
 merge + budget (priority-ordered, trimmed to context_window_chars)
      ▼
 PromptBuilder.build_user_prompt(..., context=merged)  ──► Jinja2 templates
```

### 4.2 Core interfaces (illustrative)

```python
# kryten_llm/components/context/base.py
from dataclasses import dataclass
from typing import Any, Protocol

@dataclass
class ContextRequest:
    username: str
    message: str
    trigger: dict[str, Any] | None
    channel: str

@dataclass
class ContextFragment:
    name: str            # e.g. "user_memory"
    priority: int        # higher = kept first under budget pressure
    text: str | None     # rendered text, OR
    data: Any = None     # structured payload for templates
    est_chars: int = 0

class ContextProvider(Protocol):
    id: str
    reads: bool
    writes: bool
    async def observe(self, username: str, message: str) -> None: ...   # WRITE path (no-op if not writes)
    async def provide(self, req: ContextRequest) -> list[ContextFragment]: ...  # READ path
```

```python
# kryten_llm/components/memory/embedder.py
class Embedder(Protocol):
    id: str
    dimension: int
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

# kryten_llm/components/memory/vector_store.py
class VectorStore(Protocol):
    async def upsert(self, ids: list[str], vectors: list[list[float]],
                     metadatas: list[dict], documents: list[str]) -> None: ...
    async def query(self, vector: list[float], k: int,
                    where: dict | None = None) -> list[dict]: ...
    async def delete(self, where: dict) -> None: ...

# kryten_llm/components/memory/extractor.py
@dataclass
class Fact:
    user: str
    category: str        # preference|habit|past|life_context|self_description|misc
    summary: str
    evidence: dict       # {line,time,message}
    score: float

class FactExtractor(Protocol):
    async def extract(self, messages: list[dict], user: str) -> list[Fact]: ...
```

### 4.3 Provider registry / factory
- A `PROVIDER_REGISTRY: dict[str, type[ContextProvider]]` maps a config `type` string to a class.
- `EMBEDDER_REGISTRY` and `EXTRACTOR_REGISTRY` and `VECTOR_STORE_REGISTRY` follow the same pattern.
- `ContextPipeline.from_config(config, deps)` instantiates providers in declared order, injecting
  shared dependencies (`LLMManager`, logger, data dir).

## 5. Configuration Schema (additions to `config.json`)

New Pydantic models under `kryten_llm/models/config.py`, referenced by `LLMConfig`.

```jsonc
{
  "context": {
    // ...existing fields (chat_history_size, context_window_chars, etc.)...
    "providers": [
      { "type": "video",        "enabled": true,  "priority": 60 },
      { "type": "chat_history", "enabled": true,  "priority": 50 },
      {
        "type": "long_term_memory",
        "enabled": false,                 // CON-002: opt-in
        "priority": 40,
        "read_timeout_ms": 300,
        "retrieval": { "top_k": 5, "relate_to_message": true, "min_similarity": 0.25 },
        "write": { "min_message_score": 30, "per_user_fact_cap": 200,
                   "dedup_similarity": 0.9 },
        "store": {
          "backend": "chroma",
          "path": "./data/chroma",
          "collection": "user_facts"
        },
        "embedder": {
          "type": "onnx",                 // onnx | openai_compatible | anthropic
          "model": "all-MiniLM-L6-v2"
          // openai_compatible example:
          // "type": "openai_compatible", "base_url": "http://localhost:1234/v1",
          // "model": "nomic-embed-text", "api_key": "${LMSTUDIO_KEY}"
        },
        "extractor": {
          "type": "heuristic"             // heuristic | llm
          // llm example: "type": "llm", "provider": "local", "max_facts": 10
        }
      }
    ]
  }
}
```

- Backwards compatibility: if `context.providers` is **absent**, the pipeline defaults to
  `[video, chat_history]` reproducing today's behaviour (REQ-007).
- API keys use the existing `${ENV_VAR}` resolution pattern (see `LLMManager._resolve_api_key`).

## 6. Salvage Map — `user-extraction/factfinder.py`

| factfinder.py element | MVP destination | Notes |
|-----------------------|-----------------|-------|
| `safe_message_text()` + `email_like`/`url_like`/`phone_like`/`addressy`/6+ digit regexes | `memory/safety.py` privacy gate (CON-001) | **Fix prototype bug**: drug/explicit-age branches currently `return True` (kept); MVP MUST make these **exclusionary** (`return False`). |
| `first_person` regex + reaction filter | `HeuristicFactExtractor` candidate filter (REQ-031) | Decides if a message is worth remembering. |
| `normalize()` | dedup key helper (REQ-013) | Reused for both write-dedup and fragment de-dup. |
| `score()` (length + keyword bonuses) | extractor ranking + `write.min_message_score` gate | Threshold becomes config-driven. |
| `summarize_fact()` categorisation | `HeuristicFactExtractor.extract()` core | Produces `Fact.category` + `Fact.summary`. |
| `extract_facts()` orchestration | `HeuristicFactExtractor.extract()` | Streaming (per-message/small-batch) instead of top-25 batch. |
| `DSU` alias union-find | **Dropped for MVP** | Live username is the memory key; revisit for identity resolution later. |
| top-25 / file IO / JSON report scaffolding | **Repurposed** into the `memory seed` CLI (Section 7) | Batch path over log files, not the live path. |

## 7. Seeding CLI

- **REQ-040**: Add `kryten-llm memory seed --logs <glob> [--dry-run]` that parses historical chat
  logs (reusing `line_re`/`server_alias_re` parsing from the prototype), runs the configured
  `FactExtractor` + safety gate, and bulk-upserts facts with `source="seed"`.
- **REQ-041**: Seeding MUST be idempotent (stable fact IDs via hash of `user+normalised summary`)
  so re-running does not duplicate.
- **REQ-042**: Add companion commands: `memory forget <user>` (CON-003) and `memory stats`
  (counts per user / per category, collection health).
- **GUD-003**: Seeding SHOULD show a progress summary (users processed, facts written, facts skipped
  by safety filter) — mirroring the prototype's final tuple output.

## 8. Implementation Phases

1. **7a — Framework (no behaviour change).** Add `ContextProvider`/`ContextFragment`/`ContextPipeline`;
   wrap current video + chat logic as built-in providers; wire `service.py` to the pipeline behind a
   default config that reproduces today's output. Ship + regression-test.
2. **7b — Memory core (offline).** Add `Embedder` (ONNX), `VectorStore` (Chroma), `Fact`,
   `HeuristicFactExtractor` + `safety.py` (salvage). Unit-test in isolation. No service wiring yet.
3. **7c — Seeding CLI.** `memory seed/forget/stats`. Validates the whole write+query path against real logs.
4. **7d — Live provider.** `LongTermMemoryProvider` (observe=write, provide=read) wired into the
   pipeline; opt-in via config; fail-open + off-critical-path writes.
5. **7e — Pluggable backends.** Add `openai_compatible` + `anthropic` embedders; embedder-identity
   guard (REQ-022). Optional `[memory]` extra packaging.
6. **7f — LLM extractor (post-MVP).** `LLMFactExtractor` behind the same interface; config swap only.

## 9. Testing Strategy

- Unit: safety gate (each PII class), heuristic extractor categorisation, dedup, budget trimming,
  provider fail-open, embedder-identity mismatch guard.
- Integration: seed a fixture log → query returns expected user facts; live `observe→provide` round-trip
  with an in-memory Chroma; pipeline merge order + budget under pressure.
- Backwards-compat: with no `context.providers` config, prompt output byte-identical to Phase 6 for a
  fixed fixture.
- Contract tests shared across all `Embedder` / `VectorStore` / `FactExtractor` implementations.

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Heavy deps (chromadb, onnxruntime) bloat base install | Slower/broken installs | Optional `[memory]` extra; feature disabled by default (CON-002/005). |
| Embedding backend swap silently mixes vector spaces | Garbage retrieval | Record embedder id+dim on collection; hard fail on mismatch (REQ-022). |
| Heuristic extractor stores noisy/low-value "facts" | Prompt pollution | `min_message_score` gate + per-user cap + dedup; LLM extractor later (7f). |
| Privacy leak into durable store | Serious | Safety gate before every write; opt-in; `forget` command; fix prototype's non-exclusionary bug. |
| Synchronous embedding/query stalls responses | Latency | Writes fire-and-forget; reads time-boxed + fail-open (REQ-004/023, GUD-001). |
| Prototype bug carried over (drug/age `return True`) | Sensitive content stored | Explicitly inverted in salvage (Section 6). |

## 11. Open Questions

- Memory key: pure username vs. lightweight alias resolution (revive DSU) if CyTube exposes alias joins live?
- Should retrieved facts be injected as a distinct template block (`{{ user_memory }}`) or merged into the
  existing system prompt? (Leaning: new optional Jinja block for clarity.)
- Retention policy: time-decay scoring vs. hard cap only?
- Multi-channel: one collection with `channel` metadata vs. one collection per channel?
