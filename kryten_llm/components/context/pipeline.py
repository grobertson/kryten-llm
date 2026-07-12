"""Context pipeline — loads, orchestrates, and budgets all context providers.

Phase 7a: REQ-002 through REQ-007.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from kryten_llm.components.context.base import (
    PROVIDER_REGISTRY,
    ContextFragment,
    ContextProvider,
    ContextRequest,
)

if TYPE_CHECKING:
    from kryten_llm.models.config import LLMConfig

logger = logging.getLogger(__name__)


class ContextPipeline:
    """Orchestrator that composes context from multiple providers.

    REQ-002: Providers, their order, and per-provider settings are driven
             entirely from ``config.json``.
    REQ-004: A single provider failure MUST NOT block response generation.
    REQ-005: Enforces a global character budget by trimming lowest-priority
             fragments first.
    REQ-007: Falls back to [video, chat_history] when no ``providers`` list
             is configured.
    """

    def __init__(self, providers: list[ContextProvider], context_window_chars: int):
        self._providers = providers
        self._budget = context_window_chars

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        config: "LLMConfig",
        deps: dict[str, Any] | None = None,
    ) -> "ContextPipeline":
        """Instantiate the pipeline from *config*.

        *deps* is an optional dict of shared dependencies (e.g. LLMManager,
        data_dir, logger) injected into providers that need them.

        REQ-002, REQ-007.
        """
        # Import built-in providers here to avoid circular imports at module level
        from kryten_llm.components.context.providers.chat_history import ChatHistoryProvider
        from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider
        from kryten_llm.components.context.providers.video import VideoContextProvider

        # Ensure built-ins are registered
        PROVIDER_REGISTRY.setdefault("video", VideoContextProvider)
        PROVIDER_REGISTRY.setdefault("chat_history", ChatHistoryProvider)
        PROVIDER_REGISTRY.setdefault("long_term_memory", LongTermMemoryProvider)

        # REQ-007: if no providers list is configured, default to the two built-ins
        provider_cfgs = []
        if hasattr(config, "context") and config.context.providers:
            provider_cfgs = config.context.providers
        else:
            # Backwards-compatible defaults — behaviour identical to Phase 6
            provider_cfgs = [
                {"type": "video", "enabled": True, "priority": 60},
                {"type": "chat_history", "enabled": True, "priority": 50},
            ]

        providers: list[ContextProvider] = []
        for pcfg in provider_cfgs:
            # Support both dict (from default) and Pydantic model (from config)
            if hasattr(pcfg, "model_dump"):
                pcfg_dict = pcfg.model_dump()
            else:
                pcfg_dict = dict(pcfg)

            if not pcfg_dict.get("enabled", True):
                logger.debug(f"Provider '{pcfg_dict.get('type')}' disabled by config, skipping")
                continue

            ptype = pcfg_dict.get("type", "")
            provider_cls = PROVIDER_REGISTRY.get(ptype)
            if provider_cls is None:
                logger.warning(f"Unknown provider type '{ptype}', skipping")
                continue

            try:
                provider = provider_cls.from_config(pcfg_dict, config, deps or {})
                providers.append(provider)
                logger.info(
                    f"Loaded context provider '{ptype}' (priority={pcfg_dict.get('priority', 0)})"
                )
            except Exception as exc:
                logger.error(f"Failed to instantiate provider '{ptype}': {exc}", exc_info=True)

        return cls(providers, config.context.context_window_chars)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def observe(self, username: str, message: str) -> None:
        """Route a message to all WRITE providers (off the critical path).

        Errors are caught per-provider (REQ-004).
        """
        tasks = []
        for provider in self._providers:
            if provider.writes:
                tasks.append(self._safe_observe(provider, username, message))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def build(self, req: ContextRequest) -> dict[str, Any]:
        """Call all READ providers and return a merged context dict.

        Returns a dict that is backward-compatible with the old
        ``ContextManager.get_context()`` shape so that ``PromptBuilder``
        needs no changes.
        """
        fragments = await self._collect_fragments(req)
        fragments = self._apply_budget(fragments)
        return self._merge_fragments(fragments)

    @property
    def providers(self) -> list[ContextProvider]:
        """Ordered list of registered providers."""
        return list(self._providers)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _safe_observe(self, provider: ContextProvider, username: str, message: str) -> None:
        """Call provider.observe, swallowing any exception (REQ-004)."""
        try:
            await provider.observe(username, message)
        except Exception as exc:
            logger.warning(f"Provider '{provider.id}' observe() raised: {exc}", exc_info=True)

    async def _collect_fragments(self, req: ContextRequest) -> list[ContextFragment]:
        """Gather fragments from all READ providers, fail-open (REQ-004)."""
        fragments: list[ContextFragment] = []
        for provider in self._providers:
            if not provider.reads:
                continue
            try:
                result = await provider.provide(req)
                fragments.extend(result)
            except Exception as exc:
                logger.warning(f"Provider '{provider.id}' provide() raised: {exc}", exc_info=True)
        return fragments

    def _apply_budget(self, fragments: list[ContextFragment]) -> list[ContextFragment]:
        """Trim lowest-priority fragments to stay within the character budget (REQ-005)."""
        # Fill in est_chars from text length where not already set
        for frag in fragments:
            if frag.est_chars == 0 and frag.text:
                frag.est_chars = len(frag.text)

        # Sort descending by priority — highest priority kept first
        sorted_frags = sorted(fragments, key=lambda f: f.priority, reverse=True)

        kept: list[ContextFragment] = []
        used = 0
        for frag in sorted_frags:
            cost = frag.est_chars or 0
            if used + cost <= self._budget:
                kept.append(frag)
                used += cost
            else:
                logger.debug(
                    f"Budget exceeded: dropping fragment '{frag.name}' "
                    f"({cost} chars, budget remaining {self._budget - used})"
                )
        return kept

    def _merge_fragments(self, fragments: list[ContextFragment]) -> dict[str, Any]:
        """Convert fragments to the legacy context dict shape.

        Providers contribute to the dict by *name*.  The dict is backward-
        compatible with what ``ContextManager.get_context()`` used to return.
        """
        # Start with safe defaults identical to Phase 6 baseline
        ctx: dict[str, Any] = {
            "current_video": None,
            "next_video": None,
            "recent_messages": [],
            "channel_users": 0,
            "active_users": [],
        }

        for frag in fragments:
            if frag.data is not None:
                # Structured payload — merge dict or store under name
                if isinstance(frag.data, dict):
                    ctx.update(frag.data)
                else:
                    ctx[frag.name] = frag.data
            elif frag.text is not None:
                # Plain text fragment — store under name (e.g. "user_memory")
                ctx[frag.name] = frag.text

        return ctx
