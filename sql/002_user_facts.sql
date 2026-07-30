-- Kryten memory: user_facts table (reference).
--
-- PgVectorStore auto-creates this on first connect. This file is provided so a
-- DBA can pre-create it (e.g. when the app role may not run DDL) and so the
-- schema is documented alongside the code.
--
-- NOTE the embedding dimension: it MUST match the configured embedder.
--   all-MiniLM-L6-v2 (default onnx embedder) -> vector(384)
-- If you change the embedder, use a different table (the app enforces an
-- embedder-identity check stored in the table comment).

CREATE TABLE IF NOT EXISTS user_facts (
    id         text PRIMARY KEY,               -- stable_fact_id(user, summary)
    username   text NOT NULL,                  -- promoted from metadata->>'user'
    document   text NOT NULL,                  -- the paraphrased fact summary
    embedding  vector(384) NOT NULL,           -- must match embedder dimension
    metadata   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Primary access pattern is "filter by user, then vector-rank", so index the
-- username column. Per-user fact sets are tiny (cap ~350), so exact cosine
-- search under this btree is fast and needs no ANN index.
CREATE INDEX IF NOT EXISTS user_facts_username_idx ON user_facts (username);

-- OPTIONAL: only worthwhile if a single user's set grows large or you drop the
-- per-user filter. cosine ops => vector_cosine_ops.
-- CREATE INDEX user_facts_embedding_hnsw
--     ON user_facts USING hnsw (embedding vector_cosine_ops);
