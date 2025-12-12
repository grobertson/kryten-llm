"""Unit tests for MessageListener component."""

import pytest

from kryten_llm.components.listener import MessageListener
from kryten_llm.models.config import LLMConfig


@pytest.mark.asyncio
class TestMessageListener:
    """Test MessageListener filtering and validation."""

    async def test_filter_valid_message(self, llm_config: LLMConfig, sample_chat_message: dict):
        """Test that valid messages pass through filter."""
        listener = MessageListener(llm_config)
        result = await listener.filter_message(sample_chat_message)

        assert result is not None
        assert result == sample_chat_message

    async def test_filter_spam_message_exclamation(self, llm_config: LLMConfig, spam_message: dict):
        """Test that spam messages starting with ! are filtered."""
        listener = MessageListener(llm_config)
        result = await listener.filter_message(spam_message)

        assert result is None

    async def test_filter_spam_message_slash(self, llm_config: LLMConfig):
        """Test that spam messages starting with / are filtered."""
        listener = MessageListener(llm_config)
        message = {
            "username": "testuser",
            "msg": "/me does something",
            "time": 1640000000,
            "meta": {"rank": 1},
        }
        result = await listener.filter_message(message)

        assert result is None

    async def test_filter_spam_message_period(self, llm_config: LLMConfig):
        """Test that spam messages starting with . are filtered."""
        listener = MessageListener(llm_config)
        message = {
            "username": "testuser",
            "msg": ".command",
            "time": 1640000000,
            "meta": {"rank": 1},
        }
        result = await listener.filter_message(message)

        assert result is None

    async def test_filter_system_user_server(self, llm_config: LLMConfig, system_message: dict):
        """Test that [server] messages are filtered."""
        listener = MessageListener(llm_config)
        result = await listener.filter_message(system_message)

        assert result is None

    async def test_filter_system_user_bot(self, llm_config: LLMConfig):
        """Test that [bot] messages are filtered."""
        listener = MessageListener(llm_config)
        message = {
            "username": "[bot]",
            "msg": "Bot message",
            "time": 1640000000,
            "meta": {"rank": 0},
        }
        result = await listener.filter_message(message)

        assert result is None

    async def test_filter_system_user_system(self, llm_config: LLMConfig):
        """Test that [system] messages are filtered."""
        listener = MessageListener(llm_config)
        message = {
            "username": "[system]",
            "msg": "System message",
            "time": 1640000000,
            "meta": {"rank": 0},
        }
        result = await listener.filter_message(message)

        assert result is None

    async def test_filter_missing_username(self, llm_config: LLMConfig):
        """Test that messages without username are filtered."""
        listener = MessageListener(llm_config)
        message = {"msg": "Test message", "time": 1640000000, "meta": {"rank": 1}}
        result = await listener.filter_message(message)

        assert result is None

    async def test_filter_missing_msg(self, llm_config: LLMConfig):
        """Test that messages without msg are filtered."""
        listener = MessageListener(llm_config)
        message = {"username": "testuser", "time": 1640000000, "meta": {"rank": 1}}
        result = await listener.filter_message(message)

        assert result is None

    async def test_filter_missing_time(self, llm_config: LLMConfig):
        """Test that messages without time are filtered."""
        listener = MessageListener(llm_config)
        message = {"username": "testuser", "msg": "Test message", "meta": {"rank": 1}}
        result = await listener.filter_message(message)

        assert result is None

    async def test_filter_empty_message(self, llm_config: LLMConfig):
        """Test that empty messages pass if they have required fields."""
        listener = MessageListener(llm_config)
        message = {"username": "testuser", "msg": "", "time": 1640000000, "meta": {"rank": 1}}
        result = await listener.filter_message(message)

        # Empty messages are valid, they just won't trigger anything
        assert result is not None
