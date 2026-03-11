"""Tests for deduplication manager."""

import time
from unittest.mock import Mock

import pytest
from datetime import datetime, timezone

from kryten import ChatMessageEvent, ChangeMediaEvent

from kryten_llm.components.deduplication_manager import DeduplicationManager
from kryten_llm.models.config import ContextConfig


@pytest.fixture
def config():
    """Test context configuration."""
    return ContextConfig(
        enable_enhanced_deduplication=True,
        reconnection_grace_period=120,
        correlation_id_cache_size=100,
    )


@pytest.fixture
def dedup_manager(config):
    """Test deduplication manager."""
    return DeduplicationManager(config)


@pytest.fixture
def sample_chat_event():
    """Sample chat message event."""
    return ChatMessageEvent(
        username="testuser",
        message="hello world",
        timestamp=datetime.now(timezone.utc),
        rank=1,
        channel="testchannel",
        domain="cytu.be",
        correlation_id="test-correlation-id-123"
    )


@pytest.fixture 
def sample_media_event():
    """Sample media change event."""
    event = Mock()
    event.title = "Test Video"
    event.duration = 1800  # 30 minutes
    event.media_type = "youtube"
    return event


class TestConnectionStateTracking:
    """Test robot connection state tracking."""

    def test_initial_state_connected(self, dedup_manager):
        """Robot should be assumed connected initially."""
        assert dedup_manager.robot_connected is True
        assert dedup_manager.last_disconnection_time is None
        assert dedup_manager.last_reconnection_time is None

    def test_disconnection_tracking(self, dedup_manager):
        """Disconnection should be tracked with timestamp."""
        start_time = time.time()
        dedup_manager.track_robot_connection_state(False)
        
        assert dedup_manager.robot_connected is False
        assert dedup_manager.last_disconnection_time is not None
        assert dedup_manager.last_disconnection_time >= start_time

    def test_reconnection_tracking(self, dedup_manager):
        """Reconnection should trigger grace period."""
        # Start disconnected
        dedup_manager.track_robot_connection_state(False)
        assert not dedup_manager.is_in_reconnection_grace_period()
        
        # Reconnect
        start_time = time.time()
        dedup_manager.track_robot_connection_state(True)
        
        assert dedup_manager.robot_connected is True
        assert dedup_manager.last_reconnection_time is not None
        assert dedup_manager.last_reconnection_time >= start_time
        assert dedup_manager.is_in_reconnection_grace_period()

    def test_grace_period_expiry(self, config):
        """Grace period should expire after configured time."""
        # Use short grace period for testing
        config.reconnection_grace_period = 1
        dedup_manager = DeduplicationManager(config)
        
        # Simulate reconnection
        dedup_manager.track_robot_connection_state(False)
        dedup_manager.track_robot_connection_state(True)
        
        # Should be in grace period immediately
        assert dedup_manager.is_in_reconnection_grace_period()
        
        # Wait for grace period to expire
        time.sleep(1.1)
        assert not dedup_manager.is_in_reconnection_grace_period()


class TestChatMessageDeduplication:
    """Test chat message deduplication."""

    def test_first_message_not_duplicate(self, dedup_manager, sample_chat_event):
        """First time seeing a correlation ID should not be duplicate."""
        assert not dedup_manager.is_duplicate_chat_message(sample_chat_event)

    def test_duplicate_correlation_id_detected(self, dedup_manager, sample_chat_event):
        """Same correlation ID should be detected as duplicate."""
        # Process first time
        assert not dedup_manager.is_duplicate_chat_message(sample_chat_event)
        
        # Same message again should be duplicate
        assert dedup_manager.is_duplicate_chat_message(sample_chat_event)

    def test_different_correlation_ids_not_duplicate(self, dedup_manager, sample_chat_event):
        """Different correlation IDs should not be duplicates."""
        # Process first message
        assert not dedup_manager.is_duplicate_chat_message(sample_chat_event)
        
        # Different correlation ID should not be duplicate
        sample_chat_event.correlation_id = "different-correlation-id"
        assert not dedup_manager.is_duplicate_chat_message(sample_chat_event)

    def test_grace_period_old_message_filtering(self, dedup_manager, sample_chat_event):
        """Messages from before disconnection should be ignored during grace period."""
        # Set up disconnection/reconnection scenario
        past_time = time.time() - 300  # 5 minutes ago
        dedup_manager.last_disconnection_time = past_time - 60  # Disconnected 6 minutes ago
        dedup_manager.last_reconnection_time = time.time()  # Just reconnected
        
        # Message from before disconnection
        sample_chat_event.timestamp = datetime.fromtimestamp(past_time - 120, timezone.utc)
        sample_chat_event.correlation_id = "old-message-id"
        
        assert dedup_manager.is_duplicate_chat_message(sample_chat_event)

    def test_cache_size_limit(self, config):
        """Correlation ID cache should respect size limit."""
        config.correlation_id_cache_size = 3
        dedup_manager = DeduplicationManager(config)
        
        # Add messages up to cache limit
        for i in range(4):
            event = Mock()
            event.correlation_id = f"id-{i}"
            event.timestamp = datetime.now(timezone.utc)
            dedup_manager.is_duplicate_chat_message(event)
        
        # Cache should only contain last 3 IDs
        assert len(dedup_manager.seen_correlation_ids) == 3
        assert "id-0" not in dedup_manager.seen_correlation_ids  # Oldest should be evicted
        assert "id-3" in dedup_manager.seen_correlation_ids


