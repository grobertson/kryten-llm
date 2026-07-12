"""VectorStore interface and ChromaDB implementation.

Phase 7b: REQ-010, CON-004, CON-005.

The ChromaDB backend is only available when ``kryten-llm[memory]`` is
installed.  If ChromaDB is not importable, ``ChromaVectorStore`` raises an
``ImportError`` with a helpful installation message.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

#: Registry: config ``backend`` → store class.
VECTOR_STORE_REGISTRY: dict[str, type] = {}


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
    ):
        self._path = path
        self._collection_name = collection
        self._embedder_id = embedder_id
        self._dimension = dimension
        self._client = None
        self._collection = None

    @classmethod
    def from_config(cls, cfg: dict[str, Any], embedder_id: str = "", dimension: int = 0) -> "ChromaVectorStore":
        return cls(
            path=cfg.get("path", "./data/chroma"),
            collection=cfg.get("collection", "user_facts"),
            embedder_id=embedder_id,
            dimension=dimension,
        )

    def _ensure_connected(self) -> None:
        """Lazy-connect to ChromaDB and validate embedder identity (REQ-022)."""
        if self._collection is not None:
            return

        try:
            import chromadb  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "chromadb is required for long-term memory. "
                "Install it with: pip install 'kryten-llm[memory]'"
            ) from exc

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
            self._collection = coll
        else:
            meta: dict[str, Any] = {}
            if self._embedder_id:
                meta["embedder_id"] = self._embedder_id
            if self._dimension:
                meta["dimension"] = self._dimension

            self._collection = self._client.create_collection(
                name=self._collection_name,
                metadata=meta if meta else None,
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
            records.append(
                {"id": rid, "document": doc, "metadata": meta or {}, "distance": dist}
            )
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
            return self._collection.count()
        except Exception as exc:
            logger.warning(f"ChromaDB count failed: {exc}")
            return 0


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
        raise ValueError(f"Unknown vector store backend '{backend}'. Known: {list(VECTOR_STORE_REGISTRY)}")
    return cls.from_config(cfg, embedder_id=embedder_id, dimension=dimension)
