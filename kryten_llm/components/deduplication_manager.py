"""Deduplication manager for handling reconnection scenarios.

This module provides enhanced deduplication to prevent duplicate responses
when kryten-robot reconnects and CyTube replays recent chat messages and media events.
"""

import logging
import time
from collections import deque
from typing import Any, Dict, Optional

from kryten import ChangeMediaEvent, ChatMessageEvent  # type: ignore[import-untyped]

from kryten_llm.models.config import ContextConfig

logger = logging.getLogger(__name__)


class DeduplicationManager:
    """Manages event deduplication during reconnection scenarios.

    This class tracks:
    - Robot connection state
    - Recent message correlation IDs
    - Last media change details
    - Reconnection grace periods

    To prevent duplicate responses when CyTube replays events after reconnection.
    """

    def __init__(self, config: ContextConfig):
        """Initialize deduplication manager.

        Args:
            config: Context configuration with deduplication settings
        """
        self.config = config

        # Connection state tracking
        self.robot_connected: bool = True  # Assume connected at start
        self.last_disconnection_time: Optional[float] = None
        self.last_reconnection_time: Optional[float] = None

        # Correlation ID cache for message deduplication
        self.seen_correlation_ids: deque[str] = deque(maxlen=config.correlation_id_cache_size)

        # Media change deduplication
        self.last_media_change: Optional[Dict[str, Any]] = None
        self.last_media_change_time: Optional[float] = None

        logger.info(
            f"DeduplicationManager initialized: enhanced={config.enable_enhanced_deduplication}, "
            f"grace_period={config.reconnection_grace_period}s, "
            f"cache_size={config.correlation_id_cache_size}"
        )

    def track_robot_connection_state(self, connected: bool) -> None:
        """Track robot connection state changes.

        Args:
            connected: True if robot is connected, False if disconnected
        """
        current_time = time.time()

        if connected and not self.robot_connected:
            # Robot reconnected
            self.last_reconnection_time = current_time
            logger.info(
                f"Robot reconnection detected, entering grace period for {self.config.reconnection_grace_period}s"
            )
        elif not connected and self.robot_connected:
            # Robot disconnected
            self.last_disconnection_time = current_time
            logger.info("Robot disconnection detected")

        self.robot_connected = connected

    def is_in_reconnection_grace_period(self) -> bool:
        """Check if we're currently in a reconnection grace period.

        Returns:
            True if within grace period after reconnection
        """
        if not self.config.enable_enhanced_deduplication:
            return False

        if not self.last_reconnection_time:
            return False

        time_since_reconnection = time.time() - self.last_reconnection_time
        return time_since_reconnection < self.config.reconnection_grace_period

    def is_duplicate_chat_message(self, event: ChatMessageEvent) -> bool:
        """Check if a chat message is a duplicate.

        Uses correlation ID tracking for enhanced deduplication during
        reconnection grace periods, falls back to basic checks otherwise.

        Args:
            event: Chat message event to check

        Returns:
            True if this is a duplicate message
        """
        if not self.config.enable_enhanced_deduplication:
            return False

        # Check correlation ID cache
        if event.correlation_id in self.seen_correlation_ids:
            logger.debug(
                f"Duplicate chat message detected via correlation ID: {event.correlation_id[:8]}... "
                f"from {event.username}"
            )
            return True

        # During grace period, be extra cautious about old messages
        if self.is_in_reconnection_grace_period():
            # Check if message timestamp is before the disconnection
            if (
                self.last_disconnection_time
                and event.timestamp.timestamp() < self.last_disconnection_time
            ):
                logger.debug(
                    f"Ignoring pre-disconnection message during grace period: "
                    f"{event.username}: {event.message[:30]}..."
                )
                return True

        # Not a duplicate, cache the correlation ID
        self.seen_correlation_ids.append(event.correlation_id)
        return False

    def is_duplicate_media_change(self, event: ChangeMediaEvent) -> bool:
        """Check if a media change is a duplicate.

        Compares media details to prevent re-announcing the same video
        when robot reconnects.

        Args:
            event: Media change event to check

        Returns:
            True if this is a duplicate media change
        """
        if not self.config.enable_enhanced_deduplication:
            return False

        current_media = {
            "title": event.title,
            "duration": event.duration,
            "media_type": event.media_type,
        }

        # Check if this is the same media as last change
        if self.last_media_change and self.last_media_change == current_media:
            # If within grace period, likely a replay
            if self.is_in_reconnection_grace_period():
                logger.debug(f"Duplicate media change detected during grace period: {event.title}")
                return True

            # Even outside grace period, if it's very recent (< 30 seconds), likely duplicate
            if self.last_media_change_time and time.time() - self.last_media_change_time < 30:
                logger.debug(f"Duplicate recent media change detected: {event.title}")
                return True

        # Not a duplicate, update last media change
        self.last_media_change = current_media
        self.last_media_change_time = time.time()
        return False

    def should_ignore_historical_message(
        self, message_timestamp: float, service_start_time: float
    ) -> bool:
        """Enhanced historical message detection.

        Args:
            message_timestamp: Message timestamp in Unix time
            service_start_time: Service start time in Unix time

        Returns:
            True if message should be ignored as historical
        """
        # Basic check: before service start
        if message_timestamp < service_start_time:
            return True

        # Enhanced check: during grace period, be more strict about recent messages
        if self.is_in_reconnection_grace_period():
            # If message is before disconnection, it's replayed
            if self.last_disconnection_time and message_timestamp < self.last_disconnection_time:
                return True

        return False

    def should_ignore_old_message(
        self, message_timestamp: float, max_age_seconds: int = 60
    ) -> bool:
        """Enhanced old message detection with dynamic thresholds.

        Args:
            message_timestamp: Message timestamp in Unix time
            max_age_seconds: Maximum message age in seconds

        Returns:
            True if message should be ignored as too old
        """
        message_age = time.time() - message_timestamp

        # During grace period, use stricter age limits
        if self.is_in_reconnection_grace_period():
            # Use longer threshold during grace period to catch replayed messages
            stricter_threshold = max(max_age_seconds, 90)
            return message_age > stricter_threshold

        # Normal age check
        return message_age > max_age_seconds

    def get_status(self) -> Dict[str, Any]:
        """Get current deduplication manager status.

        Returns:
            Status dictionary with current state
        """
        return {
            "enhanced_deduplication": self.config.enable_enhanced_deduplication,
            "robot_connected": self.robot_connected,
            "in_grace_period": self.is_in_reconnection_grace_period(),
            "grace_period_seconds": self.config.reconnection_grace_period,
            "last_reconnection": self.last_reconnection_time,
            "last_disconnection": self.last_disconnection_time,
            "cached_correlation_ids": len(self.seen_correlation_ids),
            "cache_max_size": self.config.correlation_id_cache_size,
            "last_media_change": self.last_media_change,
        }

    def clear_cache(self) -> None:
        """Clear correlation ID cache and reset state.

        Useful for testing or manual reset.
        """
        self.seen_correlation_ids.clear()
        self.last_media_change = None
        self.last_media_change_time = None
        logger.info("Deduplication cache cleared")
