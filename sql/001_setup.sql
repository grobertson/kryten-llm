-- Kryten memory: PostgreSQL + pgvector setup (run once, as a superuser/DBA).
--
-- This provisions a DEDICATED database for Kryten's vector memory. Do NOT
-- reuse the Django CMS database — keep this isolated to avoid migration
-- collisions, resource contention, and permission coupling.
--
-- Requires: PostgreSQL 13+ and the pgvector extension available on the server
-- (package `postgresql-16-pgvector` on Debian/Ubuntu, or build from source).
-- HNSW indexing needs pgvector >= 0.5.0; per-user exact search (used by the
-- fact store) does not require any ANN index at all.

-- 1. Role + database (edit the password before running; prefer a secret store).
--    Run these two as a superuser, OUTSIDE a transaction:
--
--    CREATE ROLE kryten LOGIN PASSWORD 'change-me';
--    CREATE DATABASE kryten_memory OWNER kryten;
--
-- 2. Then connect to the new database and enable the extension:
--    \c kryten_memory
CREATE EXTENSION IF NOT EXISTS vector;

-- 3. The application auto-creates its own tables on first connect, but the
--    role needs privileges to do so:
GRANT ALL ON SCHEMA public TO kryten;

-- The `user_facts` table (see 002_user_facts.sql) is created automatically by
-- PgVectorStore. It is reproduced there for reference and for environments
-- where the app role is not allowed to run DDL.
