"""Context manager for video and chat history tracking.

Phase 3: Implements REQ-008 through REQ-013 for context-aware responses.
"""

import logging
from collections import deque
from datetime import datetime
from typing import Any, Dict, Optional

from kryten_llm.models.config import LLMConfig
from kryten_llm.models.phase3 import ChatMessage, VideoMetadata

logger = logging.getLogger(__name__)


class ContextManager:
    """Manages video and chat context for LLM prompts.

    Phase 3 component that:
    - Subscribes to CyTube video change events (REQ-008)
    - Maintains current video state (REQ-009)
    - Maintains rolling chat history buffer (REQ-010)
    - Provides context dict for prompt building (REQ-011)
    - Handles edge cases and privacy constraints (REQ-012, REQ-013)
    """

    def __init__(self, config: LLMConfig):
        """Initialize with configuration.

        Args:
            config: LLM configuration with context settings
        """
        self.config = config
        self.current_video: Optional[VideoMetadata] = None

        # REQ-010: Rolling buffer with configurable size
        self.chat_history: deque[ChatMessage] = deque(maxlen=config.context.chat_history_size)

        logger.info(
            f"ContextManager initialized: chat_history_size={config.context.chat_history_size}, "
            f"include_video={config.context.include_video_context}, "
            f"include_chat={config.context.include_chat_history}"
        )

    async def start(self, nats_client) -> None:
        """Start subscribing to context events.

        Args:
            nats_client: NATS client for subscriptions
        """
        # REQ-008: Subscribe to video change events
        # Use first configured channel
        channel_config = self.config.channels[0]
        channel = (
            channel_config.channel
            if hasattr(channel_config, "channel")
            else channel_config.get("channel", "unknown")
        )
        subject = f"kryten.events.cytube.{channel}.changemedia"

        await nats_client.subscribe(subject, self._handle_video_change)
        logger.info(f"ContextManager subscribed to: {subject}")

    async def _handle_video_change(self, msg: Dict[str, Any]) -> None:
        """Handle video change event from CyTube.

        REQ-009: Update current video state atomically.
        REQ-012: Handle edge cases (long titles, missing fields, special chars).

        Args:
            msg: Video metadata from changemedia event
        """
        try:
            # Extract and validate video metadata
            title = str(msg.get("title", "Unknown"))

            # REQ-012: Truncate long titles
            if len(title) > self.config.context.max_video_title_length:
                title = title[: self.config.context.max_video_title_length]
                logger.debug(
                    f"Truncated video title to {self.config.context.max_video_title_length} chars"
                )

            # REQ-009: Atomic update
            self.current_video = VideoMetadata(
                title=title,
                duration=msg.get("seconds", 0),
                type=msg.get("type", "unknown"),
                queued_by=msg.get("queueby", "unknown"),
                timestamp=datetime.now(),
            )

            logger.info(
                f"Video changed: '{self.current_video.title}' "
                f"({self.current_video.type}, {self.current_video.duration}s) "
                f"queued by {self.current_video.queued_by}"
            )

        except Exception as e:
            # REQ-033: Context errors should not block responses
            logger.warning(f"Error handling video change: {e}", exc_info=True)

    def add_chat_message(self, username: str, message: str) -> None:
        """Add a message to chat history buffer.

        REQ-010: Maintain rolling buffer excluding bot's own messages.
        REQ-013: Only store configured number of messages.

        Args:
            username: User who sent the message
            message: Message content
        """
        # REQ-010: Don't store bot's own messages
        if username == self.config.personality.character_name:
            return

        # REQ-013: Deque automatically maintains size limit
        self.chat_history.append(
            ChatMessage(username=username, message=message, timestamp=datetime.now())
        )

        logger.debug(
            f"Added message to history: {username}: {message[:50]}... "
            f"(buffer size: {len(self.chat_history)})"
        )

    def get_context(self) -> Dict[str, Any]:
        """Get current context for prompt building.

        REQ-011: Provide context dict with current_video and recent_messages.
        REQ-012: Handle None state for no video playing.

        Returns:
            Context dictionary with video and chat history
        """
        context: Dict[str, Any] = {}

        # Include video context if enabled and available
        if self.config.context.include_video_context and self.current_video:
            context["current_video"] = {
                "title": self.current_video.title,
                "duration": self.current_video.duration,
                "type": self.current_video.type,
                "queued_by": self.current_video.queued_by,
            }
        else:
            # REQ-012: No video playing
            context["current_video"] = None

        # Include chat history if enabled
        if self.config.context.include_chat_history:
            # REQ-016: Limit to most recent N messages for prompt
            max_messages = self.config.context.max_chat_history_in_prompt
            recent = list(self.chat_history)[-max_messages:] if self.chat_history else []

            context["recent_messages"] = [
                {"username": msg.username, "message": msg.message} for msg in recent
            ]
        else:
            context["recent_messages"] = []

        return context

    def clear_chat_history(self) -> None:
        """Clear chat history buffer.

        REQ-013: Support clearing on service restart or for privacy.
        """
        self.chat_history.clear()
        logger.info("Chat history buffer cleared")

    def get_stats(self) -> Dict[str, Any]:
        """Get context manager statistics.

        Returns:
            Statistics dict with buffer sizes and current state
        """
        return {
            "chat_history_size": len(self.chat_history),
            "chat_history_max": self.chat_history.maxlen,
            "has_video": self.current_video is not None,
            "current_video_title": self.current_video.title if self.current_video else None,
        }
