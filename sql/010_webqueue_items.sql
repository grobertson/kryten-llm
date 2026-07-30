-- Kryten-WebQueue: movie/TV item embeddings + recommendation schema (SKETCH).
--
-- FORWARD-LOOKING: this is a design sketch for the upcoming recommendation
-- feature. It is conceptually OWNED BY kryten-webqueue (not kryten-llm) and is
-- included here so the pgvector rollout accounts for it. The chatbot will not
-- read these tables directly — it will ask kryten-webqueue over NATS
-- (`kryten.webqueue.command`, e.g. "recommend for user X") and webqueue runs
-- the vector query.
--
-- These tables can live in the SAME `kryten_memory` database as `user_facts`.
-- Co-locating them is the whole point: a recommender can JOIN item vectors
-- against relational watch history AND (optionally) against the user_facts
-- preference rows in one query — something two separate vector engines cannot do.
--
-- Catalog scale target: ~10k items now, unlikely to exceed ~20k. At that size
-- exact cosine search is fast; the HNSW index below is optional.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- 1. The catalog: one row per movie / show. Shared across all users.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS media_items (
    id          text PRIMARY KEY,              -- internal stable id
    external_id text,                          -- tmdb/imdb id (nullable)
    media_type  text NOT NULL,                 -- 'movie' | 'tv'
    title       text NOT NULL,
    year        int,
    genres      text[] NOT NULL DEFAULT '{}',  -- e.g. {'sci-fi','comedy'}
    description text NOT NULL DEFAULT '',
    embedding   vector(384) NOT NULL,          -- embed(title + description + genres)
    metadata    jsonb NOT NULL DEFAULT '{}'::jsonb,  -- runtime, poster url, availability, ...
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Filter-friendly indexes for the structured predicates a recommender uses.
CREATE INDEX IF NOT EXISTS media_items_type_idx  ON media_items (media_type);
CREATE INDEX IF NOT EXISTS media_items_year_idx  ON media_items (year);
CREATE INDEX IF NOT EXISTS media_items_genres_gin ON media_items USING gin (genres);

-- OPTIONAL ANN index (only if exact search becomes a bottleneck at scale):
-- CREATE INDEX media_items_embedding_hnsw
--     ON media_items USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- 2. Per-user history: the user x item relation that powers "don't recommend
--    what they've already seen" and builds a taste profile. Grows over time.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_watch_history (
    username   text NOT NULL,
    item_id    text NOT NULL REFERENCES media_items (id) ON DELETE CASCADE,
    source     text NOT NULL DEFAULT 'watched',  -- 'watched' | 'queued' | 'skipped'
    rating     real,                             -- optional explicit signal (0..1)
    watched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (username, item_id)
);

CREATE INDEX IF NOT EXISTS user_watch_history_user_idx ON user_watch_history (username);

-- ---------------------------------------------------------------------------
-- 3. Example recommendation query (content-based, personalised).
--
--    Build a taste profile = mean embedding of what the user liked, then find
--    the nearest catalog items they HAVEN'T already seen, filtered by type.
--    All the "already watched" / metadata filtering is a plain SQL JOIN — the
--    ergonomic win that keeps this in Postgres rather than a pure vector store.
-- ---------------------------------------------------------------------------
--
--  WITH profile AS (
--      SELECT avg(mi.embedding) AS vec
--      FROM   user_watch_history h
--      JOIN   media_items mi ON mi.id = h.item_id
--      WHERE  h.username = $1
--        AND  h.source = 'watched'
--        AND  coalesce(h.rating, 1.0) >= 0.5
--  )
--  SELECT mi.id, mi.title, mi.year, mi.genres,
--         (mi.embedding <=> (SELECT vec FROM profile)) AS distance
--  FROM   media_items mi
--  WHERE  mi.media_type = $2
--    AND  NOT EXISTS (
--             SELECT 1 FROM user_watch_history h
--             WHERE h.username = $1 AND h.item_id = mi.id
--         )
--  ORDER BY mi.embedding <=> (SELECT vec FROM profile)
--  LIMIT $3;
--
--  Cold-start (no history): fall back to similarity against an ad-hoc query
--  embedding (e.g. "80s cyberpunk"), or to popularity from metadata.
--
--  Cross-domain (optional): the taste profile can be enriched by JOINing the
--  kryten-llm `user_facts` rows where category = 'preference' — same database,
--  one query.
