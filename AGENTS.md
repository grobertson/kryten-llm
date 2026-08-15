# Kryten-LLM — Project Guidelines

Kryten-LLM is the AI memory and chat-responder service in the **Kryten ecosystem**. It subscribes to CyTube chat events over NATS, decides when to respond (triggers + rate limits), generates replies via pluggable LLM providers, and sends them back through `KrytenClient`.

## Deployment Context

Two kryten-llm instances run against the **same channel** simultaneously:

- **Primary bot** — speaks on triggers and auto-participation; conversationally interactive;
  uses a fast local model. Always-on observation of the full chat stream.
- **Secondary bot** — responds only when directly addressed (questions, trivia requests);
  uses a larger, more capable model for deep factual recall on films, TV, and pop culture.

Both instances **share one fact store** (Chroma HTTP server or pgvector — never embedded
Chroma with two processes). Each bot should list the other's `character_name` in
`ignored_users` to prevent bot-on-bot observation. See [docs/MULTI_INSTANCE.md](docs/MULTI_INSTANCE.md)
for the deployment guide (Sprint 17).

This is a **single-channel deployment**. There is no cross-channel federation, no consent
gate architecture, and no multi-operator coordination to design for. Keep the architecture
simple; resist feature creep that assumes a multi-channel or multi-operator deployment.

## Architecture
- Event-driven microservice on a **NATS message bus**. Never call other services over direct HTTP — the only HTTP surface in the ecosystem is `kryten-api-gate`.
- Use the shared **`kryten-py`** library (`KrytenClient`) for all NATS, lifecycle, health, and KV state — do not use raw `nats-py`.
- Subscribe to chat events on `kryten.events.{domain}.{channel}.{event_type}` (normalized: lowercase, dots stripped). Handle commands on the single subject `kryten.llm.command`, dispatching on the `command` field and replying `{"service","command","success",...}`.
- Shared state via JetStream KV buckets `kryten_{channel|service}_{type}`: bind read-only with `get_kv_store`; only the owning service creates via `get_or_create_kv_store`.
- Component layout and message flow: see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Ecosystem-wide contracts: [../KRYTEN_ARCHITECTURE.md](../KRYTEN_ARCHITECTURE.md) and the `kryten-py` docs ([../kryten-py/COMMAND_PROTOCOL.md](../kryten-py/COMMAND_PROTOCOL.md), [../kryten-py/STATE_MANAGEMENT.md](../kryten-py/STATE_MANAGEMENT.md), [../kryten-py/ERROR_HANDLING.md](../kryten-py/ERROR_HANDLING.md)).

## Build and Test
Run from the repo root (uv-managed):
- Install deps: `uv sync`
- Format: `uv run black .`
- Lint (autofix): `uv run ruff check --fix .`
- Types: `uv run mypy kryten_llm`
- Tests: `uv run pytest` (add `--cov=kryten_llm --cov-report=term-missing` for coverage)

Run all four before committing. Do not bypass checks (`--no-verify`).

## Conventions
- Python 3.10+, 100% `async`/`await`, Pydantic v2 config. black/ruff `line-length = 100` (E501 ignored). pytest `asyncio_mode = "auto"`.
- **Event handlers must catch and log exceptions — never raise into the event loop.** Rely on `kryten-py` auto-reconnect; don't hand-roll reconnect logic. Put timeouts on LLM calls (see `LLMManager`).
- Config is JSON with auto-discovery: `--config` flag → `/etc/kryten/kryten-llm/config.json` → `./config.json`. Keep `config.example.json` in sync; never hardcode values or NATS subjects.
- Version lives only in `pyproject.toml [project] version`. Update `CHANGELOG.md` (Keep-a-Changelog + SemVer, ISO dates) for any versioned behavior change.
- Commit prefixes: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `ci:`. Branches: `feature/…`, `fix/…`. See [CONTRIBUTING.md](CONTRIBUTING.md).
- Contract changes (event shape, `kryten.llm.command` commands, KV schema, config schema) are high-stakes: flag them, keep backward compatibility, and version/document any break.

## Development Workflow
Feature work follows the nano-sprint PRD → Sortie flow in [../AGENT-WORKFLOW-GUIDE.md](../AGENT-WORKFLOW-GUIDE.md). Specs live under `docs/{N}-{sprint-name}/`.
