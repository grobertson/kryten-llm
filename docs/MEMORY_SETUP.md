# Long-Term Memory Setup (Phase 7)

Phase 7 adds a pluggable context provider framework and an optional long-term memory
subsystem backed by ChromaDB. This guide covers installation, configuration, and
operation of both the context framework and the memory subsystem.

---

## Overview

The Phase 7 context pipeline replaces the hard-wired `ContextManager` with a registry
of composable `ContextProvider` plugins. Each provider runs independently and is
fail-open — a single provider failure will never block a response.

Two built-in providers are always available:

| Provider | Type key | Default priority | Description |
|---|---|---|---|
| Video context | `video` | 60 | Current playlist item / media metadata |
| Chat history | `chat_history` | 50 | Recent chat window (same as Phase 6) |

An optional third provider activates long-term per-user memory:

| Provider | Type key | Default priority | Description |
|---|---|---|---|
| Long-term memory | `long_term_memory` | 40 | ChromaDB-backed per-user fact store |

---

## Base Install (no memory)

The base package has no heavy ML dependencies. Install as usual:

```bash
pip install kryten-llm
# or via uv:
uv add kryten-llm
```

When `context.providers` is absent from `config.json`, the pipeline defaults to
`[video, chat_history]` — identical to Phase 6 behaviour. No configuration change
is required to use Phase 7 at this level.

---

## Memory Install

Long-term memory requires ChromaDB and sentence-transformers. Install the `[memory]`
optional extra:

```bash
pip install 'kryten-llm[memory]'
# or via uv:
uv add 'kryten-llm[memory]'
```

> **Python version requirement:** The `[memory]` extra requires **Python 3.11+**
> because `onnxruntime >= 1.24` (a transitive dependency of `sentence-transformers`)
> does not ship Python 3.10 wheels. The base package continues to support Python 3.10+.

This pulls in:
- `chromadb>=0.4.0` — the vector database backend
- `sentence-transformers>=2.2.0` — the default ONNX in-process embedder

The first time an embedder model is used it will be downloaded from HuggingFace
(~90 MB for `all-MiniLM-L6-v2`). Subsequent starts load from the local cache.

---

## Configuration

### Minimal — keep Phase 6 defaults

No `context` section needed:

```json
{
  "nats": { ... },
  "llm_providers": { ... }
}
```

### Explicit providers, memory disabled

```json
{
  "context": {
    "context_window_chars": 4000,
    "providers": [
      { "type": "video",        "enabled": true,  "priority": 60 },
      { "type": "chat_history", "enabled": true,  "priority": 50 }
    ]
  }
}
```

### Full memory enabled (ONNX in-process embedder)

```json
{
  "context": {
    "context_window_chars": 4000,
    "providers": [
      { "type": "video",        "enabled": true,  "priority": 60 },
      { "type": "chat_history", "enabled": true,  "priority": 50 },
      {
        "type": "long_term_memory",
        "enabled": true,
        "priority": 40,
        "embedder": {
          "type": "onnx",
          "model": "all-MiniLM-L6-v2"
        },
        "store": {
          "backend": "chroma",
          "path": "./data/chroma",
          "collection": "user_facts"
        },
        "extractor": { "type": "heuristic" },
        "max_facts_per_user": 50,
        "observe_timeout_seconds": 2.0,
        "provide_timeout_seconds": 1.5
      }
    ]
  }
}
```

### Memory enabled with OpenAI-compatible embedder (LM Studio / Ollama / OpenAI)

Use this when you want to run a remote embedder instead of the local ONNX model.
This does **not** require the `[memory]` extra (only `chromadb` is needed):

```json
{
  "type": "long_term_memory",
  "enabled": true,
  "priority": 40,
  "embedder": {
    "type": "openai_compatible",
    "base_url": "http://localhost:1234/v1",
    "model": "nomic-embed-text",
    "api_key": "",
    "dimension": 768
  },
  "store": {
    "backend": "chroma",
    "path": "./data/chroma",
    "collection": "user_facts"
  },
  "extractor": { "type": "heuristic" }
}
```

> **Important:** Once a collection is written with a given embedder, you must use
> the same embedder for all subsequent runs. Kryten-LLM stores the embedder
> identity in the ChromaDB collection metadata and hard-fails on mismatch to
> prevent silently mixing vector spaces. To switch embedders, either delete the
> collection or change the `collection` name.

---

## Config reference

### `context` block

| Key | Type | Default | Description |
|---|---|---|---|
| `context_window_chars` | int | 4000 | Global character budget shared across all providers |
| `providers` | list | `[video, chat_history]` | Ordered list of provider configs |

### Provider common keys

| Key | Type | Default | Description |
|---|---|---|---|
| `type` | str | — | Provider type key (see table above) |
| `enabled` | bool | `true` | Set `false` to skip without removing the config |
| `priority` | int | 0 | Higher = kept first when budget is tight |

### `long_term_memory` provider keys

