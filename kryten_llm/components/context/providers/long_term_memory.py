"""Long-term memory context provider backed by a vector store.

Phase 7d: REQ-010 through REQ-016, GUD-001, GUD-002.

The provider is opt-in (``enabled: false`` by default, CON-002).
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from kryten_llm.components.context.base import ContextFragment, ContextRequest, register_provider
from kryten_llm.components.memory.embedder import Embedder, build_embedder
from kryten_llm.components.memory.extractor import EXTRACTOR_REGISTRY, ExtractedFact, Fact
from kryten_llm.components.memory.heuristic_extractor import (
    HeuristicFactExtractor,
    is_candidate,
    stable_fact_id,
)

# Importing the LLM extractor here registers it in EXTRACTOR_REGISTRY (spec §4.3)
# and is light-weight (no heavy deps until a manager is built).
from kryten_llm.components.memory.llm_extractor import LLMFactExtractor
from kryten_llm.components.memory.moderation_gate import ModerationGate
from kryten_llm.components.memory.safety import is_safe_message
from kryten_llm.components.memory.vector_store import VectorStore, build_vector_store

if TYPE_CHECKING:
    from kryten_llm.models.config import ExtractorConfig, LLMConfig

logger = logging.getLogger(__name__)


@dataclass
class RetrievalScope:
    """A single retrieval request within ``provide()`` (Sprint 8, Sortie 0).

    Each associative-memory feature (speaker, topical, room, ambient) is a
    scope: a store filter plus a query-vector source, optionally passed through
    the shadow-mute gate and rendered as one named fragment.
    """

    where: dict[str, Any] | None
    query_source: Literal["message", "username"]
    exclude_silenced: bool
    fragment_name: str
    priority: int


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
        observe_exclude_users: list[str] | None = None,
        extractor_cfg: "ExtractorConfig | None" = None,
        cross_user_enabled: bool = False,
        moderation_gate: ModerationGate | None = None,
        gate_fail_closed: bool = True,
        topical_cfg: dict[str, Any] | None = None,
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
        self._observe_exclude: set[str] = {u.lower() for u in (observe_exclude_users or [])}

        # Phase 8 (Sortie 0/1): cross-user associative retrieval + shadow-mute gate.
        self._cross_user_enabled = cross_user_enabled
        self._mod_gate = moderation_gate
        self._gate_fail_closed = gate_fail_closed
        tcfg = topical_cfg or {}
        self._topical_enabled = bool(tcfg.get("enabled", False))
        self._topical_fire_on: set[str] = {
            str(t) for t in tcfg.get("fire_on", ["auto_participation"])
        }
        self._topical_top_k = int(tcfg.get("top_k", 4))
        self._topical_min_similarity = float(tcfg.get("min_similarity", 0.30))
        self._topical_exclude_speaker = bool(tcfg.get("exclude_speaker", True))
        self._topical_priority = int(tcfg.get("priority", 38))

        # Phase 7f: LLM-driven extraction + scoring state.
        self._ext_cfg = extractor_cfg
        self._llm_mode = extractor_cfg is not None and extractor_cfg.type == "llm"
        if self._llm_mode and extractor_cfg is not None:
            lookback = extractor_cfg.attribution.lookback_messages
            batch = extractor_cfg.cadence.batch_max_size
            self._recent: deque[dict[str, Any]] = deque(maxlen=max(lookback, batch * 2, batch))
        else:
            self._recent = deque(maxlen=1)
        self._batches: dict[str, list[dict[str, Any]]] = {}
        self._idle_tasks: dict[str, asyncio.Task[None]] = {}
        self._inflight: dict[str, int] = {}
        # Per-user lock serialising the read-modify-write in `_persist` so the
        # importance counter and dedup decision stay consistent under the
        # concurrent batches allowed by `max_inflight_batches_per_user`.
        self._persist_locks: dict[str, asyncio.Lock] = {}

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
        # Validate + build the extractor first so a bad config fails fast, before
        # any (potentially heavy) embedder/store construction.
        ext_cfg = pcfg.get("extractor", {"type": "heuristic"})
        ext_type = ext_cfg.get("type", "heuristic")
        write_cfg = pcfg.get("write", {})
        extractor_cfg = None
        if ext_type not in EXTRACTOR_REGISTRY:
            raise ValueError(
                f"Unknown extractor type '{ext_type}'. Known: {sorted(EXTRACTOR_REGISTRY)}"
            )
        if ext_type == "heuristic":
            extractor = HeuristicFactExtractor(min_score=write_cfg.get("min_message_score", 25.0))
        elif ext_type == "llm":
            extractor, extractor_cfg = cls._build_llm_extractor(
                ext_cfg, templates_dir=config.templates.dir
            )
        else:  # pragma: no cover - registered types are constructed above
            raise ValueError(f"Extractor type '{ext_type}' is registered but not constructable")

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

        retrieval_cfg = pcfg.get("retrieval", {})

        # Phase 8 (Sortie 0): cross-user retrieval + shadow-mute gate wiring.
        deps = deps or {}
        cross_cfg = pcfg.get("cross_user", {})
        cross_enabled = bool(cross_cfg.get("enabled", False))
        gate: ModerationGate | None = None
        gate_cfg = pcfg.get("moderation_gate", {})
        gate_fail_closed = bool(gate_cfg.get("fail_closed", True))
        if cross_enabled and gate_cfg.get("enabled", True):
            client = deps.get("client")
            domain = channel = None
            if getattr(config, "channels", None):
                ch0 = config.channels[0]
                domain = getattr(ch0, "domain", None)
                channel = getattr(ch0, "channel", None)
            if client is not None and domain and channel:
                gate = ModerationGate(
                    client,
                    domain,
                    channel,
                    silence_actions=frozenset(
                        str(a).lower()
                        for a in gate_cfg.get("silence_actions", ["ban", "smute", "mute"])
                    ),
                    cache_ttl_s=float(gate_cfg.get("cache_ttl_s", 10.0)),
                    request_timeout_s=float(gate_cfg.get("request_timeout_s", 2.0)),
                )
            else:
                logger.warning(
                    "long_term_memory: cross_user enabled but no NATS client / channel "
                    "identity available; cross-user retrieval disabled."
                )
                cross_enabled = False

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
            observe_exclude_users=write_cfg.get("observe_exclude_users", []),
            extractor_cfg=extractor_cfg,
            cross_user_enabled=cross_enabled,
            moderation_gate=gate,
            gate_fail_closed=gate_fail_closed,
            topical_cfg=pcfg.get("topical", {}),
        )

    @staticmethod
    def _build_llm_extractor(
        ext_cfg: dict[str, Any],
        templates_dir: str | None = None,
    ) -> tuple[Any, "ExtractorConfig"]:
        """Build the dedicated extractor LLM connection (Phase 7f, REQ-001/002).

        The extractor's providers live under ``extractor.llm`` and are loaded
        into a **separate** :class:`LLMManager`; there is no reference to the
        message-generation ``llm_providers`` anywhere in this path.
        """
        from kryten_llm.components.llm_manager import LLMManager
        from kryten_llm.models.config import ExtractorConfig

        # Ensure each provider dict carries its key as ``name`` before validation.
        raw = dict(ext_cfg)
        llm_block = raw.get("llm")
        if not isinstance(llm_block, dict) or not llm_block.get("providers"):
            raise ValueError(
                "LLM extractor requires 'extractor.llm.providers' (REQ-001); "
                "the extractor connection must never fall back to llm_providers (REQ-002)."
            )
        llm_block = dict(llm_block)
        providers_in = dict(llm_block.get("providers", {}))
        for pname, pval in providers_in.items():
            if isinstance(pval, dict) and "name" not in pval:
                pval = dict(pval)
                pval["name"] = pname
                providers_in[pname] = pval
        llm_block["providers"] = providers_in
        raw["llm"] = llm_block

        extractor_cfg = ExtractorConfig.model_validate(raw)
        assert extractor_cfg.llm is not None  # guaranteed by the guard above

        manager = LLMManager.for_extractor(
            providers=extractor_cfg.llm.providers,
            provider_priority=extractor_cfg.llm.provider_priority,
            retry_strategy=extractor_cfg.llm.retry_strategy,
        )
        extractor = LLMFactExtractor(manager, extractor_cfg, logger, templates_dir=templates_dir)
        logger.info(
            "LLM fact extractor initialised with dedicated connection "
            f"({len(extractor_cfg.llm.providers)} provider(s), "
            f"mode={extractor_cfg.structured_output.mode})"
        )
        return extractor, extractor_cfg

    # ------------------------------------------------------------------
    # ContextProvider interface
    # ------------------------------------------------------------------

    async def observe(self, username: str, message: str) -> None:
        """Extract + store facts asynchronously (WRITE path, REQ-011).

        Fire-and-forget wrapper — errors are logged but never propagated. In
        LLM mode this feeds the per-user extraction batcher (REQ-020/021);
        otherwise it uses the Phase 7 per-message heuristic path.
        """
        if username.lower() in self._observe_exclude:
            return
        if self._llm_mode:
            try:
                self._observe_llm(username, message)
            except Exception as exc:  # never raise into the pipeline
                logger.warning(f"LongTermMemoryProvider._observe_llm() failed: {exc}")
            return
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
            logger.warning(f"LongTermMemoryProvider.provide() failed: {exc}", exc_info=True)
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
        """Full read path: speaker recall + (optional) cross-user topical recall."""
        speaker_frags, speaker_ids = await self._run_speaker_scope(req)
        fragments: list[ContextFragment] = list(speaker_frags)

        if self._should_run_topical(req):
            fragments.extend(await self._run_topical_scope(req, exclude_ids=speaker_ids))

        return fragments

    async def _run_speaker_scope(
        self, req: ContextRequest
    ) -> tuple[list[ContextFragment], set[str]]:
        """Speaker-scoped recall — the original Phase 7 behaviour (``user_memory``)."""
        query_text = req.message if self._relate_to_message else req.username

        # Embed the query
        vectors = await self._embedder.embed([query_text])
        if not vectors:
            return [], set()

        query_vec = vectors[0]

        # In LLM mode, over-fetch candidates so the importance/recency boost can
        # surface salient facts that fall just outside the pure-similarity top-K
        # (REQ-037). Pure-similarity mode fetches exactly top_k.
        fetch_k = self._top_k
        if self._llm_mode and self._ext_cfg is not None:
            fetch_k = min(self._top_k * 3, self._top_k + 20)

        # Query for this user's facts
        results = await self._store.query(
            vector=query_vec,
            k=fetch_k,
            where={"user": req.username},
        )

        if not results:
            return [], set()

        # Filter by minimum similarity (cosine distance — 0 = identical, 2 = opposite).
        # cosine_distance = 1 − cosine_similarity, so max_distance = 1 − min_similarity.
        max_distance = 1.0 - self._min_similarity
        filtered = [r for r in results if r.get("distance", 1.0) <= max_distance]

        if not filtered:
            return [], set()

        # REQ-037: in LLM mode, re-rank by similarity + importance + recency.
        if self._llm_mode and self._ext_cfg is not None:
            filtered = self._rank_with_boost(filtered)[: self._top_k]

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
        surfaced_ids = {str(r.get("id")) for r in filtered if r.get("id") is not None}

        return [
            ContextFragment(
                name="user_memory",
                priority=self._priority,
                text=text,
                est_chars=len(text),
            )
        ], surfaced_ids

    def _should_run_topical(self, req: ContextRequest) -> bool:
        """Topical recall fires only when enabled and the trigger type qualifies."""
        if not (self._cross_user_enabled and self._topical_enabled):
            return False
        trigger_type = str((req.trigger or {}).get("type", ""))
        return trigger_type in self._topical_fire_on

    async def _run_topical_scope(
        self, req: ContextRequest, exclude_ids: set[str]
    ) -> list[ContextFragment]:
        """Cross-user, topic-scoped recall (``topical_memory``) — Sprint 8, Sortie 1.

        Retrieves facts similar to the current message regardless of author,
        excludes currently-silenced users (shadow-mute gate), and attributes each
        line to its source user.
        """
        vectors = await self._embedder.embed([req.message])
        if not vectors:
            return []
        query_vec = vectors[0]

        where: dict[str, Any] | None = (
            {"user": {"$ne": req.username}} if self._topical_exclude_speaker else None
        )
        # Over-fetch: the gate + speaker de-dup can drop rows before the top-K trim.
        fetch_k = min(self._topical_top_k * 3, self._topical_top_k + 20)
        results = await self._store.query(vector=query_vec, k=fetch_k, where=where)
        if not results:
            return []

        max_distance = 1.0 - self._topical_min_similarity
        filtered = [
            r
            for r in results
            if r.get("distance", 1.0) <= max_distance and str(r.get("id")) not in exclude_ids
        ]
        if not filtered:
            return []

        gated = await self._filter_silenced(filtered)
        if gated is None:  # gate failure + fail_closed → withhold cross-user recall
            return []
        gated = gated[: self._topical_top_k]
        if not gated:
            return []

        lines = []
        for r in gated:
            meta = r.get("metadata", {})
            user = meta.get("user", "?")
            doc = r.get("document", "")
            if doc:
                lines.append(f"• [{user}] {doc}")
        if not lines:
            return []

        text = "Relevant things people have said before:\n" + "\n".join(lines)
        return [
            ContextFragment(
                name="topical_memory",
                priority=self._topical_priority,
                text=text,
                est_chars=len(text),
            )
        ]

    async def _filter_silenced(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        """Drop rows whose author is currently silenced (REQ-042/043).

        Returns ``None`` when the gate is unavailable and ``fail_closed`` is set,
        signalling the caller to withhold the cross-user fragment entirely.
        """
        if self._mod_gate is None:
            # Gate explicitly disabled by config → no exclusion.
            return rows
        silenced = await self._mod_gate.silenced_users()
        if silenced is None:
            return None if self._gate_fail_closed else rows
        return [r for r in rows if r.get("metadata", {}).get("user", "").lower() not in silenced]

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
        if logger.isEnabledFor(logging.DEBUG):
            for fact, meta_item in zip(facts, metas):
                logger.debug(
                    f"  upserted [{meta_item['user']}] {meta_item['category']}: "
                    f"'{fact.summary[:80]}' (score={fact.score:.1f})"
                )
        logger.debug(f"Upserted {len(ids)} fact(s)")

    # ------------------------------------------------------------------
    # Phase 7f: LLM extraction cadence (REQ-020 to REQ-023, CON-004)
    # ------------------------------------------------------------------

    def _observe_llm(self, username: str, message: str) -> None:
        """Feed the per-user extraction batcher (synchronous, non-blocking)."""
        assert self._ext_cfg is not None
        text = message.strip()
        if not text:
            return
        now = datetime.now(timezone.utc).isoformat()

        # CON-001: the safety gate is unconditional. PII must never reach the
        # extractor LLM — not even as look-back context — so unsafe messages are
        # dropped *before* entering the rolling window.
        if not is_safe_message(text):
            return

        # Rolling look-back window across all authors (context for attribution).
        self._recent.append({"username": username, "message": text, "time": now})

        # Heuristic candidate pre-gate: this gates *batch eligibility* only
        # (REQ-020). Safe-but-non-candidate messages still provide context above.
        if self._ext_cfg.heuristic_pregate and not is_candidate(text):
            return

        buf = self._batches.setdefault(username, [])
        buf.append({"username": username, "message": text, "time": now})

        # CON-004: bound the per-user buffer so a slow/hung extractor (deferred
        # by the in-flight cap) cannot grow it without limit — keep the newest.
        max_buf = (
            self._ext_cfg.cadence.batch_max_size
            * self._ext_cfg.cadence.max_inflight_batches_per_user
        )
        if len(buf) > max_buf:
            del buf[: len(buf) - max_buf]

        if len(buf) >= self._ext_cfg.cadence.batch_max_size:
            self._cancel_idle(username)
            self._flush_user(username)
        else:
            self._schedule_idle(username)

    def _schedule_idle(self, username: str) -> None:
        """(Re)start the idle-flush timer for *username* (REQ-021)."""
        assert self._ext_cfg is not None
        self._cancel_idle(username)
        idle = self._ext_cfg.cadence.batch_idle_seconds
        self._idle_tasks[username] = asyncio.ensure_future(self._idle_flush(username, idle))

    def _cancel_idle(self, username: str) -> None:
        task = self._idle_tasks.pop(username, None)
        if task is not None and not task.done():
            task.cancel()

    async def _idle_flush(self, username: str, idle: float) -> None:
        try:
            await asyncio.sleep(idle)
        except asyncio.CancelledError:
            return
        self._flush_user(username)

    def _flush_user(self, username: str) -> None:
        """Snapshot the batch + look-back window and launch extraction off-path."""
        assert self._ext_cfg is not None
        buf = self._batches.get(username)
        if not buf:
            return

        cap = self._ext_cfg.cadence.max_inflight_batches_per_user
        if self._inflight.get(username, 0) >= cap:
            # CON-004: bound in-flight batches; defer until a slot frees.
            logger.debug(f"LTM: in-flight batch cap reached for '{username}'; deferring flush")
            self._schedule_idle(username)
            return

        # REQ-011/023: the look-back window is exactly `lookback_messages` of the
        # most recent (safe) context, which may span more than one batch.
        lookback = self._ext_cfg.attribution.lookback_messages
        window = list(self._recent)[-lookback:]
        self._batches[username] = []
        self._inflight[username] = self._inflight.get(username, 0) + 1
        asyncio.ensure_future(self._run_batch(username, window))

    async def _run_batch(self, username: str, window: list[dict[str, Any]]) -> None:
        """Off-critical-path extraction + persistence for one batch (REQ-022)."""
        try:
            facts = await self._extractor.extract(window, username)
            for ef in facts:
                await self._persist(ef)
        except Exception as exc:
            logger.warning(f"LTM._run_batch failed for '{username}': {exc}", exc_info=True)
        finally:
            self._inflight[username] = max(0, self._inflight.get(username, 1) - 1)

    # ------------------------------------------------------------------
    # Phase 7f: scoring & persistence (REQ-030 to REQ-038)
    # ------------------------------------------------------------------

    @staticmethod
    def _similarity(distance: float) -> float:
        """Map a store distance to a [0,1] similarity (consistent with retrieval)."""
        return max(0.0, min(1.0, 1.0 - distance))

    def _persist_lock(self, user: str) -> asyncio.Lock:
        """Return (creating if needed) the per-user persistence lock."""
        lock = self._persist_locks.get(user)
        if lock is None:
            lock = asyncio.Lock()
            self._persist_locks[user] = lock
        return lock

    async def _persist(self, ef: ExtractedFact) -> None:
        """Score + persist one extracted fact (REQ-030 to REQ-038)."""
        assert self._ext_cfg is not None
        cfg = self._ext_cfg

        # Confidence gate (REQ-030).
        if ef.confidence < cfg.attribution.min_confidence:
            return
        # Safety re-check on the summary before it enters the durable store (CON-003).
        if not is_safe_message(ef.summary):
            return

        # Embedding is pure and shares no state — do it outside the lock.
        vectors = await self._embedder.embed([ef.summary])
        if not vectors:
            return
        vec = vectors[0]

        # Serialise the query→decide→write critical section per user so the
        # dedup decision and importance counter stay consistent when concurrent
        # batches run for the same user.
        async with self._persist_lock(ef.target_user):
            neighbours = await self._store.query(vector=vec, k=1, where={"user": ef.target_user})
            top = neighbours[0] if neighbours else None
            similarity = self._similarity(top.get("distance", 1.0)) if top else 0.0
            novelty = 1.0 - similarity  # REQ-032: mechanical, authoritative.
            now = datetime.now(timezone.utc).isoformat()

            # Dedup / merge — same fact (REQ-033).
            if top is not None and novelty <= cfg.scoring.dedup_novelty_max:
                logger.debug(
                    f"LTM [{ef.target_user}] DEDUP '{top['document'][:80]}' "
                    f"(sim={similarity:.3f}) -> bumping importance"
                )
                await self._bump_importance(top["id"], evidence=ef.evidence, last_seen=now)
                return

            # Related-mention salience — distinct but closely related (REQ-034).
            if top is not None and novelty <= cfg.scoring.importance_increment_below:
                logger.debug(
                    f"LTM [{ef.target_user}] RELATED '{top['document'][:80]}' "
                    f"(sim={similarity:.3f}) -> bump importance + insert new"
                )
                await self._bump_importance(top["id"], last_seen=now)

            # Novel (or related-but-distinct) fact — insert new record (REQ-035/038).
            await self._enforce_cap(ef.target_user)
            fact_id = stable_fact_id(ef.target_user, ef.summary)
            meta: dict[str, Any] = {
                "user": ef.target_user,
                "category": ef.category,
                "source": "live",
                "confidence": float(ef.confidence),
                "sentiment": float(ef.sentiment),
                "novelty_at_write": float(novelty),
                "importance": 1,
                "created_at": now,
                "last_seen": now,
                "embedder_id": self._embedder.id,
                "evidence": str(ef.evidence.get("message", ""))[:200],
            }
            await self._store.upsert(
                ids=[fact_id], vectors=[vec], metadatas=[meta], documents=[ef.summary]
            )
            logger.debug(
                f"LTM [{ef.target_user}] NEW [{ef.category}]: '{ef.summary[:80]}' "
                f"(conf={ef.confidence:.2f}, novelty={novelty:.3f})"
            )

    async def _bump_importance(
        self,
        fact_id: str,
        evidence: dict[str, Any] | None = None,
        last_seen: str | None = None,
    ) -> None:
        """Increment the importance counter on an existing fact (REQ-033/034/036)."""
        assert self._ext_cfg is not None
        get_meta = getattr(self._store, "get_metadata", None)
        update_meta = getattr(self._store, "update_metadata", None)
        if get_meta is None or update_meta is None:
            logger.debug("LTM: store does not support metadata updates; importance bump skipped")
            return
        try:
            metas = await get_meta(ids=[fact_id])
            if not metas:
                return
            meta = dict(metas[0] or {})
            current = int(meta.get("importance", 1))
            new_importance = min(current + 1, self._ext_cfg.scoring.importance_cap)
            meta["importance"] = new_importance
            if last_seen:
                meta["last_seen"] = last_seen
            if evidence:
                meta["evidence"] = str(evidence.get("message", ""))[:200]
            await update_meta(ids=[fact_id], metadatas=[meta])
            logger.debug(
                f"  importance bump: {current} -> {new_importance}"
                + (f" (evidence: '{str(evidence.get('message', ''))[:60]}')" if evidence else "")
            )
        except Exception as exc:
            logger.warning(f"LTM._bump_importance failed for '{fact_id}': {exc}")

    def _rank_with_boost(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Blend importance + recency into similarity for ranking (REQ-037)."""
        assert self._ext_cfg is not None
        boost = self._ext_cfg.retrieval_boost
        cap = self._ext_cfg.scoring.importance_cap
        log_cap = math.log(1.0 + cap)
        now = datetime.now(timezone.utc)

        def _score(r: dict[str, Any]) -> float:
            meta = r.get("metadata", {}) or {}
            similarity = self._similarity(r.get("distance", 1.0))
            importance = int(meta.get("importance", 1))
            norm_imp = math.log(1.0 + importance) / log_cap if log_cap > 0 else 0.0
            recency = self._recency_factor(meta.get("last_seen", ""), now)
            return similarity + boost.importance_weight * norm_imp + boost.recency_weight * recency

        return sorted(results, key=_score, reverse=True)

    @staticmethod
    def _recency_factor(last_seen: str, now: datetime) -> float:
        """Return a [0,1] recency factor from an ISO timestamp (newer = higher)."""
        if not last_seen:
            return 0.0
        try:
            ts = datetime.fromisoformat(last_seen)
        except ValueError:
            return 0.0
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
        return 1.0 / (1.0 + age_days)

    async def _enforce_cap(self, username: str) -> None:
        """Evict lowest-quality facts if the per-user cap is exceeded (REQ-014).

        Eviction priority (ascending — lowest value evicted first):
        1. ``quality``    mode-normalised 0–100 score:
                          • heuristic mode: ``score`` field (25–100)
                          • LLM mode:       ``confidence`` × 100 (0–100)
                          • mixed collection: both are on the same scale so
                            heuristic and LLM facts compete fairly.
        2. ``importance`` (engagement counter, 1–N;  absent in either mode → 1)
        3. ``created_at`` (ISO timestamp tiebreaker — oldest among equal-quality
                           records is evicted first)

        Age is intentionally only a tiebreaker: an old high-quality fact is more
        valuable than a recent low-quality one.

        NOTE: using ``score`` and ``confidence`` as separate dimensions is
        intentionally avoided — doing so causes heuristic facts (score≥25) to
        always outlast LLM facts (score absent → 0), making bulk-imported
        heuristic facts permanently block live LLM learning once the cap is hit.
        """
        try:
            count = await self._store.count(where={"user": username})
            if count <= self._per_user_fact_cap:
                return

            excess = count - self._per_user_fact_cap

            # Backend-agnostic eviction: the store must expose ``get_all`` (fetch
            # all records for a filter, with metadata + documents) and
            # ``delete_ids`` (delete by explicit id). Both Chroma and pgvector
            # backends provide these.
            get_all = getattr(self._store, "get_all", None)
            delete_ids = getattr(self._store, "delete_ids", None)
            if get_all is None or delete_ids is None:
                logger.debug(
                    f"User '{username}' has {count} facts (cap={self._per_user_fact_cap}); "
                    "eviction skipped (store does not support get_all/delete_ids)"
                )
                return

            records = await get_all(where={"user": username})

            def _eviction_key(meta: dict) -> tuple:
                # Lower value → evicted first.
                # Normalise to a single 0-100 quality scale so heuristic
                # and LLM facts compete fairly in mixed collections:
                #   heuristic: "score" field stores 25-100 directly.
                #   LLM:       no "score" → use confidence × 100 (0-100).
                # Using score and confidence as *separate* dimensions would
                # cause heuristic facts (score≥25) to always beat LLM facts
                # (score absent → 0.0), blocking live learning after a bulk
                # import once the cap is hit.
                raw_score = meta.get("score")
                confidence = float(meta.get("confidence", 1.0))
                quality = float(raw_score) if raw_score is not None else confidence * 100.0
                return (
                    quality,  # 0-100, mode-normalised
                    int(meta.get("importance", 1)),  # engagement counter (1-N)
                    meta.get("created_at", ""),  # age tiebreaker (oldest first)
                )

            records.sort(key=lambda r: _eviction_key(r.get("metadata") or {}))
            to_evict = records[:excess]
            ids_to_evict = [r["id"] for r in to_evict]
            if ids_to_evict:
                await delete_ids(ids_to_evict)
                logger.info(
                    f"Evicted {len(ids_to_evict)} lowest-quality fact(s) for '{username}' "
                    f"(cap={self._per_user_fact_cap})"
                )
                if logger.isEnabledFor(logging.DEBUG):
                    for r in to_evict:
                        emeta = r.get("metadata") or {}
                        edoc = r.get("document") or ""
                        logger.debug(
                            f"  evicted [{emeta.get('category', '?')}]: "
                            f"'{edoc[:80]}' "
                            f"(score={emeta.get('score', 0.0)}, "
                            f"importance={emeta.get('importance', 1)}, "
                            f"conf={float(emeta.get('confidence', 1.0)):.2f}, "
                            f"age={str(emeta.get('created_at', '?'))[:10]})"
                        )
        except Exception as exc:
            logger.warning(f"_enforce_cap failed for '{username}': {exc}")

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
