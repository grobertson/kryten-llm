"""Context manager for video and chat history tracking.

Phase 3: Implements REQ-008 through REQ-013 for context-aware responses.
"""

import logging
import time  # Added import
from collections import deque
from datetime import datetime
from typing import Any, Dict, Optional

from kryten import ChangeMediaEvent, KrytenClient  # type: ignore[import-untyped]
from kryten.kv_store import get_kv_store, kv_get

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
        self.next_video: Optional[VideoMetadata] = None  # Added for next playing support

        # REQ-010: Rolling buffer with configurable size
        self.chat_history: deque[ChatMessage] = deque(maxlen=config.context.chat_history_size)

        # Track active users in channel
        self.users: Dict[str, Dict[str, Any]] = {}

        logger.info(
            f"ContextManager initialized: chat_history_size={config.context.chat_history_size}, "
            f"include_video={config.context.include_video_context}, "
            f"include_chat={config.context.include_chat_history}"
        )

    async def load_initial_state(self, kryten_client: KrytenClient) -> None:
        """Load initial video state from KV store on startup.

        Queries the Kryten-Robot's KV store for the current media
        (what's actually playing) rather than the playlist.

        Args:
            kryten_client: KrytenClient instance with KV access
        """
        if not self.config.context.include_video_context:
            logger.debug("Video context disabled, skipping initial state load")
            return

        try:
            # Get channel name from first configured channel
            channel_config = self.config.channels[0]
            channel = (
                channel_config.channel
                if hasattr(channel_config, "channel")
                else channel_config.get("channel", "unknown")
            )

            # Construct bucket name to match Kryten-Robot naming
            bucket_name = f"kryten_{channel}_playlist"

            logger.debug(f"Loading current media from KV bucket: {bucket_name}")

            # Get current media from KV store (set by changeMedia events)
            bucket = await get_kv_store(kryten_client._nats, bucket_name, logger=logger)
            current = await kv_get(bucket, "current", default=None, parse_json=True, logger=logger)

            # Get next media from KV store
            # The playlist is stored in keys "0", "1", "2"... but that's for queue
            # We need to find the next item. For now, we'll try to fetch "queue" or inspect playlist structure if possible
            # But based on typical KV store usage in Kryten, it might be a list or individual keys.
            # Assuming 'playlist' bucket structure. If complex, we might skip next for now or implement better fetching.
            # However, Kryten usually stores the active playlist.
            # Let's try to get "0" which is usually the top of the queue if "current" is separate.
            # NOTE: Implementation detail depends on Kryten's playlist storage.
            # Assuming we can get the queue list or top item.
            # Let's try getting "playlist" key if it exists, or "0".
            # If we can't reliably get next, we'll leave it None.

            # Trying to get next item from queue
            # Usually index 0 is next if current is playing.
            next_item = await kv_get(bucket, "0", default=None, parse_json=True, logger=logger)

            if current and isinstance(current, dict):
                logger.debug(f"Current media from KV: {current}")

                # Extract media info from changeMedia event payload
                title = current.get("title", "Unknown")
                duration = current.get("seconds", 0)
                media_type = current.get("type", "unknown")

                # changeMedia doesn't include queueby, but we can fall back
                queued_by = current.get("queueby", "unknown")

                # Truncate long titles
                if len(title) > self.config.context.max_video_title_length:
                    title = title[: self.config.context.max_video_title_length]

                self.current_video = VideoMetadata(
                    title=title,
                    duration=duration,
                    type=media_type,
                    queued_by=queued_by,
                    timestamp=datetime.now(),
                    start_time=time.time(),  # Track when we loaded/started it for position calculation
                )

                # If we loaded from KV, we might need to adjust start_time if possible,
                # but for now we assume 'now' or rely on what we have.
                # Ideally 'current' KV might have 'started_at' timestamp?
                # If not, position will be relative to when we loaded context.
                if "timestamp" in current:  # If Kryten stores start time
                    # Convert javascript timestamp (ms) to python (s) if needed
                    # Assuming standard Kryten behavior might not store this in 'current' object directly
                    pass

                logger.info(
                    f"Loaded current media from KV: '{self.current_video.title}' "
                    f"(type={media_type}, duration={duration}s)"
                )
            else:
                logger.info("No current media found in KV store, current_video remains None")

            # Process next item
            if next_item and isinstance(next_item, dict):
                next_duration = next_item.get("seconds", 0)
                # Filter by duration threshold (default 10 mins from media_change config)
                min_duration = self.config.media_change.min_duration_minutes * 60

                if next_duration >= min_duration:
                    self.next_video = VideoMetadata(
                        title=next_item.get("title", "Unknown"),
                        duration=next_duration,
                        type=next_item.get("type", "unknown"),
                        queued_by=next_item.get("queueby", "unknown"),
                        timestamp=datetime.now(),
                    )
                    logger.info(f"Loaded next media: {self.next_video.title}")
                else:
                    logger.debug(
                        f"Next media too short ({next_duration}s < {min_duration}s), ignoring"
                    )
                    self.next_video = None
            else:
                self.next_video = None

        except Exception as e:
            # Don't fail startup if initial state load fails
            logger.warning(f"Could not load initial video state from KV: {e}")

    async def start(self, kryten_client) -> None:
        """Start subscribing to context events.

        Args:
            kryten_client: KrytenClient instance for subscriptions
        """
        # REQ-008: Video change events are now handled by service.py
        # The service forwards changemedia events to this manager via _handle_video_change
        logger.info("ContextManager started (changemedia events handled by service.py)")

    async def _handle_video_change(self, event: ChangeMediaEvent) -> None:
        """Handle video change event from CyTube.

        REQ-009: Update current video state atomically.
        REQ-012: Handle edge cases (long titles, missing fields, special chars).

        Args:
            event: ChangeMediaEvent from kryten-py with video metadata
        """
        try:
            # Extract title from event
            title = str(event.title or "Unknown")

            # REQ-012: Truncate long titles
            if len(title) > self.config.context.max_video_title_length:
                title = title[: self.config.context.max_video_title_length]
                logger.debug(
                    f"Truncated video title to {self.config.context.max_video_title_length} chars"
                )

            # REQ-009: Atomic update
            self.current_video = VideoMetadata(
                title=title,
                duration=event.duration or 0,
                type=event.media_type or "unknown",
                queued_by="system",  # ChangeMediaEvent doesn't have queued_by field
                timestamp=datetime.now(),
                start_time=time.time(),  # Track start time
            )

            # Since video changed, the 'next' item is now 'current' (or unknown until refreshed from KV)
            # We can't know the NEXT item without querying KV again, or maintaining a local queue copy.
            # For simplicity/robustness, we should invalidate next_video or keep it if we knew it?
            # Ideally, we should re-poll KV for the new queue state, but we don't have client here easily?
            # Actually, service.py handles this event.
            # We'll just clear next_video for now to avoid stale data, or leave it.
            # Ideally, service should trigger a KV reload or we do it here if we had client.
            # Let's invalidate it for now.
            self.next_video = None

            logger.info(
                f"Video changed: '{self.current_video.title}' "
                f"({self.current_video.type}, {self.current_video.duration}s) "
                f"queued by {self.current_video.queued_by}"
            )

        except Exception as e:
            # REQ-033: Context errors should not block responses
            logger.warning(f"Error handling video change: {e}", exc_info=True)

    def add_chat_message(self, username: str, message: str) -> bool:
        """Add a message to chat history buffer.

        REQ-010: Maintain rolling buffer.
        REQ-013: Only store configured number of messages.

        Args:
            username: User who sent the message
            message: Message content

        Returns:
            bool: True if message was added, False if it was a duplicate
        """
        # Check for duplicate (reconnection replay)
        # Check if the exact same message from same user is already in history
        # We check the last few messages (e.g., last 20) to be safe/efficient
        for existing in list(self.chat_history)[-20:]:
            if existing.username == username and existing.message == message:
                logger.debug(
                    f"Skipping duplicate message from history: {username}: {message[:20]}..."
                )
                return False

        # REQ-013: Deque automatically maintains size limit
        self.chat_history.append(
            ChatMessage(username=username, message=message, timestamp=datetime.now())
        )

        logger.debug(
            f"Added message to history: {username}: {message[:50]}... "
            f"(buffer size: {len(self.chat_history)})"
        )
        return True

    def get_context(self) -> Dict[str, Any]:
        """Get current context for prompt building.

        REQ-011: Provide context dict with current_video and recent_messages.
        REQ-012: Handle None state for no video playing.

        Returns:
            Context dictionary with video and chat history
        """
        context: Dict[str, Any] = {}

        # Include video context if enabled and available
        logger.debug(
            f"get_context called: include_video={self.config.context.include_video_context}, "
            f"current_video={self.current_video.title if self.current_video else None}"
        )
        if self.config.context.include_video_context and self.current_video:
            # Calculate current position
            # If start_time is set, we can estimate position
            current_pos = 0.0
            if hasattr(self.current_video, "start_time") and self.current_video.start_time:
                current_pos = time.time() - self.current_video.start_time
                # Clamp to duration
                if current_pos > self.current_video.duration:
                    current_pos = self.current_video.duration

            context["current_video"] = {
                "title": self.current_video.title,
                "duration": self.current_video.duration,
                "type": self.current_video.type,
                "queued_by": self.current_video.queued_by,
                "position": current_pos,  # New field
            }

            # Add next video if available
            if self.next_video:
                context["next_video"] = {
                    "title": self.next_video.title,
                    "duration": self.next_video.duration,
                    "type": self.next_video.type,
                    "queued_by": self.next_video.queued_by,
                }
            else:
                context["next_video"] = None

            logger.info(f"Video context included: {self.current_video.title}")
        else:
            # REQ-012: No video playing
            context["current_video"] = None
            context["next_video"] = None
            logger.debug(
                f"No video context: enabled={self.config.context.include_video_context}, "
                f"has_video={self.current_video is not None}"
            )

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

        # Add user statistics
        context["channel_users"] = len(self.users)

        # Calculate active users (not AFK)
        # CyTube user object usually has 'meta' dict with 'afk' boolean, or top-level 'afk'
        active_users = []
        for u in self.users.values():
            is_afk = False
            if u.get("afk"):
                is_afk = True
            elif isinstance(u.get("meta"), dict) and u["meta"].get("afk"):
                is_afk = True

            if not is_afk:
                active_users.append(u.get("name", "Unknown"))

        context["active_users"] = active_users

        return context

    def handle_userlist(self, users: list[Dict[str, Any]]) -> None:
        """Handle initial userlist event.

        Args:
            users: List of user dictionaries
        """
        self.users.clear()
        for user in users:
            name = user.get("name")
            if name:
                self.users[name] = user
        logger.debug(f"Processed userlist: {len(self.users)} users")

    def handle_user_join(self, user: Dict[str, Any]) -> None:
        """Handle user join event.

        Args:
            user: User dictionary
        """
        name = user.get("name")
        if name:
            self.users[name] = user
            logger.debug(f"User joined: {name}")

    def handle_user_leave(self, username: str) -> None:
        """Handle user leave event.

        Args:
            username: Username of user who left
        """
        if username in self.users:
            del self.users[username]
            logger.debug(f"User left: {username}")

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
