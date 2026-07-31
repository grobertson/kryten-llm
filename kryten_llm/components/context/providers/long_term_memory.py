"""Long-term memory context provider backed by a vector store.

Phase 7d: REQ-010 through REQ-016, GUD-001, GUD-002.

The provider is opt-in (``enabled: false`` by default, CON-002).
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
from kryten_llm.components.memory.opposition import opposition_score
from kryten_llm.components.memory.safety import is_safe_message
from kryten_llm.components.memory.vector_store import VectorStore, build_vector_store

if TYPE_CHECKING:
    from kryten_llm.models.config import ExtractorConfig, LLMConfig

logger = logging.getLogger(__name__)

# Sortie 6: shallow negation/polarity markers for contradiction detection (v1).
_NEGATION_RE = re.compile(
    r"\b(not|no|never|n't|hate|hates|dislike|dislikes|stopped|quit|"
    r"used to|no longer|don't|doesn't|didn't|isn't|aren't)\b",
    re.IGNORECASE,
)


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
        context_manager: Any = None,
        query_mode: str = "message",
        window_size: int = 6,
        window_recency_weight: float = 0.0,
        window_pooling: str = "recency",
        window_min_salience: float = 0.0,
        category_routing_cfg: dict[str, Any] | None = None,
        bot_name: str = "",
        room_cfg: dict[str, Any] | None = None,
        novelty_cfg: dict[str, Any] | None = None,
        callback_cfg: dict[str, Any] | None = None,
        ambient_cfg: dict[str, Any] | None = None,
        health_monitor: Any = None,
        trace_cfg: dict[str, Any] | None = None,
        client: Any = None,
        domain: str = "",
        channel: str = "",
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
        self._topical_boost = bool(tcfg.get("boost_ranking", True))

        # Sortie 3: windowed query vector (pool the recent conversation).
        self._context_manager = context_manager
        self._query_mode = query_mode
        self._window_size = window_size
        self._window_recency_weight = window_recency_weight
        # Sprint 9 (Sortie 4): pooling strategy for the window vector.
        self._window_pooling = window_pooling
        self._window_min_salience = window_min_salience

        # Sortie 4: category-routed presentation of speaker facts.
        crcfg = category_routing_cfg or {}
        self._cat_routing_enabled = bool(crcfg.get("enabled", False))
        self._cat_mode = str(crcfg.get("mode", "sections"))
        self._cat_order = [str(c) for c in crcfg.get("order", [])]
        self._cat_labels = {str(k): str(v) for k, v in dict(crcfg.get("labels", {})).items()}
        self._cat_top_k: dict[str, int] = {
            str(k): int(v) for k, v in dict(crcfg.get("per_category_top_k", {"default": 2})).items()
        }
        self._cat_priority: dict[str, int] = {
            str(k): int(v) for k, v in dict(crcfg.get("priority", {})).items()
        }

        # Sortie 2: room awareness (facts for other currently-active participants).
        self._bot_name = bot_name.lower()
        rmcfg = room_cfg or {}
        self._room_enabled = bool(rmcfg.get("enabled", False))
        self._room_fire_on = {str(t) for t in rmcfg.get("fire_on", ["auto_participation"])}
        self._room_window_messages = int(rmcfg.get("window_messages", 20))
        self._room_max_users = int(rmcfg.get("max_users", 4))
        self._room_facts_per_user = int(rmcfg.get("facts_per_user", 1))
        self._room_min_similarity = float(rmcfg.get("min_similarity", 0.25))
        self._room_priority = int(rmcfg.get("priority", 30))
        self._room_boost = bool(rmcfg.get("boost_ranking", True))
        self._room_presence_source = str(rmcfg.get("presence_source", "recent_activity"))
        self._room_presence_ttl = float(rmcfg.get("presence_cache_ttl_s", 10.0))

        # Sortie 6: read-only novelty / contradiction signal.
        nvcfg = novelty_cfg or {}
        self._novelty_enabled = bool(nvcfg.get("enabled", False))
        self._novelty_max_similarity = float(nvcfg.get("novelty_max_similarity", 0.35))
        self._contradiction_min_similarity = float(nvcfg.get("contradiction_min_similarity", 0.80))
        self._novelty_priority = int(nvcfg.get("priority", 28))
        self._novel_label = str(nvcfg.get("novel_label", "This seems new for {user}"))
        self._contradiction_label = str(
            nvcfg.get("contradiction_label", "This may update what you knew")
        )
        # Sprint 9 (Sortie 3): embedding-based contradiction detection.
        self._contradiction_method = str(nvcfg.get("contradiction_method", "heuristic"))
        self._opposition_threshold = float(nvcfg.get("opposition_threshold", 0.05))
        self._min_facts_for_contradiction = int(nvcfg.get("min_facts_for_contradiction", 3))

        # Sortie 5: long-tail callback resurfacing.
        cbcfg = callback_cfg or {}
        self._callback_enabled = bool(cbcfg.get("enabled", False))
        self._callback_probability = float(cbcfg.get("probability", 0.15))
        self._callback_min_importance = int(cbcfg.get("min_importance", 3))
        self._callback_min_age_days = float(cbcfg.get("min_age_days", 14))
        self._callback_max_sim = float(cbcfg.get("max_similarity_to_topic", 0.6))
        self._callback_cooldown_turns = int(cbcfg.get("cooldown_turns", 20))
        self._callback_scope = str(cbcfg.get("scope", "speaker"))
        self._callback_label = str(cbcfg.get("label", "You also remember"))
        self._callback_priority = int(cbcfg.get("priority", 32))
        self._callback_cooldown: dict[str, int] = {}

        # Sortie 7: ambient mood vector (EWMA of recent chatter).
        amcfg = ambient_cfg or {}
        self._ambient_enabled = bool(amcfg.get("enabled", False))
        self._ambient_alpha = float(amcfg.get("alpha", 0.15))
        self._ambient_warmup = int(amcfg.get("warmup_messages", 15))
        self._ambient_top_k = int(amcfg.get("top_k", 3))
        self._ambient_min_similarity = float(amcfg.get("min_similarity", 0.20))
        self._ambient_fire_on = {str(t) for t in amcfg.get("fire_on", ["auto_participation"])}
        self._ambient_priority = int(amcfg.get("priority", 26))
        self._ambient_boost = bool(amcfg.get("boost_ranking", True))
        # Sprint 9 (Sortie 4): pooling strategy for the mood vector.
        self._ambient_pooling = str(amcfg.get("pooling_strategy", "mean"))
        self._ambient_min_salience = float(amcfg.get("min_salience", 0.0))
        self._mood: list[float] | None = None
        self._mood_count = 0

        # Sprint 9 (Sortie 5): observability.
        self._monitor = health_monitor
        trcfg = trace_cfg or {}
        self._trace_enabled = bool(trcfg.get("enabled", False))
        self._trace_include_content = bool(trcfg.get("include_content", False))

        # Sprint 9 (Sortie 2): authoritative presence from the robot userlist.
        self._client = client
        self._domain = domain
        self._channel = channel
        self._userlist_cache: list[str] | None = None
        self._userlist_cache_at = 0.0

        # Sprint 11: Engagement signals from the last provide() (REQ-220).
        # Read by the trigger engine for the pre-check / eagerness gate (stale-ok).
        from kryten_llm.components.memory.engagement import EngagementSignals

        self.last_engagement_signals: EngagementSignals | None = None

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

        # Sprint 13: Fact Confidence & Verification (REQ-280–309).
        # These are read from the provider config; all default to no-behaviour-change.
        # Confidence parameters live in pcfg["confidence"] and are wired via from_config.
        self._confidence_corroboration_step: float = 0.05  # Sortie 2: set non-zero to enable
        self._confidence_contradiction_decay: float = 0.1  # Sortie 3: set non-zero to enable
        self._confidence_floor: float = 0.1  # Sortie 3: floor guard
        self._confidence_hedge_enabled: bool = False  # Sortie 5: hedged template
        self._confidence_hedge_above: float = 0.7  # Sortie 5: assertive threshold
        # Sprint 18, Sortie 2 (REQ-375–379): importance-gated contradiction decay.
        self._confidence_importance_gated_decay: bool = False

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
        client = deps.get("client")
        domain = channel = None
        if getattr(config, "channels", None):
            ch0 = config.channels[0]
            domain = getattr(ch0, "domain", None)
            channel = getattr(ch0, "channel", None)
        cross_cfg = pcfg.get("cross_user", {})
        cross_enabled = bool(cross_cfg.get("enabled", False))
        gate: ModerationGate | None = None
        gate_cfg = pcfg.get("moderation_gate", {})
        gate_fail_closed = bool(gate_cfg.get("fail_closed", True))
        if cross_enabled and gate_cfg.get("enabled", True):
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

        provider = cls(
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
            context_manager=deps.get("context_manager"),
            query_mode=retrieval_cfg.get("query_mode", "message"),
            window_size=int(retrieval_cfg.get("window_size", 6)),
            window_recency_weight=float(retrieval_cfg.get("window_recency_weight", 0.0)),
            window_pooling=str(retrieval_cfg.get("pooling_strategy", "recency")),
            window_min_salience=float(retrieval_cfg.get("min_salience", 0.0)),
            category_routing_cfg=pcfg.get("category_routing", {}),
            bot_name=(getattr(getattr(config, "personality", None), "character_name", "") or ""),
            room_cfg=pcfg.get("room_awareness", {}),
            novelty_cfg=pcfg.get("novelty", {}),
            callback_cfg=pcfg.get("callback", {}),
            ambient_cfg=pcfg.get("ambient", {}),
            health_monitor=deps.get("health_monitor"),
            trace_cfg=pcfg.get("trace", {}),
            client=client,
            domain=domain or "",
            channel=channel or "",
        )

        # Sprint 13: wire confidence parameters from the provider config (REQ-280–309).
        conf_cfg = pcfg.get("confidence", {})
        provider._confidence_corroboration_step = float(conf_cfg.get("corroboration_step", 0.05))
        provider._confidence_contradiction_decay = float(conf_cfg.get("contradiction_decay", 0.1))
        provider._confidence_floor = float(conf_cfg.get("confidence_floor", 0.1))
        provider._confidence_hedge_enabled = bool(conf_cfg.get("hedge_enabled", False))
        provider._confidence_hedge_above = float(conf_cfg.get("hedge_above", 0.7))
        # Sprint 18, Sortie 2 (REQ-375): importance-gated contradiction decay.
        provider._confidence_importance_gated_decay = bool(conf_cfg.get("importance_gated_decay", False))
        return provider

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
        if self._ambient_enabled:
            try:
                await self._update_mood(message)
            except Exception as exc:  # never raise into the pipeline
                logger.warning(f"LTM mood update failed: {exc}")
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
        Records read-path latency and fragment-emission metrics (Sprint 9, S5).
        """
        start = time.perf_counter()
        fragments: list[ContextFragment] = []
        try:
            fragments = await asyncio.wait_for(
                self._provide_impl(req),
                timeout=self._read_timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"LongTermMemoryProvider.provide() timed out after "
                f"{self._read_timeout_s * 1000:.0f} ms for user '{req.username}'"
            )
        except Exception as exc:
            logger.warning(f"LongTermMemoryProvider.provide() failed: {exc}", exc_info=True)
        finally:
            if self._monitor is not None:
                self._monitor.record_memory_retrieval_time(time.perf_counter() - start)

        if self._monitor is not None:
            for frag in fragments:
                self._monitor.record_memory_fragment(frag.name)
        if self._trace_enabled and fragments:
            self._emit_trace(req, fragments)
        return fragments

    def _emit_trace(self, req: ContextRequest, fragments: list[ContextFragment]) -> None:
        """Debug per-turn fragment trace (REQ-164/165). Names/sizes only unless
        ``trace.include_content`` is explicitly set."""
        parts = []
        for f in fragments:
            if self._trace_include_content:
                parts.append(f"{f.name}({f.est_chars}c): {f.text}")
            else:
                parts.append(f"{f.name}({f.est_chars}c)")
        logger.debug("LTM trace user=%s fragments=[%s]", req.username, "; ".join(parts))

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

    # ------------------------------------------------------------------
    # Query-vector construction (Sortie 3)
    # ------------------------------------------------------------------

    async def _message_query_vector(self, req: ContextRequest) -> list[float] | None:
        """Embed the current message, or a pooled mean of the recent window."""
        if self._query_mode != "window":
            vecs = await self._embedder.embed([req.message])
            return vecs[0] if vecs else None
        texts = self._recent_window_texts(req)
        if not texts:
            vecs = await self._embedder.embed([req.message])
            return vecs[0] if vecs else None
        vecs = await self._embedder.embed(texts)
        if not vecs:
            return None
        return self._pool_window(vecs, texts)

    def _pool_window(self, vecs: list[list[float]], texts: list[str]) -> list[float]:
        """Pool the window vectors by the configured strategy (Sortie 4)."""
        if self._window_pooling == "attention":
            return self._attention_pool(vecs, texts, self._window_min_salience)
        rw = self._window_recency_weight if self._window_pooling == "recency" else 0.0
        return self._pool(vecs, rw)

    def _recent_window_texts(self, req: ContextRequest) -> list[str]:
        """Return the last ``window_size`` message texts from chat history."""
        cm = self._context_manager
        history = getattr(cm, "chat_history", None)
        if not history:
            return []
        recent = list(history)[-self._window_size :]
        return [m.message for m in recent if getattr(m, "message", "")]

    @staticmethod
    def _pool(vectors: list[list[float]], recency_weight: float) -> list[float]:
        """Weighted mean of vectors (geometric recency decay; 0 = plain mean)."""
        n = len(vectors)
        if n == 1:
            return list(vectors[0])
        if recency_weight and recency_weight > 0:
            weights = [(1.0 - recency_weight) ** (n - 1 - i) for i in range(n)]
        else:
            weights = [1.0] * n
        total = sum(weights) or 1.0
        dim = len(vectors[0])
        pooled = [0.0] * dim
        for w, vec in zip(weights, vectors):
            for j in range(dim):
                pooled[j] += w * vec[j]
        return [x / total for x in pooled]

    async def _provide_impl(self, req: ContextRequest) -> list[ContextFragment]:
        """Full read path: speaker recall + (optional) cross-user topical/room recall."""
        speaker_frags, speaker_ids, speaker_signals = await self._run_speaker_scope(req)
        fragments: list[ContextFragment] = list(speaker_frags)
        surfaced: set[str] = set(speaker_ids)

        # Collect topical similarity for engagement score (Sprint 11, REQ-221).
        topical_max_sim = 0.0

        if self._should_run_topical(req):
            tfrags, tids = await self._run_topical_scope(req, exclude_ids=surfaced)
            fragments.extend(tfrags)
            surfaced |= tids
            # Cheaply extract max topical similarity from result names/content (best-effort).
            topical_max_sim = float(getattr(self, "_last_topical_max_sim", 0.0))

        if self._should_run_room(req):
            rfrags, rids = await self._run_room_scope(req, exclude_ids=surfaced)
            fragments.extend(rfrags)
            surfaced |= rids

        if self._callback_enabled:
            cfrags, cids = await self._run_callback_scope(req, exclude_ids=surfaced)
            fragments.extend(cfrags)
            surfaced |= cids

        if self._should_run_ambient(req):
            afrags, aids = await self._run_ambient_scope(req, exclude_ids=surfaced)
            fragments.extend(afrags)
            surfaced |= aids

        # Sprint 11: Build and cache engagement signals from this turn (REQ-220–224).
        self._update_engagement_signals(req, speaker_signals, topical_max_sim)

        return fragments

    def _update_engagement_signals(
        self,
        req: ContextRequest,
        speaker_signals: dict[str, float],
        topical_max_sim: float,
    ) -> None:
        """Compute and cache engagement signals after a successful provide() (REQ-220)."""
        try:
            from kryten_llm.components.memory.engagement import EngagementSignals

            # Mood cosine: cosine between the mood vector and the current message embedding.
            mood_cosine = 0.0
            if self._mood is not None and self._mood_count >= self._ambient_warmup:
                last_vec = getattr(self, "_last_message_vec", None)
                if last_vec is not None:
                    mood_cosine = max(0.0, self._cosine(self._mood, last_vec))

            self.last_engagement_signals = EngagementSignals(
                novelty=speaker_signals.get("novelty", 0.0),
                topical_max_sim=topical_max_sim,
                mood_cosine=mood_cosine,
                max_importance=speaker_signals.get("max_importance", 0.0),
                user_depth=speaker_signals.get("user_depth", 0.0),
            )
            logger.debug(
                "LTM engagement signals: novelty=%.2f topical=%.2f mood=%.2f imp=%.2f depth=%.2f",
                self.last_engagement_signals.novelty,
                self.last_engagement_signals.topical_max_sim,
                self.last_engagement_signals.mood_cosine,
                self.last_engagement_signals.max_importance,
                self.last_engagement_signals.user_depth,
            )
        except Exception as exc:
            logger.debug("LTM: could not update engagement signals: %s", exc)

    async def _run_speaker_scope(
        self, req: ContextRequest
    ) -> tuple[list[ContextFragment], set[str], dict[str, float]]:
        """Speaker-scoped recall — the original Phase 7 behaviour (``user_memory``).

        Returns a 3-tuple: (fragments, surfaced_ids, speaker_signals) where
        ``speaker_signals`` carries novelty / importance / user_depth values for
        the Sprint 11 engagement score (REQ-221).
        """
        _no_signals: dict[str, float] = {"novelty": 0.0, "max_importance": 0.0, "user_depth": 0.0}

        if self._relate_to_message:
            query_vec = await self._message_query_vector(req)
        else:
            uvecs = await self._embedder.embed([req.username])
            query_vec = uvecs[0] if uvecs else None
        if query_vec is None:
            return [], set(), _no_signals

        # Cache message vector for mood cosine computation (Sprint 11, REQ-221).
        self._last_message_vec: list[float] | None = query_vec

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

        # Sortie 6: read-only novelty / contradiction signal from the nearest fact.
        signal_frags = await self._novelty_signal(req, results)

        if not results:
            return signal_frags, set(), _no_signals

        # Sprint 11: novelty = 1 − nearest cosine similarity (REQ-221).
        nearest_dist = min(r.get("distance", 1.0) for r in results)
        novelty = max(0.0, min(1.0, nearest_dist))  # distance ≈ 1 − similarity for cosine

        # Filter by minimum similarity (cosine distance — 0 = identical, 2 = opposite).
        # cosine_distance = 1 − cosine_similarity, so max_distance = 1 − min_similarity.
        max_distance = 1.0 - self._min_similarity
        filtered = [r for r in results if r.get("distance", 1.0) <= max_distance]

        if not filtered:
            return (
                signal_frags,
                set(),
                {"novelty": novelty, "max_importance": 0.0, "user_depth": 0.0},
            )

        # REQ-037: in LLM mode, re-rank by similarity + importance + recency.
        if self._llm_mode and self._ext_cfg is not None:
            ranked = self._rank_with_boost(filtered)
        else:
            ranked = filtered

        # Sprint 11: derive importance and depth signals (REQ-221, REQ-246).
        importance_cap = (
            self._ext_cfg.scoring.importance_cap if self._ext_cfg is not None else 10000
        )
        importances = [int(r.get("metadata", {}).get("importance", 1)) for r in filtered]
        max_imp = max(importances) if importances else 1
        max_importance = min(1.0, max_imp / max(importance_cap, 1))
        # user_depth: fact_count / cap (normalised [0,1]) combined with avg_importance.
        fact_count_norm = min(1.0, len(filtered) / max(self._per_user_fact_cap, 1))
        avg_imp_norm = min(1.0, (sum(importances) / len(importances)) / max(importance_cap, 1))
        user_depth = (fact_count_norm + avg_imp_norm) / 2.0
        speaker_signals = {
            "novelty": novelty,
            "max_importance": max_importance,
            "user_depth": user_depth,
        }

        # Sortie 4: category-routed presentation (labeled sections / per-category).
        if self._cat_routing_enabled:
            frags, ids = self._format_categorized(req, ranked)
            return frags + signal_frags, ids, speaker_signals

        ranked = ranked[: self._top_k]

        # Sprint 13, Sortie 5 (REQ-300): compute avg confidence for template hedging.
        if ranked:
            avg_conf = sum(
                float(r.get("metadata", {}).get("confidence", 0.5)) for r in ranked
            ) / len(ranked)
        else:
            avg_conf = None

        # Format as compact bulleted text (GUD-002)
        lines = []
        for r in ranked:
            meta = r.get("metadata", {})
            cat = meta.get("category", "")
            doc = r.get("document", "")
            if doc:
                line = f"• [{cat}] {doc}" if cat else f"• {doc}"
                lines.append(line)

        text = f"Known facts about {req.username}:\n" + "\n".join(lines)
        surfaced_ids = {str(r.get("id")) for r in ranked if r.get("id") is not None}

        return (
            [
                ContextFragment(
                    name="user_memory",
                    priority=self._priority,
                    text=text,
                    est_chars=len(text),
                    confidence=avg_conf,  # Sprint 13, Sortie 5 (REQ-300)
                )
            ]
            + signal_frags,
            surfaced_ids,
            speaker_signals,
        )

    def _format_categorized(
        self, req: ContextRequest, ranked: list[dict[str, Any]]
    ) -> tuple[list[ContextFragment], set[str]]:
        """Group the speaker's facts by category (Sortie 4).

        ``sections`` mode renders one ``user_memory`` fragment with labeled
        sections in ``order``; ``fragments`` mode emits one fragment per category
        with its own priority so the budget trimmer can drop categories
        independently.
        """
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in ranked:
            cat = str(r.get("metadata", {}).get("category", "") or "other")
            groups.setdefault(cat, []).append(r)

        # Configured order first, then any remaining categories alphabetically.
        ordered = [c for c in self._cat_order if c in groups]
        ordered += sorted(c for c in groups if c not in self._cat_order)

        surfaced_ids: set[str] = set()
        sections: list[tuple[str, str, str]] = []  # (category, label, body)
        for cat in ordered:
            cap = int(self._cat_top_k.get(cat, self._cat_top_k.get("default", 2)))
            rows = [r for r in groups[cat] if r.get("document")][:cap]
            if not rows:
                continue
            label = self._cat_labels.get(cat, cat.replace("_", " ").title())
            body = " · ".join(str(r.get("document", "")) for r in rows)
            sections.append((cat, label, body))
            surfaced_ids |= {str(r.get("id")) for r in rows if r.get("id") is not None}

        if not sections:
            return [], set()

        if self._cat_mode == "fragments":
            frags: list[ContextFragment] = []
            for cat, label, body in sections:
                prio = int(
                    self._cat_priority.get(cat, self._cat_priority.get("default", self._priority))
                )
                text = f"{label}: {body}"
                frags.append(
                    ContextFragment(
                        name=f"user_memory_{cat}",
                        priority=prio,
                        text=text,
                        est_chars=len(text),
                    )
                )
            return frags, surfaced_ids

        lines = [f"  {label}: {body}" for _cat, label, body in sections]
        text = f"Known about {req.username}:\n" + "\n".join(lines)
        return [
            ContextFragment(
                name="user_memory",
                priority=self._priority,
                text=text,
                est_chars=len(text),
            )
        ], surfaced_ids

    async def _novelty_signal(
        self, req: ContextRequest, results: list[dict[str, Any]]
    ) -> list[ContextFragment]:
        """Read-only novelty / contradiction signal (Sortie 6; Sprint 9 S3).

        Reuses the speaker's already-fetched nearest fact (no extra store query)
        and never mutates stored facts inline.  Sprint 13 Sortie 3 (REQ-290–294):
        when a contradiction is confirmed, fires ``_apply_confidence_decay`` off the
        critical path (fire-and-forget; never affects ``provide()`` latency).
        """
        if not self._novelty_enabled or not results:
            return []
        nearest = min(results, key=lambda r: r.get("distance", 1.0))
        sim = max(0.0, 1.0 - float(nearest.get("distance", 1.0)))
        doc = str(nearest.get("document", ""))

        if sim < self._novelty_max_similarity:
            text = f"{self._novel_label.format(user=req.username)}: {req.message}"
        elif sim > self._contradiction_min_similarity and await self._is_contradiction(
            req.message, doc, len(results)
        ):
            text = f"{self._contradiction_label}: {doc}"
            # Sprint 13, Sortie 3 (REQ-290–292): decay confidence off the critical path.
            decay = self._confidence_contradiction_decay
            floor = self._confidence_floor
            if decay > 0 and nearest.get("id") is not None:
                asyncio.ensure_future(
                    self._apply_confidence_decay(str(nearest["id"]), decay, floor)
                )
        else:
            return []

        return [
            ContextFragment(
                name="memory_signal",
                priority=self._novelty_priority,
                text=text,
                est_chars=len(text),
            )
        ]

    async def _apply_confidence_decay(self, fact_id: str, decay: float, floor: float) -> None:
        """Decrement the confidence of *fact_id* by *decay*, floored at *floor* (REQ-290–292).

        Sprint 18, Sortie 2 (REQ-375–379): when ``_confidence_importance_gated_decay`` is
        True, scales the effective decay by ``1 / importance`` — a well-corroborated fact
        is more resistant to a single contradiction.

        Off-path, fire-and-forget.  Errors are logged and silently swallowed.
        """
        get_meta = getattr(self._store, "get_metadata", None)
        update_meta = getattr(self._store, "update_metadata", None)
        if get_meta is None or update_meta is None:
            return
        try:
            metas = await get_meta(ids=[fact_id])
            if not metas or metas[0] is None:
                return
            meta = dict(metas[0])
            old_conf = float(meta.get("confidence", 0.5))
            # REQ-376: gate decay by importance when configured.
            effective_decay = decay
            if self._confidence_importance_gated_decay:
                importance = int(meta.get("importance", 1))
                effective_decay = decay / max(importance, 1)
            new_conf = max(floor, old_conf - effective_decay)
            if new_conf == old_conf:
                return
            meta["confidence"] = new_conf
            await update_meta(ids=[fact_id], metadatas=[meta])
            logger.debug(
                "LTM contradiction decay: fact=%s conf %.2f → %.2f (decay=%.4f, floor=%.2f)",
                fact_id[:16],
                old_conf,
                new_conf,
                effective_decay,
                floor,
            )
        except Exception as exc:
            logger.debug("LTM._apply_confidence_decay failed for '%s': %s", fact_id, exc)

    async def _is_contradiction(self, message: str, doc: str, candidate_count: int) -> bool:
        """Decide contradiction via embedding opposition (S3) or keyword heuristic (S8)."""
        if self._contradiction_method == "embedding":
            # Cold-start guard (REQ-142): require enough stored facts (candidate
            # count is a cheap proxy that avoids an extra store round-trip).
            if candidate_count < self._min_facts_for_contradiction:
                return False
            score = await opposition_score(message, doc, self._embedder)
            if score is not None:
                return score >= self._opposition_threshold
            # Fall back to the heuristic if the scorer is unavailable (REQ-144).
        return self._polarity_differs(message, doc)

    @staticmethod
    def _polarity_differs(message: str, doc: str) -> bool:
        """True when exactly one of the two texts carries a negation marker (v1)."""
        return bool(_NEGATION_RE.search(message)) != bool(_NEGATION_RE.search(doc))

    def _should_run_topical(self, req: ContextRequest) -> bool:
        """Topical recall fires only when enabled and the trigger type qualifies."""
        if not (self._cross_user_enabled and self._topical_enabled):
            return False
        trigger_type = str((req.trigger or {}).get("type", ""))
        return trigger_type in self._topical_fire_on

    async def _run_topical_scope(
        self, req: ContextRequest, exclude_ids: set[str]
    ) -> tuple[list[ContextFragment], set[str]]:
        """Cross-user, topic-scoped recall (``topical_memory``) — Sprint 8, Sortie 1.

        Retrieves facts similar to the current message regardless of author,
        excludes currently-silenced users (shadow-mute gate), and attributes each
        line to its source user.
        """
        query_vec = await self._message_query_vector(req)
        if query_vec is None:
            return [], set()

        where: dict[str, Any] | None = (
            {"user": {"$ne": req.username}} if self._topical_exclude_speaker else None
        )
        # Over-fetch: the gate + speaker de-dup can drop rows before the top-K trim.
        fetch_k = min(self._topical_top_k * 3, self._topical_top_k + 20)
        results = await self._store.query(vector=query_vec, k=fetch_k, where=where)
        if not results:
            return [], set()

        max_distance = 1.0 - self._topical_min_similarity
        filtered = [
            r
            for r in results
            if r.get("distance", 1.0) <= max_distance and str(r.get("id")) not in exclude_ids
        ]
        if not filtered:
            return [], set()

        # Sprint 11: cache max topical similarity for engagement score (REQ-221).
        self._last_topical_max_sim = max(max(0.0, 1.0 - r.get("distance", 1.0)) for r in filtered)

        # Sprint 9 (S1): rank cross-user candidates by importance + recency too.
        if self._topical_boost and self._llm_mode and self._ext_cfg is not None:
            filtered = self._rank_with_boost(filtered)

        gated = await self._filter_silenced(filtered)
        if gated is None:  # gate failure + fail_closed → withhold cross-user recall
            return [], set()
        gated = gated[: self._topical_top_k]
        if not gated:
            return [], set()

        lines = []
        for r in gated:
            meta = r.get("metadata", {})
            user = meta.get("user", "?")
            doc = r.get("document", "")
            if doc:
                lines.append(f"• [{user}] {doc}")
        if not lines:
            return [], set()

        surfaced = {str(r.get("id")) for r in gated if r.get("id") is not None}
        text = "Relevant things people have said before:\n" + "\n".join(lines)
        return [
            ContextFragment(
                name="topical_memory",
                priority=self._topical_priority,
                text=text,
                est_chars=len(text),
            )
        ], surfaced

    def _should_run_room(self, req: ContextRequest) -> bool:
        """Room awareness fires only when enabled and the trigger type qualifies."""
        if not (self._cross_user_enabled and self._room_enabled):
            return False
        return str((req.trigger or {}).get("type", "")) in self._room_fire_on

    def _active_other_users(self, req: ContextRequest) -> list[str]:
        """Distinct recent chatters, excluding the speaker and the bot (Sortie 2)."""
        history = getattr(self._context_manager, "chat_history", None)
        if not history:
            return []
        recent = list(history)[-self._room_window_messages :]
        speaker = req.username.lower()
        seen: list[str] = []
        seen_low: set[str] = set()
        for m in reversed(recent):  # most-recent first
            name = getattr(m, "username", "")
            low = name.lower()
            if not name or low in seen_low or low == speaker or low == self._bot_name:
                continue
            seen.append(name)
            seen_low.add(low)
            if len(seen) >= self._room_max_users:
                break
        return seen

    async def _present_other_users(self, req: ContextRequest) -> list[str]:
        """Resolve present users from the robot userlist (Sortie 2), falling back to
        the recent-activity heuristic on unavailability."""
        if (
            self._room_presence_source == "userlist"
            and self._client is not None
            and self._domain
            and self._channel
        ):
            names = await self._read_userlist()
            if names:
                present = self._filter_presence(names, req)
                if present:
                    return present
            if self._monitor is not None:
                self._monitor.record_memory_presence_fallback()
        return self._active_other_users(req)

    async def _read_userlist(self) -> list[str] | None:
        """Read usernames from the robot's userlist KV (TTL-cached); None on failure."""
        now = time.monotonic()
        if (
            self._userlist_cache is not None
            and (now - self._userlist_cache_at) < self._room_presence_ttl
        ):
            return self._userlist_cache
        safe_domain = self._domain.lower().replace(".", "_")
        bucket = f"cytube_{safe_domain}_{self._channel.lower()}_userlist"
        try:
            users = await self._client.kv_get(bucket, "users", default=[], parse_json=True)
        except Exception as exc:
            logger.debug(f"room presence: userlist read failed: {exc}")
            return None
        if isinstance(users, list):
            names = [str(u.get("name")) for u in users if isinstance(u, dict) and u.get("name")]
        else:
            names = []
        self._userlist_cache = names
        self._userlist_cache_at = now
        return names

    def _filter_presence(self, names: list[str], req: ContextRequest) -> list[str]:
        """Dedup names, drop speaker + bot, cap at max_users (order preserved)."""
        speaker = req.username.lower()
        seen: list[str] = []
        seen_low: set[str] = set()
        for name in names:
            low = name.lower()
            if not name or low in seen_low or low == speaker or low == self._bot_name:
                continue
            seen.append(name)
            seen_low.add(low)
            if len(seen) >= self._room_max_users:
                break
        return seen

    async def _run_room_scope(
        self, req: ContextRequest, exclude_ids: set[str]
    ) -> tuple[list[ContextFragment], set[str]]:
        """Facts for the other people currently in the room (``room_memory``)."""
        active = await self._present_other_users(req)
        if not active:
            return [], set()

        query_vec = await self._message_query_vector(req)
        if query_vec is None:
            return [], set()

        fetch_k = max(len(active) * self._room_facts_per_user * 3, len(active) + 10)
        results = await self._store.query(
            vector=query_vec, k=fetch_k, where={"user": {"$in": active}}
        )
        if not results:
            return [], set()

        max_distance = 1.0 - self._room_min_similarity
        filtered = [
            r
            for r in results
            if r.get("distance", 1.0) <= max_distance and str(r.get("id")) not in exclude_ids
        ]
        if self._room_boost and self._llm_mode and self._ext_cfg is not None:
            filtered = self._rank_with_boost(filtered)
        gated = await self._filter_silenced(filtered)
        if gated is None:
            return [], set()

        # Cap facts_per_user per user, following distance order.
        per_user: dict[str, int] = {}
        chosen: list[dict[str, Any]] = []
        for r in gated:
            user = str(r.get("metadata", {}).get("user", ""))
            if not r.get("document"):
                continue
            if per_user.get(user, 0) >= self._room_facts_per_user:
                continue
            per_user[user] = per_user.get(user, 0) + 1
            chosen.append(r)
        if not chosen:
            return [], set()

        lines = [f"• [{r['metadata'].get('user', '?')}] {r.get('document', '')}" for r in chosen]
        text = "People here right now:\n" + "\n".join(lines)
        surfaced = {str(r.get("id")) for r in chosen if r.get("id") is not None}
        return [
            ContextFragment(
                name="room_memory",
                priority=self._room_priority,
                text=text,
                est_chars=len(text),
            )
        ], surfaced

    async def _run_callback_scope(
        self, req: ContextRequest, exclude_ids: set[str]
    ) -> tuple[list[ContextFragment], set[str]]:
        """Occasionally resurface an old, important, off-topic fact (Sortie 5).

        Probabilistic and cooldown-limited; reads existing metadata only and
        never mutates stored facts.
        """
        channel = req.channel or ""
        remaining = self._callback_cooldown.get(channel, 0)
        if remaining > 0:
            self._callback_cooldown[channel] = remaining - 1
            return [], set()
        if random.random() >= self._callback_probability:
            return [], set()

        where: dict[str, Any] = (
            {"user": {"$ne": req.username}}
            if self._callback_scope == "any"
            else {"user": req.username}
        )
        try:
            records = await self._store.get_all(where=where)
        except Exception as exc:  # store may not support get_all
            logger.debug(f"callback: get_all failed: {exc}")
            return [], set()
        if not records:
            return [], set()

        cutoff = datetime.now(timezone.utc) - timedelta(days=self._callback_min_age_days)
        cands: list[dict[str, Any]] = []
        for r in records:
            meta = r.get("metadata", {})
            if str(r.get("id")) in exclude_ids or not r.get("document"):
                continue
            if int(meta.get("importance", 1)) < self._callback_min_importance:
                continue
            created = self._parse_created_at(meta.get("created_at"))
            if created is None or created > cutoff:
                continue
            cands.append(r)
        if not cands:
            return [], set()

        if self._callback_scope == "any":
            gated = await self._filter_silenced(cands)
            if gated is None or not gated:
                return [], set()
            cands = gated

        cands = await self._filter_topic_dissimilar(req, cands)
        if not cands:
            return [], set()

        weights = [max(1, int(r.get("metadata", {}).get("importance", 1))) for r in cands]
        chosen = random.choices(cands, weights=weights, k=1)[0]
        self._callback_cooldown[channel] = self._callback_cooldown_turns

        doc = str(chosen.get("document", ""))
        if self._callback_scope == "any":
            user = chosen.get("metadata", {}).get("user", "?")
            text = f"{self._callback_label}: [{user}] {doc}"
        else:
            text = f"{self._callback_label}: {doc}"
        surfaced = {str(chosen.get("id"))} if chosen.get("id") is not None else set()
        return [
            ContextFragment(
                name="callback_memory",
                priority=self._callback_priority,
                text=text,
                est_chars=len(text),
            )
        ], surfaced

    async def _filter_topic_dissimilar(
        self, req: ContextRequest, cands: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Drop candidates too similar to the current topic (a callback should feel
        bot-initiated, not an echo)."""
        if self._callback_max_sim >= 1.0:
            return cands
        qv = await self._message_query_vector(req)
        if qv is None:
            return cands
        vecs = await self._embedder.embed([str(r.get("document", "")) for r in cands])
        out: list[dict[str, Any]] = []
        for r, v in zip(cands, vecs):
            if self._cosine(qv, v) <= self._callback_max_sim:
                out.append(r)
        return out

    @staticmethod
    def _parse_created_at(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (na * nb)

    async def _update_mood(self, message: str) -> None:
        """Update the per-instance EWMA mood vector (Sortie 7).

        Only accepted (non-shadow, non-excluded) messages reach ``observe``, so
        shadow-muted chatter never shapes the mood.
        """
        if not message:
            return
        vecs = await self._embedder.embed([message])
        if not vecs:
            return
        v = vecs[0]
        if self._mood is None:
            self._mood = list(v)
        else:
            a = self._ambient_alpha
            if self._ambient_pooling == "attention":
                a = self._ambient_alpha * self._salience(message, 0, 1)
            self._mood = [(1.0 - a) * m + a * x for m, x in zip(self._mood, v)]
        self._mood = self._normalize(self._mood)
        self._mood_count += 1

    def _should_run_ambient(self, req: ContextRequest) -> bool:
        """Ambient recall fires only when warmed up and the trigger qualifies."""
        if not (self._cross_user_enabled and self._ambient_enabled):
            return False
        if self._mood is None or self._mood_count < self._ambient_warmup:
            return False
        return str((req.trigger or {}).get("type", "")) in self._ambient_fire_on

    async def _run_ambient_scope(
        self, req: ContextRequest, exclude_ids: set[str]
    ) -> tuple[list[ContextFragment], set[str]]:
        """Whole-room recall seeded by the ambient mood vector (``ambient_memory``)."""
        if self._mood is None:
            return [], set()
        fetch_k = min(self._ambient_top_k * 3, self._ambient_top_k + 20)
        results = await self._store.query(vector=self._mood, k=fetch_k, where=None)
        if not results:
            return [], set()

        max_distance = 1.0 - self._ambient_min_similarity
        filtered = [
            r
            for r in results
            if r.get("distance", 1.0) <= max_distance and str(r.get("id")) not in exclude_ids
        ]
        if self._ambient_boost and self._llm_mode and self._ext_cfg is not None:
            filtered = self._rank_with_boost(filtered)
        gated = await self._filter_silenced(filtered)
        if gated is None:
            return [], set()
        gated = gated[: self._ambient_top_k]

        lines = [
            f"• [{r['metadata'].get('user', '?')}] {r.get('document', '')}"
            for r in gated
            if r.get("document")
        ]
        if not lines:
            return [], set()

        text = "The room's vibe right now:\n" + "\n".join(lines)
        surfaced = {str(r.get("id")) for r in gated if r.get("id") is not None}
        return [
            ContextFragment(
                name="ambient_memory",
                priority=self._ambient_priority,
                text=text,
                est_chars=len(text),
            )
        ], surfaced

    @staticmethod
    def _normalize(v: list[float]) -> list[float]:
        n = math.sqrt(sum(x * x for x in v))
        if n == 0.0:
            return list(v)
        return [x / n for x in v]

    @staticmethod
    def _salience(
        text: str,
        index: int,
        n: int,
        centroid: list[float] | None = None,
        vector: list[float] | None = None,
    ) -> float:
        """Heuristic message salience (Sortie 4): length × recency × centrality."""
        tokens = len(text.split())
        length_w = min(1.0, tokens / 12.0) if tokens else 0.0
        recency_w = (index + 1) / n if n > 0 else 1.0
        s = length_w * recency_w
        if centroid is not None and vector is not None:
            central = max(0.0, LongTermMemoryProvider._cosine(vector, centroid))
            s *= 0.5 + 0.5 * central
        return s

    def _attention_pool(
        self, vectors: list[list[float]], texts: list[str], min_salience: float
    ) -> list[float]:
        """Salience-weighted mean of the window vectors (Sortie 4)."""
        n = len(vectors)
        if n == 1:
            return list(vectors[0])
        centroid = self._pool(vectors, 0.0)
        weights: list[float] = []
        for i, (t, v) in enumerate(zip(texts, vectors)):
            s = self._salience(t, i, n, centroid, v)
            weights.append(s if s >= min_salience else 0.0)
        total = sum(weights)
        if total <= 0.0:
            return self._pool(vectors, 0.0)
        dim = len(vectors[0])
        pooled = [0.0] * dim
        for w, vec in zip(weights, vectors):
            for j in range(dim):
                pooled[j] += w * vec[j]
        return self._normalize([x / total for x in pooled])

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
            if self._gate_fail_closed and self._monitor is not None:
                self._monitor.record_memory_gate_fail_closed()
            return None if self._gate_fail_closed else rows
        kept = [r for r in rows if r.get("metadata", {}).get("user", "").lower() not in silenced]
        if self._monitor is not None and len(kept) < len(rows):
            self._monitor.record_memory_silenced_excluded(len(rows) - len(kept))
        return kept

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
                # Sprint 13, Sortie 1 (REQ-280–281): heuristic confidence = score / 100.
                "confidence": min(1.0, fact.score / 100.0),
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
        """Increment the importance counter on an existing fact (REQ-033/034/036).

        Sprint 13, Sortie 2 (REQ-285–289): also apply corroboration confidence boost
        when ``_confidence_corroboration_step > 0``.
        """
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

            # Sprint 13, Sortie 2 (REQ-285–287): corroboration → confidence boost.
            step = self._confidence_corroboration_step
            if step > 0:
                old_conf = float(meta.get("confidence", 0.5))
                meta["confidence"] = min(1.0, old_conf + step * (1.0 - old_conf))

            await update_meta(ids=[fact_id], metadatas=[meta])
            logger.debug(
                f"  importance bump: {current} -> {new_importance}"
                + (f" (evidence: '{str(evidence.get('message', ''))[:60]}')" if evidence else "")
            )
        except Exception as exc:
            logger.warning(f"LTM._bump_importance failed for '{fact_id}': {exc}")

    def _rank_with_boost(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Blend importance + recency + confidence into similarity for ranking (REQ-037, REQ-295)."""
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
            # Sprint 13, Sortie 4 (REQ-295–298): optional confidence axis.
            confidence = float(meta.get("confidence", 0.5))  # REQ-296: default 0.5
            return (
                similarity
                + boost.importance_weight * norm_imp
                + boost.recency_weight * recency
                + boost.confidence_weight * confidence
            )

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