| Key | Type | Default | Description |
|---|---|---|---|
| `embedder` | object | — | Embedder config (see below) |
| `store` | object | — | Vector store config (see below) |
| `extractor` | object | `{"type": "heuristic"}` | Fact extractor config |
| `max_facts_per_user` | int | 50 | Cap on stored facts per user; oldest evicted first |
| `observe_timeout_seconds` | float | 2.0 | Async write timeout per message |
| `provide_timeout_seconds` | float | 1.5 | Read timeout during prompt build |

### Embedder: `onnx`

| Key | Type | Default | Description |
|---|---|---|---|
| `type` | str | `"onnx"` | Selects the in-process ONNX backend |
| `model` | str | `"all-MiniLM-L6-v2"` | HuggingFace model name (384-dim) |

### Embedder: `openai_compatible`

| Key | Type | Required | Description |
|---|---|---|---|
| `type` | str | yes | `"openai_compatible"` |
| `base_url` | str | yes | API base URL (e.g. `http://localhost:1234/v1`) |
| `model` | str | yes | Model identifier sent in the request |
| `api_key` | str | no | Bearer token (leave empty for local servers) |
| `dimension` | int | no | Embedding dimension hint (used for store creation) |

### Store: `chroma`

| Key | Type | Default | Description |
|---|---|---|---|
| `backend` | str | `"chroma"` | Selects ChromaDB |
| `path` | str | `"./data/chroma"` | Directory for the persistent database |
| `collection` | str | `"user_facts"` | Collection name |

---

## Memory CLI

The `kryten-llm` command exposes a `memory` subcommand for offline operations.
The `[memory]` extra must be installed.

### Seed from log files

```bash
kryten-llm memory seed --logs "logs/*.log"
```

Parses chat logs, extracts facts with the heuristic extractor, and upserts them
into the vector store. Seeding is **idempotent** — facts are keyed by a SHA-256
hash of `username + normalised_summary`, so running it twice produces no
duplicates.

```bash
# Dry run — show what would be extracted without writing anything
kryten-llm memory seed --logs "logs/*.log" --dry-run
```

### Forget a user

```bash
kryten-llm memory forget <username>
```

Deletes all stored facts for the given user. This is the GDPR-friendly erasure
path. The same effect can be triggered at runtime via the `memory.forget` NATS
command (see API reference).

### Show stats

```bash
kryten-llm memory stats
```

Prints total fact count and per-user breakdown.

---

## NATS command API

Memory commands follow the standard `kryten.llm.command` request/reply pattern.

| `command` | Description |
|---|---|
| `memory.stats` | Returns total and per-user fact counts |
| `memory.forget` | Deletes all facts for `request["username"]` |

Example request (using `kryten-py` debug tool):

```bash
python debug_commands.py kryten.llm.command '{"command": "memory.stats"}'
python debug_commands.py kryten.llm.command '{"command": "memory.forget", "username": "alice"}'
```

---

## Privacy / Safety

The heuristic extractor includes a privacy gate (`safety.py`) that excludes
messages flagged as sensitive (drug references, mentions of minors, etc.) from
being stored as facts. This runs before any embedding. The gate is
**fail-closed**: uncertain cases are rejected, not stored.

---

## Operational notes

### ChromaDB data directory

The default `./data/chroma` path is relative to the working directory. For
production, use an absolute path and ensure the `kryten` user has write access:

```json
"store": { "backend": "chroma", "path": "/var/lib/kryten/chroma" }
```

### First-run model download

On the first start with `type: onnx`, `sentence-transformers` will download the
model from HuggingFace (~90 MB). In offline/air-gapped environments, pre-download
it and point `SENTENCE_TRANSFORMERS_HOME` to the local cache.

### Disk usage

ChromaDB stores vectors on disk. A rough estimate for `all-MiniLM-L6-v2` (384-dim
float32): ~1.5 KB per fact. With the default cap of 50 facts/user and 100 active
users, expect ~7.5 MB of vector data plus ChromaDB overhead (~2×).

### Embedder mismatch

If you change embedders (e.g. switching from `onnx` to `openai_compatible`), the
service will refuse to start with a clear error:

```
RuntimeError: Embedder identity mismatch: collection was created with 'onnx'
(dim=384) but current embedder is 'openai_compatible:nomic-embed-text' (dim=768).
Re-embed the collection or change the collection name.
```

Resolution options:
1. Delete the ChromaDB collection directory and re-seed from logs.
2. Change `store.collection` to a new name (old facts are abandoned).
3. Revert to the original embedder.

---

## Extending with custom providers

The registry pattern (`PROVIDER_REGISTRY`, `EMBEDDER_REGISTRY`, `VECTOR_STORE_REGISTRY`)
is designed for future extension. Custom providers must implement the
`ContextProvider` protocol from `kryten_llm.components.context.base` and register
themselves before the pipeline is built. This interface is stable — Phase 7f will
add an LLM-based extractor as a config-only swap.
