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

## Build, Test & Conventions
Shared ecosystem rules (uv build/test, config auto-discovery, versioning, commit
style, NATS/KV patterns, contract-change policy): see
[../KRYTEN_CONVENTIONS.md](../KRYTEN_CONVENTIONS.md). Repo specifics:
- **Python 3.10+**; mypy target `uv run mypy kryten_llm`.
- Config: `/etc/kryten/kryten-llm/config.json` (JSON auto-discovery).
- **Put timeouts on LLM calls** (see `LLMManager`); event handlers must never
  raise into the event loop.
- `kryten.llm.command` command set, event shape, KV schema, and config schema are
  the contract surface — keep backward compatible and version/document any break.
- Feature work: nano-sprint PRD → Sortie flow
  ([../AGENT-WORKFLOW-GUIDE.md](../AGENT-WORKFLOW-GUIDE.md)); specs under
  `docs/{N}-{sprint-name}/`. See also [CONTRIBUTING.md](CONTRIBUTING.md).
