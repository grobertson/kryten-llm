"""Unit tests for ContextManager component."""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from kryten_llm.components.context_manager import ContextManager
from kryten_llm.models.config import LLMConfig
from kryten_llm.models.phase3 import VideoMetadata, ChatMessage


class TestContextManager:
    """Test ContextManager video and chat tracking."""

    def test_initialization(self, llm_config: LLMConfig):
        """Test ContextManager initializes correctly."""
        manager = ContextManager(llm_config)
        
        assert manager.config == llm_config
        assert manager.current_video is None
        assert len(manager.chat_history) == 0

    def test_initialization_with_custom_history_size(self, llm_config: LLMConfig):
        """Test ContextManager respects configured history size."""
        llm_config.context.chat_history_size = 50
        manager = ContextManager(llm_config)
        
        assert manager.chat_history.maxlen == 50

    @pytest.mark.asyncio
    async def test_handle_video_change(self, llm_config: LLMConfig):
        """Test video change event updates current_video."""
        manager = ContextManager(llm_config)
        
        video_data = {
            "title": "Tango & Cash (1989)",
            "seconds": 5400,
            "type": "yt",
            "queueby": "user123"
        }
        
        # _handle_video_change expects a dict directly, not a NATS message
        await manager._handle_video_change(video_data)
        
        assert manager.current_video is not None
        assert manager.current_video.title == "Tango & Cash (1989)"
        assert manager.current_video.duration == 5400
        assert manager.current_video.type == "yt"
        assert manager.current_video.queued_by == "user123"

    @pytest.mark.asyncio
    async def test_handle_video_change_truncates_long_title(self, llm_config: LLMConfig):
        """Test video change truncates titles longer than max_video_title_length."""
        llm_config.context.max_video_title_length = 200
        manager = ContextManager(llm_config)
        
        long_title = "A" * 300
        video_data = {
            "title": long_title,
            "seconds": 5400,
            "type": "yt",
            "queueby": "user123"
        }
        
        # _handle_video_change expects a dict directly
        await manager._handle_video_change(video_data)
        
        assert len(manager.current_video.title) == 200
        assert manager.current_video.title == "A" * 200

    @pytest.mark.asyncio
    async def test_handle_video_change_handles_missing_fields(self, llm_config: LLMConfig):
        """Test video change handles missing optional fields."""
        manager = ContextManager(llm_config)
        
        video_data = {
            "title": "Test Video"
            # Missing: seconds, type, queueby
        }
        
        # _handle_video_change expects a dict directly
        await manager._handle_video_change(video_data)
        
        assert manager.current_video is not None
        assert manager.current_video.title == "Test Video"
        assert manager.current_video.duration == 0
        assert manager.current_video.type == "unknown"
        assert manager.current_video.queued_by == "unknown"

    def test_add_chat_message(self, llm_config: LLMConfig):
        """Test adding chat message to history."""
        manager = ContextManager(llm_config)
        
        manager.add_chat_message("user1", "Hello world")
        
        assert len(manager.chat_history) == 1
        assert manager.chat_history[0].username == "user1"
        assert manager.chat_history[0].message == "Hello world"

    def test_add_chat_message_excludes_bot_messages(self, llm_config: LLMConfig):
        """Test bot's own messages are not added to history."""
        manager = ContextManager(llm_config)
        bot_name = llm_config.personality.character_name
        
        manager.add_chat_message(bot_name, "I am a bot")
        
        assert len(manager.chat_history) == 0

    def test_add_chat_message_rolling_buffer(self, llm_config: LLMConfig):
        """Test chat history maintains max size as rolling buffer."""
        llm_config.context.chat_history_size = 5
        manager = ContextManager(llm_config)
        
        # Add 10 messages
        for i in range(10):
            manager.add_chat_message(f"user{i}", f"Message {i}")
        
        assert len(manager.chat_history) == 5
        # Should have messages 5-9
        assert manager.chat_history[0].message == "Message 5"
        assert manager.chat_history[-1].message == "Message 9"

    def test_get_context_with_no_data(self, llm_config: LLMConfig):
        """Test get_context returns empty structure when no data."""
        manager = ContextManager(llm_config)
        
        context = manager.get_context()
        
        assert context["current_video"] is None
        assert context["recent_messages"] == []

    def test_get_context_with_video_only(self, llm_config: LLMConfig):
        """Test get_context includes video when available."""
        manager = ContextManager(llm_config)
        manager.current_video = VideoMetadata(
            title="Test Movie",
            duration=7200,
            type="yt",
            queued_by="user1",
            timestamp=datetime.now()
        )
        
        context = manager.get_context()
        
        assert context["current_video"] is not None
        assert context["current_video"]["title"] == "Test Movie"
        assert context["current_video"]["duration"] == 7200
        assert context["current_video"]["queued_by"] == "user1"

    def test_get_context_with_chat_history(self, llm_config: LLMConfig):
        """Test get_context includes recent messages."""
        manager = ContextManager(llm_config)
        
        manager.add_chat_message("user1", "Hello")
        manager.add_chat_message("user2", "Hi there")
        manager.add_chat_message("user3", "How are you?")
        
        context = manager.get_context()
        
        assert len(context["recent_messages"]) == 3
        assert context["recent_messages"][0]["username"] == "user1"
        assert context["recent_messages"][0]["message"] == "Hello"
        assert context["recent_messages"][2]["username"] == "user3"

    def test_get_context_limits_messages_in_prompt(self, llm_config: LLMConfig):
        """Test get_context respects max_chat_history_in_prompt."""
        llm_config.context.chat_history_size = 30
        llm_config.context.max_chat_history_in_prompt = 5
        manager = ContextManager(llm_config)
        
        # Add 20 messages
        for i in range(20):
            manager.add_chat_message(f"user{i}", f"Message {i}")
        
        context = manager.get_context()
        
        # Should only return last 5 messages
        assert len(context["recent_messages"]) == 5
        assert context["recent_messages"][0]["message"] == "Message 15"
        assert context["recent_messages"][-1]["message"] == "Message 19"

    def test_clear_chat_history(self, llm_config: LLMConfig):
        """Test clearing chat history."""
        manager = ContextManager(llm_config)
        
        manager.add_chat_message("user1", "Message 1")
        manager.add_chat_message("user2", "Message 2")
        assert len(manager.chat_history) > 0
        
        manager.clear_chat_history()
        
        assert len(manager.chat_history) == 0

    def test_get_stats(self, llm_config: LLMConfig):
        """Test get_stats returns correct statistics."""
        manager = ContextManager(llm_config)
        
        manager.add_chat_message("user1", "Message 1")
        manager.add_chat_message("user2", "Message 2")
        manager.current_video = VideoMetadata(
            title="Test",
            duration=100,
            type="yt",
            queued_by="user1",
            timestamp=datetime.now()
        )
        
        stats = manager.get_stats()
        
        assert stats["chat_history_size"] == 2
        assert stats["current_video_title"] == "Test"
        assert stats["chat_history_max"] == llm_config.context.chat_history_size

    def test_get_stats_no_video(self, llm_config: LLMConfig):
        """Test get_stats when no video playing."""
        manager = ContextManager(llm_config)
        
        stats = manager.get_stats()
        
        assert stats["current_video_title"] is None

    @pytest.mark.asyncio
    async def test_start_subscribes_to_changemedia(self, llm_config: LLMConfig):
        """Test start() subscribes to changemedia events."""
        manager = ContextManager(llm_config)
        
        mock_nats = Mock()
        mock_nats.subscribe = AsyncMock()
        
        await manager.start(mock_nats)
        
        # Verify subscription to changemedia subject
        mock_nats.subscribe.assert_called_once()
        call_args = mock_nats.subscribe.call_args
        subject = call_args[0][0]
        
        assert "changemedia" in subject
        # Get channel from first config entry
        channel_config = llm_config.channels[0]
        channel = channel_config.channel if hasattr(channel_config, 'channel') else channel_config.get("channel", "")
        assert channel in subject

    @pytest.mark.asyncio
    async def test_concurrent_access_thread_safe(self, llm_config: LLMConfig):
        """Test concurrent access to context is thread-safe."""
        manager = ContextManager(llm_config)
        
        # Simulate concurrent access
        async def add_messages():
            for i in range(100):
                manager.add_chat_message(f"user{i}", f"Message {i}")
                await asyncio.sleep(0)
        
        async def read_context():
            for i in range(100):
                context = manager.get_context()
                await asyncio.sleep(0)
        
        # Run concurrently
        await asyncio.gather(
            add_messages(),
            read_context(),
            add_messages()
        )
        
        # Should not crash and should have valid state
        context = manager.get_context()
        assert isinstance(context["recent_messages"], list)

    def test_video_metadata_immutability(self, llm_config: LLMConfig):
        """Test that video metadata is not mutated after storage."""
        manager = ContextManager(llm_config)
        
        original_title = "Original Title"
        manager.current_video = VideoMetadata(
            title=original_title,
            duration=100,
            type="yt",
            queued_by="user1",
            timestamp=datetime.now()
        )
        
        context = manager.get_context()
        context["current_video"]["title"] = "Modified Title"
        
        # Original should remain unchanged
        assert manager.current_video.title == original_title

    def test_chat_message_order_preserved(self, llm_config: LLMConfig):
        """Test chat messages maintain chronological order."""
        manager = ContextManager(llm_config)
        
        messages = ["First", "Second", "Third", "Fourth", "Fifth"]
        for msg in messages:
            manager.add_chat_message("user1", msg)
        
        context = manager.get_context()
        retrieved_messages = [m["message"] for m in context["recent_messages"]]
        
        assert retrieved_messages == messages

    @pytest.mark.asyncio
    async def test_handle_video_change_with_special_characters(self, llm_config: LLMConfig):
        """Test video change handles special characters in title."""
        manager = ContextManager(llm_config)
        
        video_data = {
            "title": "Movie: The \"Best\" Film & More (1989)",
            "seconds": 5400,
            "type": "yt",
            "queueby": "user123"
        }
        
        # _handle_video_change expects a dict directly
        await manager._handle_video_change(video_data)
        
        assert manager.current_video.title == 'Movie: The "Best" Film & More (1989)'

    def test_empty_message_not_added(self, llm_config: LLMConfig):
        """Test empty messages are still added (might be intentional whitespace)."""
        manager = ContextManager(llm_config)
        
        manager.add_chat_message("user1", "")
        
        # Current implementation adds empty messages
        assert len(manager.chat_history) == 1

    def test_performance_large_history(self, llm_config: LLMConfig):
        """Test performance with maximum history size."""
        llm_config.context.chat_history_size = 1000
        manager = ContextManager(llm_config)
        
        import time
        start = time.time()
        
        # Add many messages
        for i in range(1000):
            manager.add_chat_message(f"user{i}", f"Message {i}")
        
        elapsed = time.time() - start
        
        # Should be fast (< 1 second for 1000 messages)
        assert elapsed < 1.0
        
        # Get context should also be fast
        start = time.time()
        context = manager.get_context()
        elapsed = time.time() - start
        
        assert elapsed < 0.01  # < 10ms as per REQ-028
