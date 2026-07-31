# Multi-Instance Deployment Guide

**Sprint**: 17
**Updated**: 2026-07-30

This guide covers running two kryten-llm instances (primary + secondary bot) against a
**shared fact store** so both bots have access to the same community memory.

---

## Why shared memory?

The production deployment runs two bots on the same channel:

| | Primary | Secondary |
|---|---|---|
| Responds to | Triggers + auto-participation | Direct address only |
| Model | Fast local | Large capable model |
| Role | Conversational | Deep factual recall (films, TV, pop culture) |

Without a shared store, the secondary bot starts every interaction cold. A user who just
told the primary bot their favourite Kubrick film gets no recognition from the secondary when
they ask it a Kubrick trivia question five minutes later.

With a shared store, facts learned by either bot are immediately available to the other.

---

## ⚠️  The Embedded Chroma Danger

**Chroma's embedded `PersistentClient` is strictly single-process.**

If both bots point at the same `store.path` in embedded mode, the second bot to write will
**corrupt the collection**. This is a hard constraint from ChromaDB itself — there is no
locking or coordination in embedded mode.

**Symptom**: errors like `sqlite3.OperationalError: database is locked` or silently lost
facts.

**Fix**: use Chroma's HTTP server mode or pgvector.

---

## Option A: Chroma HTTP Server (recommended for local deployments)

Run a single Chroma server process, then point both bots at it.

### 1. Start the Chroma server

```bash
# Create the data directory if it doesn't exist
mkdir -p ./data/chroma

# Start the server (keep it running; use a systemd unit in production)
chroma run --path ./data/chroma --port 8000
```

Or with a systemd unit:

```ini
# /etc/systemd/system/kryten-chroma.service
[Unit]
Description=ChromaDB vector store for Kryten memory
After=network.target

[Service]
Type=simple
User=kryten
WorkingDirectory=/opt/kryten
ExecStart=/opt/kryten/.venv/bin/chroma run --path /opt/kryten/data/chroma --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 2. Configure both bots

In **both** config files, set `http_host` and `http_port` instead of `path`:

```json
{
  "context": {
    "providers": [
      {
        "type": "long_term_memory",
        "enabled": true,
        "store": {
          "backend": "chroma",
          "http_host": "localhost",
          "http_port": 8000,
          "collection": "user_facts"
        },
        "...": "... other settings identical in both bots ..."
      }
    ]
  }
}
```

> **Do not set `path`** when `http_host` is set — the path is used only by embedded mode.

### 3. Verify

Check the `/metrics` endpoint of either bot:

```bash
curl -s http://localhost:28286/metrics | grep llm_memory_store_mode
# Expected: llm_memory_store_mode{mode="chroma-http"} 1
```

---

## Option B: pgvector (recommended for production)

pgvector uses PostgreSQL, which handles concurrent writers natively. No additional server
process is needed beyond the database itself.

### Configure both bots

Both bots share the same DSN. Use `dsn_env` to keep the password out of config files:

```json
{
  "context": {
    "providers": [
      {
        "type": "long_term_memory",
        "enabled": true,
        "store": {
          "backend": "pgvector",
          "table": "user_facts",
          "dsn_env": "KRYTEN_MEMORY_DSN",
          "pool_min_size": 1,
          "pool_max_size": 4
        }
      }
    ]
  }
}
```

Set the environment variable before starting each bot:

```bash
export KRYTEN_MEMORY_DSN="postgresql://kryten:PASSWORD@localhost:5432/kryten_memory"
```

See [pgvector-setup.md](pgvector-setup.md) for database initialisation instructions.

### Verify

```bash
curl -s http://localhost:28286/metrics | grep llm_memory_store_mode
# Expected: llm_memory_store_mode{mode="pgvector"} 1
```

---

## Bot Peer Exclusion (`ignored_users`)

Each bot should be listed in the other's `ignored_users` config. This prevents each bot from
extracting facts about the other's persona and avoids accidental bot-on-bot trigger loops.

In **primary bot** config:

```json
{
  "ignored_users": ["SecondaryBotName"]
}
```

In **secondary bot** config:

```json
{
  "ignored_users": ["PrimaryBotName"]
}
```

Use the exact `character_name` values from each bot's `personality` config block.

---

## `forget.user` Semantics in Shared-Store Mode

Both bots subscribe to `kryten.llm.command`. A `forget.user` command issued to either bot
calls `_store.delete({"user": username})` on the shared store — the deletion is immediately
visible to the other bot on its next query. **No cascade logic is needed.**

```bash
# Issue to either bot — both see the effect
nats request kryten.llm.command '{"service":"llm","command":"forget.user","username":"alice"}'
```

---

## Example Systemd Units

### Primary bot

```ini
# /etc/systemd/system/kryten-llm-primary.service
[Unit]
Description=Kryten LLM Primary Bot
After=network.target kryten-chroma.service
Requires=kryten-chroma.service

[Service]
Type=simple
User=kryten
WorkingDirectory=/opt/kryten/kryten-llm
EnvironmentFile=/etc/kryten/kryten-llm/environment
ExecStart=/opt/kryten/kryten-llm/.venv/bin/kryten-llm --config /etc/kryten/kryten-llm/config-primary.json
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Secondary bot

```ini
# /etc/systemd/system/kryten-llm-secondary.service
[Unit]
Description=Kryten LLM Secondary Bot (trivia/deep recall)
After=network.target kryten-chroma.service
Requires=kryten-chroma.service

[Service]
Type=simple
User=kryten
WorkingDirectory=/opt/kryten/kryten-llm
EnvironmentFile=/etc/kryten/kryten-llm/environment
ExecStart=/opt/kryten/kryten-llm/.venv/bin/kryten-llm --config /etc/kryten/kryten-llm/config-secondary.json
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## Checklist Before Going Live

- [ ] `store_mode` metric shows `chroma-http` or `pgvector` on **both** bots (not `chroma-embedded`)
- [ ] Each bot lists the other's `character_name` in `ignored_users`
- [ ] `forget.user` tested: issue to one bot, confirm fact count is 0 when queried via the other
- [ ] Both bots have the same `collection` name (Chroma) or `table` name (pgvector)
- [ ] Both bots use the same embedder model (`store.embedder.model`) — mismatch causes a startup error
