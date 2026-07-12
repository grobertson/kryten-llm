"""Video context provider — wraps ContextManager's video tracking.

Phase 7a: REQ-007 (regression-safe built-in).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from kryten_llm.components.context.base import ContextFragment, ContextRequest, register_provider

if TYPE_CHECKING:
    from kryten_llm.components.context_manager import ContextManager
    from kryten_llm.models.config import LLMConfig

logger = logging.getLogger(__name__)


@register_provider("video")
class VideoContextProvider:
    """Read-only provider that surfaces current + next video metadata.

    Delegates all state to the existing :class:`ContextManager` so there is
    zero behavioural change when memory features are disabled.
    """

    id = "video"
    reads = True
    writes = False

    def __init__(self, context_manager: "ContextManager", priority: int = 60):
        self._cm = context_manager
        self._priority = priority

    @classmethod
    def from_config(
        cls,
        pcfg: dict[str, Any],
        config: "LLMConfig",
        deps: dict[str, Any],
    ) -> "VideoContextProvider":
        context_manager = deps.get("context_manager")
        if context_manager is None:
            raise ValueError("VideoContextProvider requires 'context_manager' in deps")
        return cls(
            context_manager=context_manager,
            priority=pcfg.get("priority", 60),
        )

    async def observe(self, username: str, message: str) -> None:
        """No-op — video state is updated by service event handlers."""

    async def provide(self, req: ContextRequest) -> list[ContextFragment]:
        try:
            ctx = self._cm.get_context()
            data = {
                "current_video": ctx.get("current_video"),
                "next_video": ctx.get("next_video"),
            }
            return [
                ContextFragment(
                    name="video",
                    priority=self._priority,
                    data=data,
                    est_chars=_estimate_video_chars(data),
                )
            ]
        except Exception as exc:
            logger.warning(f"VideoContextProvider.provide() failed: {exc}", exc_info=True)
            return []


def _estimate_video_chars(data: dict[str, Any]) -> int:
    """Rough character estimate for a video context dict."""
    total = 0
    for vid in [data.get("current_video"), data.get("next_video")]:
        if vid and isinstance(vid, dict):
            total += len(vid.get("title", "")) + 50  # title + metadata overhead
    return total