class TestMediaChangeDeduplication:
    """Test media change deduplication."""

    def test_first_media_change_not_duplicate(self, dedup_manager, sample_media_event):
        """First media change should not be duplicate."""
        assert not dedup_manager.is_duplicate_media_change(sample_media_event)

    def test_same_media_change_detected(self, dedup_manager, sample_media_event):
        """Same media change should be detected as duplicate."""
        # Process first time
        assert not dedup_manager.is_duplicate_media_change(sample_media_event)
        
        # Simulate reconnection grace period
        dedup_manager.last_reconnection_time = time.time()
        
        # Same media should be duplicate during grace period
        assert dedup_manager.is_duplicate_media_change(sample_media_event)

    def test_different_media_not_duplicate(self, dedup_manager, sample_media_event):
        """Different media should not be duplicate."""
        # Process first media
        assert not dedup_manager.is_duplicate_media_change(sample_media_event)
        
        # Different media should not be duplicate
        sample_media_event.title = "Different Video"
        assert not dedup_manager.is_duplicate_media_change(sample_media_event)

    def test_recent_media_change_duplicate(self, dedup_manager, sample_media_event):
        """Very recent media changes should be duplicates even outside grace period."""
        # Process first time
        assert not dedup_manager.is_duplicate_media_change(sample_media_event)
        
        # Same media within 30 seconds should still be duplicate
        # even without grace period
        assert dedup_manager.is_duplicate_media_change(sample_media_event)


class TestHistoricalMessageFiltering:
    """Test historical message filtering."""

    def test_before_service_start_filtered(self, dedup_manager):
        """Messages from before service start should be filtered."""
        service_start = time.time()
        old_timestamp = service_start - 300  # 5 minutes before start
        
        assert dedup_manager.should_ignore_historical_message(old_timestamp, service_start)

    def test_after_service_start_not_filtered(self, dedup_manager):
        """Messages after service start should not be filtered."""
        service_start = time.time() - 300  # Service started 5 minutes ago
        recent_timestamp = time.time() - 60  # Message 1 minute ago
        
        assert not dedup_manager.should_ignore_historical_message(recent_timestamp, service_start)

    def test_grace_period_pre_disconnection_filtered(self, dedup_manager):
        """Messages from before disconnection should be filtered during grace period."""
        # Set up disconnection/reconnection
        disconnection_time = time.time() - 120  # Disconnected 2 minutes ago
        dedup_manager.last_disconnection_time = disconnection_time
        dedup_manager.last_reconnection_time = time.time()  # Just reconnected
        
        # Message from before disconnection
        old_message_time = disconnection_time - 60  # 1 minute before disconnection
        service_start = time.time() - 300  # Service started 5 minutes ago
        
        assert dedup_manager.should_ignore_historical_message(old_message_time, service_start)


class TestOldMessageFiltering:
    """Test old message filtering."""

    def test_recent_message_not_filtered(self, dedup_manager):
        """Recent messages should not be filtered."""
        recent_timestamp = time.time() - 30  # 30 seconds ago
        
        assert not dedup_manager.should_ignore_old_message(recent_timestamp, max_age_seconds=60)

    def test_old_message_filtered(self, dedup_manager):
        """Old messages should be filtered."""
        old_timestamp = time.time() - 120  # 2 minutes ago
        
        assert dedup_manager.should_ignore_old_message(old_timestamp, max_age_seconds=60)

    def test_grace_period_stricter_filtering(self, dedup_manager):
        """Grace period should use stricter age limits."""
        # Set up grace period
        dedup_manager.last_reconnection_time = time.time()
        
        # Message that would normally pass but should be filtered during grace period
        message_time = time.time() - 95  # 95 seconds ago
        
        # Normal threshold is 60s, but grace period uses max(60, 90) = 90s minimum
        # So 95 seconds should be filtered during grace period
        assert dedup_manager.should_ignore_old_message(message_time, max_age_seconds=60)


class TestStatusAndMaintenance:
    """Test status reporting and cache maintenance."""

    def test_get_status(self, dedup_manager):
        """Status should include all relevant information."""
        status = dedup_manager.get_status()
        
        assert "enhanced_deduplication" in status
        assert "robot_connected" in status
        assert "in_grace_period" in status
        assert "cached_correlation_ids" in status
        assert "last_media_change" in status

    def test_clear_cache(self, dedup_manager, sample_chat_event):
        """Clear cache should reset all cached data."""
        # Add some data
        dedup_manager.is_duplicate_chat_message(sample_chat_event)
        assert len(dedup_manager.seen_correlation_ids) > 0
        
        # Clear cache
        dedup_manager.clear_cache()
        
        assert len(dedup_manager.seen_correlation_ids) == 0
        assert dedup_manager.last_media_change is None
        assert dedup_manager.last_media_change_time is None

    def test_disabled_deduplication(self, config):
        """When disabled, deduplication should always return False."""
        config.enable_enhanced_deduplication = False
        dedup_manager = DeduplicationManager(config)
        
        # Create mock events
        chat_event = Mock()
        chat_event.correlation_id = "test-id"
        media_event = Mock()
        
        # Should never be duplicates when disabled
        assert not dedup_manager.is_duplicate_chat_message(chat_event)
        assert not dedup_manager.is_duplicate_media_change(media_event)
        assert not dedup_manager.is_in_reconnection_grace_period()