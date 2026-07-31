"""VectorStore interface and ChromaDB implementation.

Phase 7b: REQ-010, CON-004, CON-005.

The ChromaDB backend is only available when ``kryten-llm[memory]`` is
installed.  If ChromaDB is not importable, ``ChromaVectorStore`` raises an
``ImportError`` with a helpful installation message.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Protocol, cast, runtime_checkable

logger = logging.getLogger(__name__)


def _parse_timestamp(value: Any) -> datetime | None:
    """Coerce an ISO-8601 string (or datetime) to a datetime for asyncpg.

    asyncpg binds ``timestamptz`` parameters from ``datetime`` objects, not
    strings. Returns ``None`` for missing/unparseable values so the SQL
    ``COALESCE(..., now())`` fallback applies.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


#: Registry: config ``backend`` → store class.
VECTOR_STORE_REGISTRY: dict[str, Any] = {}


def _register_store(key: str):
    def _dec(cls):
        VECTOR_STORE_REGISTRY[key] = cls
        return cls

    return _dec


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class VectorStore(Protocol):
    """Minimal vector store interface (REQ-010, CON-004)."""

    async def upsert(
        self,
        ids: list[str],
        vectors: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str],
    ) -> None:
        """Insert or update records."""
        ...

    async def query(
        self,
        vector: list[float],
        k: int,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return up to *k* nearest neighbours.

        Each result dict MUST contain at least:
        ``{"id": str, "document": str, "metadata": dict, "distance": float}``.
        """
        ...

    async def delete(self, where: dict[str, Any]) -> None:
        """Delete records matching *where* filter (REQ: forget command)."""
        ...

    async def count(self, where: dict[str, Any] | None = None) -> int:
        """Return number of records, optionally filtered."""
        ...

    async def get_all(self, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Return all records matching *where* (no vector search).

        Each result dict MUST contain at least ``{"id", "document", "metadata"}``.
        Used by the per-user cap eviction path (REQ-014).
        """
        ...

    async def delete_ids(self, ids: list[str]) -> None:
        """Delete records by explicit id list (used by cap eviction)."""
        ...

    async def update_metadata(self, ids: list[str], metadatas: list[dict[str, Any]]) -> None:
        """Update metadata for records by id list (used by compaction, drift sweeper).

        Sprint 19 / Sprint 20.5: added to Protocol so callers can rely on the
        interface rather than using ``getattr`` fallbacks. Both concrete backends
        already implement this method.
        """
        ...

    async def reset(self) -> None:
        """Delete all records from the store (used by `memory reset` CLI, Sprint 20.5).

        For Chroma: deletes and recreates the collection.
        For pgvector: truncates the facts table.
        For FakeStore: clears the in-memory records dict.
        """
        ...


# ---------------------------------------------------------------------------
# ChromaDB backend
# ---------------------------------------------------------------------------


@_register_store("chroma")
class ChromaVectorStore:
    """ChromaDB-backed vector store.

    Requires ``kryten-llm[memory]`` (``chromadb``).
    REQ-010, CON-005.

    Args:
        path: Directory for the persistent ChromaDB database.
        collection: Collection name (default ``"user_facts"``).
        embedder_id: Embedder identity string stored on the collection for
                     mismatch detection (REQ-022).
        dimension: Expected embedding dimension (REQ-022).
    """

    def __init__(
        self,
        path: str,
        collection: str = "user_facts",
        embedder_id: str = "",
        dimension: int = 0,
        http_host: str = "",
        http_port: int = 8000,
    ):
        self._path = path
        self._collection_name = collection
        self._embedder_id = embedder_id
        self._dimension = dimension
        self._http_host = http_host
        self._http_port = http_port
        self._client: Any = None  # chromadb.PersistentClient / HttpClient or None
        self._collection: Any = None  # chromadb.Collection or None

    @classmethod
    def from_config(
        cls, cfg: dict[str, Any], embedder_id: str = "", dimension: int = 0
    ) -> "ChromaVectorStore":
        http_host = cfg.get("http_host", "")
        http_port = int(cfg.get("http_port", 8000))
        return cls(
            path=cfg.get("path", "./data/chroma"),
            collection=cfg.get("collection", "user_facts"),
            embedder_id=embedder_id,
            dimension=dimension,
            http_host=http_host,
            http_port=http_port,
        )

    def _ensure_connected(self) -> None:
        """Lazy-connect to ChromaDB and validate embedder identity (REQ-022)."""
        if self._collection is not None:
            return

        try:
            import chromadb  # type: ignore[import-not-found,import-untyped]
        except ImportError as exc:
            raise ImportError(
                "chromadb is required for long-term memory. "
                "Install it with: pip install 'kryten-llm[memory]'"
            ) from exc

        if self._http_host:
            # HTTP client — connects to a running ``chroma run`` server.
            # Safe for concurrent multi-process access (seed + live service).
            self._client = chromadb.HttpClient(host=self._http_host, port=self._http_port)
            logger.info(f"ChromaDB connected via HTTP to {self._http_host}:{self._http_port}")
        else:
            self._client = chromadb.PersistentClient(path=self._path)

        # REQ-022: Check embedder identity stored on the collection
        existing = self._client.list_collections()
        existing_names = [c.name for c in existing]

        if self._collection_name in existing_names:
            coll = self._client.get_collection(self._collection_name)
            stored_meta = coll.metadata or {}
            stored_eid = stored_meta.get("embedder_id", "")
            stored_dim = stored_meta.get("dimension", 0)

            if stored_eid and self._embedder_id and stored_eid != self._embedder_id:
                raise RuntimeError(
                    f"Embedder identity mismatch: collection was created with "
                    f"'{stored_eid}' (dim={stored_dim}) but current embedder is "
                    f"'{self._embedder_id}' (dim={self._dimension}). "
                    "Re-embed the collection or change the collection name."
                )
            stored_space = stored_meta.get("hnsw:space", "l2")
            if stored_space != "cosine":
                raise RuntimeError(
                    f"ChromaDB collection '{self._collection_name}' was created with "
                    f"distance metric '{stored_space}' (expected 'cosine'). "
                    "Delete the collection directory and re-run 'memory seed' to "
                    "recreate it with the correct cosine metric."
                )
            self._collection = coll
        else:
            meta: dict[str, Any] = {}
            if self._embedder_id:
                meta["embedder_id"] = self._embedder_id
            if self._dimension:
                meta["dimension"] = self._dimension

            self._collection = self._client.create_collection(
                name=self._collection_name,
                # cosine distance: distance = 1 − cosine_similarity → range [0, 2].
                # The gate formula (max_distance = 1 − min_similarity) and the
                # similarity display (sim = 1 − distance) are both correct only
                # with cosine distance, NOT the L2 default.
                metadata={"hnsw:space": "cosine", **(meta if meta else {})},
            )
            logger.info(
                f"Created ChromaDB collection '{self._collection_name}' "
                f"(embedder={self._embedder_id}, dim={self._dimension})"
            )

    async def upsert(
        self,
        ids: list[str],
        vectors: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str],
    ) -> None:
        self._ensure_connected()
        self._collection.upsert(
            ids=ids,
            embeddings=vectors,
            metadatas=metadatas,
            documents=documents,
        )
        logger.debug(f"ChromaDB upserted {len(ids)} record(s)")

    async def query(
        self,
        vector: list[float],
        k: int,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_connected()
        kwargs: dict[str, Any] = {
            "query_embeddings": [vector],
            "n_results": k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        try:
            result = self._collection.query(**kwargs)
        except Exception as exc:
            logger.warning(f"ChromaDB query failed: {exc}")
            return []

        records = []
        ids_list = result.get("ids", [[]])[0]
        docs_list = result.get("documents", [[]])[0]
        metas_list = result.get("metadatas", [[]])[0]
        dists_list = result.get("distances", [[]])[0]

        for rid, doc, meta, dist in zip(ids_list, docs_list, metas_list, dists_list):
            records.append({"id": rid, "document": doc, "metadata": meta or {}, "distance": dist})
        return records

    async def delete(self, where: dict[str, Any]) -> None:
        self._ensure_connected()
        # ChromaDB delete by where filter
        try:
            results = self._collection.get(where=where, include=["documents"])
            ids_to_delete = results.get("ids", [])
            if ids_to_delete:
                self._collection.delete(ids=ids_to_delete)
                logger.info(f"ChromaDB deleted {len(ids_to_delete)} record(s) for filter {where}")
        except Exception as exc:
            logger.error(f"ChromaDB delete failed: {exc}", exc_info=True)
            raise

    async def count(self, where: dict[str, Any] | None = None) -> int:
        self._ensure_connected()
        try:
            if where:
                results = self._collection.get(where=where, include=["documents"])
                return len(results.get("ids", []))
            return self._collection.count()  # type: ignore[no-any-return]
        except Exception as exc:
            logger.warning(f"ChromaDB count failed: {exc}")
            return 0

    async def get_all(self, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self._ensure_connected()
        try:
            kwargs: dict[str, Any] = {"include": ["metadatas", "documents"]}
            if where:
                kwargs["where"] = where
            result = self._collection.get(**kwargs)
            ids = result.get("ids", []) or []
            metas = result.get("metadatas", []) or []
            docs = result.get("documents", []) or []
            return [
                {"id": i, "document": d, "metadata": m or {}} for i, d, m in zip(ids, docs, metas)
            ]
        except Exception as exc:
            logger.warning(f"ChromaDB get_all failed: {exc}")
            return []

    async def delete_ids(self, ids: list[str]) -> None:
        self._ensure_connected()
        if not ids:
            return
        try:
            self._collection.delete(ids=ids)
        except Exception as exc:
            logger.error(f"ChromaDB delete_ids failed: {exc}", exc_info=True)
            raise

    async def get_metadata(self, ids: list[str]) -> list[dict[str, Any]]:
        """Return metadata dicts for *ids* (Phase 7f importance bump support)."""
        self._ensure_connected()
        try:
            result = self._collection.get(ids=ids, include=["metadatas"])
            metas = result.get("metadatas") or []
            return [dict(m or {}) for m in metas]
        except Exception as exc:
            logger.warning(f"ChromaDB get_metadata failed: {exc}")
            return []

    async def update_metadata(self, ids: list[str], metadatas: list[dict[str, Any]]) -> None:
        """Update metadata only for existing records (Phase 7f, REQ-033/034)."""
        self._ensure_connected()
        try:
            self._collection.update(ids=ids, metadatas=metadatas)
        except Exception as exc:
            logger.warning(f"ChromaDB update_metadata failed: {exc}")

    async def reset(self) -> None:
        """Delete and recreate the collection (Sprint 20.5, memory reset CLI)."""
        self._ensure_connected()
        try:
            self._client.delete_collection(self._collection_name)
            self._collection = self._client.get_or_create_collection(
                self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("ChromaVectorStore.reset: collection recreated (%s)", self._collection_name)
        except Exception as exc:
            logger.error("ChromaVectorStore.reset failed: %s", exc)
            raise

    @property
    def store_mode(self) -> str:
        """Return the active connection mode for observability (Sprint 17, REQ-345)."""
        return "chroma-http" if self._http_host else "chroma-embedded"


@_register_store("pgvector")
class PgVectorStore:
    """PostgreSQL + ``pgvector`` backed vector store.

    Safe for concurrent multi-process access (the DB server serialises writes),
    which the embedded Chroma ``PersistentClient`` is not. Requires
    ``kryten-llm[pgvector]`` (``asyncpg`` + ``pgvector``) and a Postgres server
    with the ``vector`` extension available.

    Schema (auto-created on first connect)::

        CREATE TABLE {table} (
            id         text PRIMARY KEY,
            username   text NOT NULL,
            document   text NOT NULL,
            embedding  vector({dim}) NOT NULL,
            metadata   jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX {table}_username_idx ON {table} (username);

    ``username`` is promoted out of ``metadata['user']`` to a first-class,
    indexed column because the fact store is queried and capped per-user. The
    full metadata dict is still stored in ``metadata`` (jsonb) for parity with
    the Chroma backend.
    """

    _IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(
        self,
        dsn: str,
        table: str = "user_facts",
        embedder_id: str = "",
        dimension: int = 0,
        pool_min_size: int = 1,
        pool_max_size: int = 8,
    ):
        if not self._IDENT_RE.match(table):
            raise ValueError(
                f"Invalid pgvector table name '{table}'. Must match {self._IDENT_RE.pattern}."
            )
        self._dsn = dsn
        self._table = table
        self._embedder_id = embedder_id
        self._dimension = dimension
        self._pool_min_size = pool_min_size
        self._pool_max_size = pool_max_size
        self._pool: Any = None
        self._connect_lock = asyncio.Lock()

    @classmethod
    def from_config(
        cls, cfg: dict[str, Any], embedder_id: str = "", dimension: int = 0
    ) -> "PgVectorStore":
        dsn = cls._resolve_dsn(cfg)
        return cls(
            dsn=dsn,
            table=cfg.get("table", "user_facts"),
            embedder_id=embedder_id,
            dimension=dimension,
            pool_min_size=int(cfg.get("pool_min_size", 1)),
            pool_max_size=int(cfg.get("pool_max_size", 8)),
        )

    @staticmethod
    def _resolve_dsn(cfg: dict[str, Any]) -> str:
        """Resolve the connection DSN, preferring env-var indirection for secrets.

        Precedence: ``dsn_env`` (env var holding a full DSN) → ``dsn`` (literal)
        → assembled from ``host``/``port``/``user``/``dbname`` with the password
        taken from ``password_env`` (preferred) or ``password``.
        """
        dsn_env = cfg.get("dsn_env")
        if dsn_env:
            val = os.environ.get(dsn_env)
            if not val:
                raise ValueError(f"pgvector dsn_env '{dsn_env}' is set but the env var is empty")
            return val
        if cfg.get("dsn"):
            return str(cfg["dsn"])
        host = cfg.get("host", "localhost")
        port = int(cfg.get("port", 5432))
        user = cfg.get("user", "kryten")
        dbname = cfg.get("dbname", "kryten_memory")
        if cfg.get("password_env"):
            password = os.environ.get(cfg["password_env"], "")
        else:
            password = cfg.get("password", "")
        return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

    # ------------------------------------------------------------------
    # Connection / schema
    # ------------------------------------------------------------------

    async def _ensure_connected(self) -> None:
        if self._pool is not None:
            return
        async with self._connect_lock:
            if self._pool is not None:
                return

            try:
                import asyncpg  # type: ignore[import-not-found,import-untyped]
                from pgvector.asyncpg import (  # type: ignore[import-not-found,import-untyped]
                    register_vector,
                )
            except ImportError as exc:
                raise ImportError(
                    "asyncpg and pgvector are required for the pgvector backend. "
                    "Install them with: pip install 'kryten-llm[pgvector]'"
                ) from exc

            if self._dimension <= 0:
                raise RuntimeError(
                    "pgvector backend needs a positive embedding dimension; the "
                    "configured embedder did not report one."
                )

            async def _init_conn(conn: Any) -> None:
                # Encode/decode jsonb transparently as Python dicts.
                await conn.set_type_codec(
                    "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
                )
                await register_vector(conn)

            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._pool_min_size,
                max_size=self._pool_max_size,
                init=_init_conn,
            )
            async with self._pool.acquire() as conn:
                await self._ensure_schema(conn)
            logger.info(
                f"pgvector connected (table={self._table}, dim={self._dimension}, "
                f"pool={self._pool_min_size}-{self._pool_max_size})"
            )

    async def _ensure_schema(self, conn: Any) -> None:
        t = self._table
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception as exc:
            # Non-superusers cannot create extensions; the DBA must run the
            # setup SQL once. If the extension is genuinely missing the table
            # creation below will fail with a clear error.
            logger.debug(f"CREATE EXTENSION vector skipped/failed (may need a DBA): {exc}")

        await conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {t} (
                id         text PRIMARY KEY,
                username   text NOT NULL,
                document   text NOT NULL,
                embedding  vector({self._dimension}) NOT NULL,
                metadata   jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                created_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute(f"CREATE INDEX IF NOT EXISTS {t}_username_idx ON {t} (username)")

        # Embedder identity check (parity with Chroma REQ-022), stored as a
        # JSON blob in the table comment.
        existing = await conn.fetchval(f"SELECT obj_description('{t}'::regclass)")
        if existing:
            try:
                prev = json.loads(existing)
            except (json.JSONDecodeError, TypeError):
                prev = {}
            prev_eid = prev.get("embedder_id", "")
            prev_dim = prev.get("dimension", 0)
            if prev_eid and self._embedder_id and prev_eid != self._embedder_id:
                raise RuntimeError(
                    f"Embedder identity mismatch: table '{t}' was created with "
                    f"'{prev_eid}' (dim={prev_dim}) but current embedder is "
                    f"'{self._embedder_id}' (dim={self._dimension}). "
                    "Re-embed the table or use a different table name."
                )
        else:
            identity = json.dumps({"embedder_id": self._embedder_id, "dimension": self._dimension})
            # $kryten$ dollar-quoting avoids any escaping issues with the JSON.
            await conn.execute(f"COMMENT ON TABLE {t} IS $kryten${identity}$kryten$")

    # ------------------------------------------------------------------
    # where → SQL translation
    # ------------------------------------------------------------------

    @staticmethod
    def _build_where(where: dict[str, Any] | None, start_idx: int) -> tuple[str, list[Any], int]:
        """Translate a ``where`` dict into a parameterised SQL clause.

        ``{"user": name}`` targets the indexed ``username`` column; any other
        key is matched against ``metadata ->> key``. Values may be a scalar
        (equality) or an operator dict ``{"$in": [...]}`` / ``{"$ne": v}``
        (Sprint 8, Sortie 0, REQ-041). All keys and values are passed as bound
        parameters (no interpolation) to prevent injection.
        """
        clauses: list[str] = []
        params: list[Any] = []
        idx = start_idx
        for key, val in (where or {}).items():
            is_user = key == "user"
            if isinstance(val, dict) and ("$in" in val or "$ne" in val):
                if "$in" in val:
                    values = list(val["$in"])
                    if is_user:
                        clauses.append(f"username = ANY(${idx})")
                        params.append([str(v) for v in values])
                        idx += 1
                    else:
                        clauses.append(f"(metadata ->> ${idx}) = ANY(${idx + 1})")
                        params.append(str(key))
                        params.append([str(v) for v in values])
                        idx += 2
                if "$ne" in val:
                    ne_val = val["$ne"]
                    if is_user:
                        clauses.append(f"username <> ${idx}")
                        params.append(str(ne_val))
                        idx += 1
                    else:
                        clauses.append(f"(metadata ->> ${idx}) <> ${idx + 1}")
                        params.append(str(key))
                        params.append(str(ne_val))
                        idx += 2
            elif is_user:
                clauses.append(f"username = ${idx}")
                params.append(val)
                idx += 1
            else:
                clauses.append(f"(metadata ->> ${idx}) = ${idx + 1}")
                params.append(str(key))
                params.append(str(val))
                idx += 2
        sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return sql, params, idx

    # ------------------------------------------------------------------
    # VectorStore interface
    # ------------------------------------------------------------------

    async def upsert(
        self,
        ids: list[str],
        vectors: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str],
    ) -> None:
        await self._ensure_connected()
        t = self._table
        rows = [
            (
                fid,
                str(meta.get("user", "")),
                doc,
                list(vec),
                meta,
                _parse_timestamp(meta.get("created_at")),
            )
            for fid, vec, meta, doc in zip(ids, vectors, metadatas, documents)
        ]
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    f"""
                    INSERT INTO {t} (id, username, document, embedding, metadata, created_at)
                    VALUES ($1, $2, $3, $4, $5, COALESCE($6, now()))
                    ON CONFLICT (id) DO UPDATE SET
                        username = EXCLUDED.username,
                        document = EXCLUDED.document,
                        embedding = EXCLUDED.embedding,
                        metadata = EXCLUDED.metadata
                    """,
                    rows,
                )
        logger.debug(f"pgvector upserted {len(ids)} record(s)")

    async def query(
        self,
        vector: list[float],
        k: int,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        await self._ensure_connected()
        t = self._table
        where_sql, params, next_idx = self._build_where(where, 2)
        sql = (
            f"SELECT id, document, metadata, (embedding <=> $1) AS distance "
            f"FROM {t} {where_sql} ORDER BY embedding <=> $1 LIMIT ${next_idx}"
        )
        try:
            async with self._pool.acquire() as conn:
                records = await conn.fetch(sql, list(vector), *params, k)
        except Exception as exc:
            logger.warning(f"pgvector query failed: {exc}")
            return []
        return [
            {
                "id": r["id"],
                "document": r["document"],
                "metadata": r["metadata"] or {},
                "distance": float(r["distance"]),
            }
            for r in records
        ]

    async def delete(self, where: dict[str, Any]) -> None:
        await self._ensure_connected()
        if not where:
            raise ValueError("pgvector delete requires a non-empty where filter")
        t = self._table
        where_sql, params, _ = self._build_where(where, 1)
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(f"DELETE FROM {t} {where_sql}", *params)
            logger.info(f"pgvector delete {result} for filter {where}")
        except Exception as exc:
            logger.error(f"pgvector delete failed: {exc}", exc_info=True)
            raise

    async def count(self, where: dict[str, Any] | None = None) -> int:
        await self._ensure_connected()
        t = self._table
        where_sql, params, _ = self._build_where(where, 1)
        try:
            async with self._pool.acquire() as conn:
                val = await conn.fetchval(f"SELECT count(*) FROM {t} {where_sql}", *params)
            return int(val or 0)
        except Exception as exc:
            logger.warning(f"pgvector count failed: {exc}")
            return 0

    async def get_all(self, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        await self._ensure_connected()
        t = self._table
        where_sql, params, _ = self._build_where(where, 1)
        try:
            async with self._pool.acquire() as conn:
                records = await conn.fetch(
                    f"SELECT id, document, metadata FROM {t} {where_sql}", *params
                )
        except Exception as exc:
            logger.warning(f"pgvector get_all failed: {exc}")
            return []
        return [
            {"id": r["id"], "document": r["document"], "metadata": r["metadata"] or {}}
            for r in records
        ]

    async def delete_ids(self, ids: list[str]) -> None:
        await self._ensure_connected()
        if not ids:
            return
        t = self._table
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(f"DELETE FROM {t} WHERE id = ANY($1::text[])", list(ids))
        except Exception as exc:
            logger.error(f"pgvector delete_ids failed: {exc}", exc_info=True)
            raise

    async def get_metadata(self, ids: list[str]) -> list[dict[str, Any]]:
        await self._ensure_connected()
        t = self._table
        try:
            async with self._pool.acquire() as conn:
                records = await conn.fetch(
                    f"SELECT id, metadata FROM {t} WHERE id = ANY($1::text[])", list(ids)
                )
        except Exception as exc:
            logger.warning(f"pgvector get_metadata failed: {exc}")
            return []
        by_id = {r["id"]: (r["metadata"] or {}) for r in records}
        return [dict(by_id.get(i, {})) for i in ids]

    async def update_metadata(self, ids: list[str], metadatas: list[dict[str, Any]]) -> None:
        await self._ensure_connected()
        t = self._table
        rows = [(fid, meta) for fid, meta in zip(ids, metadatas)]
        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.executemany(f"UPDATE {t} SET metadata = $2 WHERE id = $1", rows)
        except Exception as exc:
            logger.warning(f"pgvector update_metadata failed: {exc}")

    async def reset(self) -> None:
        """Truncate the facts table (Sprint 20.5, memory reset CLI)."""
        await self._ensure_connected()
        t = self._table
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(f'TRUNCATE TABLE "{t}"')
            logger.info("PgVectorStore.reset: table truncated (%s)", t)
        except Exception as exc:
            logger.error("PgVectorStore.reset failed: %s", exc)
            raise

    @property
    def store_mode(self) -> str:
        """Return the backend type for observability (Sprint 17, REQ-345)."""
        return "pgvector"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_vector_store(
    cfg: dict[str, Any],
    embedder_id: str = "",
    dimension: int = 0,
) -> VectorStore:
    """Instantiate a vector store from a config dict."""
    backend = cfg.get("backend", "chroma")
    cls = VECTOR_STORE_REGISTRY.get(backend)
    if cls is None:
        raise ValueError(
            f"Unknown vector store backend '{backend}'. Known: {list(VECTOR_STORE_REGISTRY)}"
        )
    return cast(VectorStore, cls.from_config(cfg, embedder_id=embedder_id, dimension=dimension))
