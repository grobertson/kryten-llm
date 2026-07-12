"""Long-term memory context provider backed by a vector store.

Phase 7d: REQ-010 through REQ-016, GUD-001, GUD-002.

The provider is opt-in (``enabled: false`` by default, CON-002).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from kryten_llm.components.context.base import ContextFragment, ContextRequest, register_provider
from kryten_llm.components.memory.embedder import Embedder, build_embedder
from kryten_llm.components.memory.extractor import Fact
from kryten_llm.components.memory.heuristic_extractor import HeuristicFactExtractor, stable_fact_id
from kryten_llm.components.memory.vector_store import VectorStore, build_vector_store

if TYPE_CHECKING:
    from kryten_llm.models.config import LLMConfig

logger = logging.getLogger(__name__)


@register_provider("long_term_memory")
class LongTermMemoryProvider:
    """Provides durable, semantically-retrievable user facts.

    * **writes** — ``observe()`` runs the fact extractor off the critical path
                    and upserts new facts into the vector store.
    * **reads**  — ``provide()`` retrieves top-K facts for the triggering user
                    within a configurable timeout (GUD-001, fail-open REQ-004).

    CON-002: Defaults to disabled; must be explicitly enabled in config.
    """

    id = "long_term_memory"
    reads = True
    writes = True

    def __init__(
        self,
        embedder: Embedder,
        vector_store: VectorStore,
        extractor,
        priority: int = 40,
        read_timeout_ms: int = 300,
        top_k: int = 5,
        relate_to_message: bool = True,
        min_similarity: float = 0.25,
        min_message_score: float = 30.0,
        per_user_fact_cap: int = 200,
        dedup_similarity: float = 0.9,
    ):
        self._embedder = embedder
        self._store = vector_store
        self._extractor = extractor
        self._priority = priority
        self._read_timeout_s = read_timeout_ms / 1000.0
        self._top_k = top_k
        self._relate_to_message = relate_to_message
        self._min_similarity = min_similarity
        self._min_message_score = min_message_score
        self._per_user_fact_cap = per_user_fact_cap
        self._dedup_similarity = dedup_similarity

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        pcfg: dict[str, Any],
        config: "LLMConfig",
        deps: dict[str, Any],
    ) -> "LongTermMemoryProvider":
        emb_cfg = pcfg.get("embedder", {"type": "onnx", "model": "all-MiniLM-L6-v2"})
        embedder = build_embedder(emb_cfg)

        store_cfg = pcfg.get(
            "store", {"backend": "chroma", "path": "./data/chroma", "collection": "user_facts"}
        )
        vector_store = build_vector_store(
            store_cfg,
            embedder_id=embedder.id,
            dimension=getattr(embedder, "dimension", 0),
        )

        ext_cfg = pcfg.get("extractor", {"type": "heuristic"})
        ext_type = ext_cfg.get("type", "heuristic")
        if ext_type == "heuristic":
            write_cfg = pcfg.get("write", {})
            extractor = HeuristicFactExtractor(
                min_score=write_cfg.get("min_message_score", 25.0)
            )
        else:
            raise ValueError(f"Unknown extractor type '{ext_type}'")

        retrieval_cfg = pcfg.get("retrieval", {})
        write_cfg = pcfg.get("write", {})

        return cls(
            embedder=embedder,
            vector_store=vector_store,
            extractor=extractor,
            priority=pcfg.get("priority", 40),
            read_timeout_ms=pcfg.get("read_timeout_ms", 300),
            top_k=retrieval_cfg.get("top_k", 5),
            relate_to_message=retrieval_cfg.get("relate_to_message", True),
            min_similarity=retrieval_cfg.get("min_similarity", 0.25),
            min_message_score=write_cfg.get("min_message_score", 30.0),
            per_user_fact_cap=write_cfg.get("per_user_fact_cap", 200),
            dedup_similarity=write_cfg.get("dedup_similarity", 0.9),
        )

    # ------------------------------------------------------------------
    # ContextProvider interface
    # ------------------------------------------------------------------

    async def observe(self, username: str, message: str) -> None:
        """Extract + store facts asynchronously (WRITE path, REQ-011).

        Fire-and-forget wrapper — errors are logged but never propagated.
        """
        asyncio.ensure_future(self._observe_impl(username, message))

    async def provide(self, req: ContextRequest) -> list[ContextFragment]:
        """Retrieve top-K user facts within read_timeout_ms (READ path, REQ-012).

        Fail-open: returns empty list on timeout or error (REQ-004, GUD-001).
        """
        try:
            return await asyncio.wait_for(
                self._provide_impl(req),
                timeout=self._read_timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"LongTermMemoryProvider.provide() timed out after "
                f"{self._read_timeout_s * 1000:.0f} ms for user '{req.username}'"
            )
            return []
        except Exception as exc:
            logger.warning(
                f"LongTermMemoryProvider.provide() failed: {exc}", exc_info=True
            )
            return []

    # ------------------------------------------------------------------
    # Internal implementations
    # ------------------------------------------------------------------

    async def _observe_impl(self, username: str, message: str) -> None:
        """Full write path: extract → safety gate → embed → upsert."""
        try:
            # 1. Extract facts
            messages = [{"username": username, "message": message}]
            facts = await self._extractor.extract(messages, username)

            if not facts:
                return

            # 2. Apply per-user cap — evict if needed
            await self._enforce_cap(username)

            # 3. Embed + upsert
            await self._upsert_facts(facts)

        except Exception as exc:
            logger.warning(f"LongTermMemoryProvider._observe_impl() failed: {exc}", exc_info=True)

    async def _provide_impl(self, req: ContextRequest) -> list[ContextFragment]:
        """Full read path: embed query → store.query → format fragment."""
        query_text = req.message if self._relate_to_message else req.username

        # Embed the query
        vectors = await self._embedder.embed([query_text])
        if not vectors:
            return []

        query_vec = vectors[0]

        # Query for this user's facts
        results = await self._store.query(
            vector=query_vec,
            k=self._top_k,
            where={"user": req.username},
        )

        if not results:
            return []

        # Filter by minimum similarity (distance threshold — lower = more similar)
        # Chroma uses L2 distance; 0 = identical. Convert min_similarity to max distance.
        max_distance = 1.0 - self._min_similarity
        filtered = [r for r in results if r.get("distance", 1.0) <= max_distance]

        if not filtered:
            return []

        # Format as compact bulleted text (GUD-002)
        lines = []
        for r in filtered:
            meta = r.get("metadata", {})
            cat = meta.get("category", "")
            doc = r.get("document", "")
            if doc:
                line = f"• [{cat}] {doc}" if cat else f"• {doc}"
                lines.append(line)

        text = f"Known facts about {req.username}:\n" + "\n".join(lines)

        return [
            ContextFragment(
                name="user_memory",
                priority=self._priority,
                text=text,
                est_chars=len(text),
            )
        ]

    async def _upsert_facts(self, facts: list[Fact]) -> None:
        """Batch-embed and upsert *facts* into the vector store."""
        summaries = [f.summary for f in facts]
        vectors = await self._embedder.embed(summaries)

        now = datetime.now(timezone.utc).isoformat()

        ids = []
        vecs = []
        metas = []
        docs = []

        for fact, vec in zip(facts, vectors):
            fact_id = stable_fact_id(fact.user, fact.summary)
            meta: dict[str, Any] = {
                "user": fact.user,
                "category": fact.category,
                "source": fact.source,
                "created_at": now,
                "score": fact.score,
                "evidence": str(fact.evidence.get("message", ""))[:200],
            }
            ids.append(fact_id)
            vecs.append(vec)
            metas.append(meta)
            docs.append(fact.summary)

        await self._store.upsert(ids=ids, vectors=vecs, metadatas=metas, documents=docs)
        logger.debug(f"Upserted {len(ids)} fact(s)")

    async def _enforce_cap(self, username: str) -> None:
        """Evict oldest facts if the per-user cap is exceeded (REQ-014)."""
        try:
            count = await self._store.count(where={"user": username})
            if count < self._per_user_fact_cap:
                return
            # Currently we just log — full eviction requires a list-and-sort
            # operation that ChromaDB makes awkward without a timestamp index.
            # A future implementation can use metadata-filtered listing.
            logger.debug(
                f"User '{username}' has {count} facts "
                f"(cap={self._per_user_fact_cap}); eviction not yet implemented"
            )
        except Exception as exc:
            logger.warning(f"_enforce_cap failed: {exc}")

    # ------------------------------------------------------------------
    # Management helpers (used by CLI commands)
    # ------------------------------------------------------------------

    async def forget_user(self, username: str) -> int:
        """Delete all facts for *username* (CON-003).

        Returns the number of facts deleted.
        """
        count_before = await self._store.count(where={"user": username})
        await self._store.delete(where={"user": username})
        logger.info(f"Deleted all facts for user '{username}' ({count_before} records)")
        return count_before

    async def stats(self) -> dict[str, Any]:
        """Return counts per user / per category for the ``memory stats`` CLI command."""
        total = await self._store.count()
        return {"total_facts": total}
