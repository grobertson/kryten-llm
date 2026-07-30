# pgvector backend for long-term memory

The long-term memory store supports two backends: the default embedded
**Chroma** (`PersistentClient`) and **PostgreSQL + pgvector**. Chroma's embedded
client is single-process only — two processes writing the same directory will
corrupt the HNSW index. The pgvector backend is safe for concurrent
multi-process access (the live bot and a multi-day `memory seed` run at once),
adds transactional integrity and SQL/JOIN filtering, and is the recommended
backend when you need concurrency.

## 1. Install the extra

```powershell
uv sync --extra memory --extra pgvector
# or: pip install 'kryten-llm[memory,pgvector]'
```

This pulls in `asyncpg` and `pgvector` (Python), on top of the embedder deps in
`[memory]`.

## 2. Provision a dedicated database

**Do not reuse the Django CMS database.** Use a separate database (ideally a
separate instance/container) to avoid migration collisions, resource
contention, and permission coupling. If your existing Postgres predates
pgvector 0.5.0, run a fresh PG 16/17 container just for Kryten memory.

Server prerequisite: the `vector` extension must be available (Debian/Ubuntu:
`postgresql-16-pgvector`).

Run the setup once as a superuser — see [../sql/001_setup.sql](../sql/001_setup.sql):

```sql
-- as superuser, outside a transaction:
CREATE ROLE kryten LOGIN PASSWORD 'change-me';
CREATE DATABASE kryten_memory OWNER kryten;
\c kryten_memory
CREATE EXTENSION IF NOT EXISTS vector;
GRANT ALL ON SCHEMA public TO kryten;
```

The app auto-creates the `user_facts` table on first connect (schema reference:
[../sql/002_user_facts.sql](../sql/002_user_facts.sql)). The embedding dimension
must match your embedder — the default `all-MiniLM-L6-v2` is `vector(384)`.

## 3. Point the store at Postgres

In your `config.json`, replace the `store` block of the `long_term_memory`
provider. Prefer env-var indirection for the password so no secret lands in
config:

```json
"store": {
  "backend": "pgvector",
  "dsn_env": "KRYTEN_MEMORY_DSN",
  "table": "user_facts",
  "pool_min_size": 1,
  "pool_max_size": 8
}
```

```powershell
$env:KRYTEN_MEMORY_DSN = "postgresql://kryten:change-me@localhost:5432/kryten_memory"
```

Alternatives to `dsn_env`:

- `"dsn": "postgresql://user:pass@host:5432/db"` — literal DSN.
- Discrete parts: `"host"`, `"port"`, `"user"`, `"dbname"`, and either
  `"password_env"` (name of an env var) or `"password"`.

## 4. Concurrency

Because Postgres serialises writes, both processes can run against the same
database safely:

- Live bot: normal service start.
- Seed job: `kryten-llm memory seed --logs 'logs/*.log'` — can run for days
  alongside the live bot.

No Chroma server (`chroma run`) is needed with this backend.

## 5. Migrating existing Chroma data (optional)

If you have salvageable facts in `./data/chroma`, point a one-off script at the
old Chroma store (`get_all`) and the new `PgVectorStore` (`upsert`) — both
implement the same `VectorStore` interface, so the copy is a straight
`get_all -> upsert`. If the Chroma index is already corrupted, just re-run
`memory seed` against a fresh pgvector table instead.

## Notes

- Per-user fact sets are small (cap ~350), so exact cosine search under the
  `username` btree is fast and needs no ANN index.
- The backend stores an embedder-identity fingerprint in the table comment and
  refuses to open a table built with a different embedder (parity with Chroma).
- The forward-looking movie/TV recommendation schema for kryten-webqueue lives
  in [../sql/010_webqueue_items.sql](../sql/010_webqueue_items.sql) and can share
  this same `kryten_memory` database.
