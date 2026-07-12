"""Chat history context provider — wraps ContextManager's rolling buffer.

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


@register_provider("chat_history")
class ChatHistoryProvider:
    """Read/write provider that mirrors the existing rolling chat buffer.

    * **writes** — ``observe()`` forwards messages to ``ContextManager``.
    * **reads**  — ``provide()`` surfaces the recent-messages list + user info.

    Identical output to Phase 6's ``ContextManager.get_context()`` fields.
    """

    id = "chat_history"
    reads = True
    writes = True

    def __init__(self, context_manager: "ContextManager", priority: int = 50):
        self._cm = context_manager
        self._priority = priority

    @classmethod
    def from_config(
        cls,
        pcfg: dict[str, Any],
        config: "LLMConfig",
        deps: dict[str, Any],
    ) -> "ChatHistoryProvider":
        context_manager = deps.get("context_manager")
        if context_manager is None:
            raise ValueError("ChatHistoryProvider requires 'context_manager' in deps")
        return cls(
            context_manager=context_manager,
            priority=pcfg.get("priority", 50),
        )

    async def observe(self, username: str, message: str) -> None:
        """Add message to the rolling buffer (WRITE path)."""
        try:
            self._cm.add_chat_message(username, message)
        except Exception as exc:
            logger.warning(f"ChatHistoryProvider.observe() failed: {exc}", exc_info=True)

    async def provide(self, req: ContextRequest) -> list[ContextFragment]:
        """Return recent_messages + channel_users/active_users (READ path)."""
        try:
            ctx = self._cm.get_context()
            data = {
                "recent_messages": ctx.get("recent_messages", []),
                "channel_users": ctx.get("channel_users", 0),
                "active_users": ctx.get("active_users", []),
            }
            est = sum(
                len(m.get("username", "")) + len(m.get("message", ""))
                for m in data["recent_messages"]
            )
            return [
                ContextFragment(
                    name="recent_chat",
                    priority=self._priority,
                    data=data,
                    est_chars=est,
                )
            ]
        except Exception as exc:
            logger.warning(f"ChatHistoryProvider.provide() failed: {exc}", exc_info=True)
            return []
