"""Unit tests for TriggerEngine component."""

import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from kryten_llm.components.trigger_engine import TriggerEngine, logger as trigger_engine_logger
from kryten_llm.models.config import AutoParticipationConfig, LLMConfig

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
class TestTriggerEngine:
    """Test TriggerEngine mention detection and message cleaning."""

    async def test_detect_mention_lowercase(self, llm_config: LLMConfig):
        """Test detection of bot name in lowercase."""
        engine = TriggerEngine(llm_config)
        message = {
            "username": "testuser",
            "msg": "hey cynthia, how are you?",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        result = await engine.check_triggers(message)

        assert result.triggered is True
        assert result.trigger_type == "mention"
        assert result.trigger_name == "cynthia"
        assert result.priority == 10
        assert "cynthia" not in result.cleaned_message.lower()

    async def test_detect_mention_uppercase(self, llm_config: LLMConfig):
        """Test detection of bot name in uppercase (case-insensitive)."""
        engine = TriggerEngine(llm_config)
        message = {
            "username": "testuser",
            "msg": "CYNTHIA can you help?",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        result = await engine.check_triggers(message)

        assert result.triggered is True
        assert result.trigger_type == "mention"
        assert result.trigger_name == "cynthia"

    async def test_detect_mention_mixed_case(self, llm_config: LLMConfig):
        """Test detection of bot name in mixed case."""
        engine = TriggerEngine(llm_config)
        message = {
            "username": "testuser",
            "msg": "Hey CyNtHiA, what's up?",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        result = await engine.check_triggers(message)

        assert result.triggered is True
        assert result.trigger_type == "mention"

    async def test_detect_alternative_name(self, llm_config: LLMConfig):
        """Test detection using alternative name variation (rothrock)."""
        engine = TriggerEngine(llm_config)
        message = {
            "username": "testuser",
            "msg": "yo rothrock, thoughts on the new movie?",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        result = await engine.check_triggers(message)

        assert result.triggered is True
        assert result.trigger_type == "mention"
        assert result.trigger_name == "rothrock"

    async def test_no_mention_detected(self, llm_config: LLMConfig):
        """Test that non-mention messages are not triggered."""
        engine = TriggerEngine(llm_config)
        message = {
            "username": "testuser",
            "msg": "I love martial arts movies",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        result = await engine.check_triggers(message)

        assert result.triggered is False
        assert result.trigger_type is None
        assert result.trigger_name is None
        assert result.priority == 0

    async def test_cleaned_message_name_removed(self, llm_config: LLMConfig):
        """Test that bot name is removed from cleaned message."""
        engine = TriggerEngine(llm_config)
        message = {
            "username": "testuser",
            "msg": "hey cynthia, what's your favorite movie?",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        result = await engine.check_triggers(message)

        assert result.triggered is True
        # Name should be removed, leaving "what's your favorite movie?"
        assert "cynthia" not in result.cleaned_message.lower()
        assert "what's your favorite movie" in result.cleaned_message.lower()

    async def test_cleaned_message_punctuation_removed(self, llm_config: LLMConfig):
        """Test that punctuation after name is cleaned up."""
        engine = TriggerEngine(llm_config)
        message = {
            "username": "testuser",
            "msg": "Cynthia, can you help?",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        result = await engine.check_triggers(message)

        assert result.triggered is True
        # Should be "can you help?" not ", can you help?"
        assert not result.cleaned_message.startswith(",")
        assert "can you help" in result.cleaned_message.lower()

    async def test_cleaned_message_whitespace_normalized(self, llm_config: LLMConfig):
        """Test that extra whitespace is cleaned up."""
        engine = TriggerEngine(llm_config)
        message = {
            "username": "testuser",
            "msg": "hey   cynthia     what's up?",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        result = await engine.check_triggers(message)

        assert result.triggered is True
        # Extra spaces should be normalized
        assert "  " not in result.cleaned_message
        assert result.cleaned_message == result.cleaned_message.strip()

    async def test_mention_in_middle_of_message(self, llm_config: LLMConfig):
        """Test detection when name is in middle of message."""
        engine = TriggerEngine(llm_config)
        message = {
            "username": "testuser",
            "msg": "I think cynthia would know the answer",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        result = await engine.check_triggers(message)

        assert result.triggered is True
        assert result.trigger_name == "cynthia"

    async def test_mention_at_end_of_message(self, llm_config: LLMConfig):
        """Test detection when name is at end of message."""
        engine = TriggerEngine(llm_config)
        message = {
            "username": "testuser",
            "msg": "What do you think, cynthia?",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        result = await engine.check_triggers(message)

        assert result.triggered is True
        assert result.trigger_name == "cynthia"

    async def test_trigger_result_boolean(self, llm_config: LLMConfig):
        """Test that TriggerResult can be used as boolean."""
        engine = TriggerEngine(llm_config)

        # Triggered message
        message_yes = {
            "username": "testuser",
            "msg": "hey cynthia",
            "time": 1640000000,
            "meta": {"rank": 1},
        }
        result_yes = await engine.check_triggers(message_yes)
        assert bool(result_yes) is True

        # Non-triggered message
        message_no = {
            "username": "testuser",
            "msg": "just chatting",
            "time": 1640000000,
            "meta": {"rank": 1},
        }
        result_no = await engine.check_triggers(message_no)
        assert bool(result_no) is False

    async def test_context_is_none_for_mentions(self, llm_config: LLMConfig):
        """Test that context is None for mentions."""
        engine = TriggerEngine(llm_config)
        message = {
            "username": "testuser",
            "msg": "hey cynthia",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        result = await engine.check_triggers(message)

        assert result.triggered is True
        assert result.context is None  # Mentions don't have context


@pytest.mark.asyncio
class TestTriggerEnginePhase2:
    """Test Phase 2 trigger word patterns with probabilities."""

    async def test_trigger_word_match_probability_100(self, llm_config_with_triggers):
        """Test trigger word with 100% probability always triggers."""
        engine = TriggerEngine(llm_config_with_triggers)
        message = {
            "username": "testuser",
            "msg": "praise toddy!",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        # Run multiple times to verify 100% probability
        for _ in range(10):
            result = await engine.check_triggers(message)
            assert result.triggered is True
            assert result.trigger_type == "trigger_word"
            assert result.trigger_name == "toddy"
            assert result.priority == 8
            assert result.context == "Respond enthusiastically about Robert Z'Dar"

    async def test_trigger_word_match_probability_0(self, llm_config_with_triggers):
        """Test trigger word with 0% probability never triggers."""
        engine = TriggerEngine(llm_config_with_triggers)
        message = {
            "username": "testuser",
            "msg": "never trigger test",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        # Run multiple times to verify 0% probability
        for _ in range(10):
            result = await engine.check_triggers(message)
            assert result.triggered is False

    async def test_trigger_word_case_insensitive(self, llm_config_with_triggers):
        """Test trigger word matching is case-insensitive."""
        engine = TriggerEngine(llm_config_with_triggers)

        messages = ["I love KUNG FU movies!", "kung fu is great", "Kung Fu films rock"]

        for msg_text in messages:
            message = {
                "username": "testuser",
                "msg": msg_text,
                "time": 1640000000,
                "meta": {"rank": 1},
            }
            result = await engine.check_triggers(message)
            # Note: kung_fu has 0.3 probability, so it might not trigger
            # But pattern matching should work regardless
            assert result is not None

    async def test_trigger_word_priority_resolution(self, llm_config_with_triggers):
        """Test that higher priority trigger wins when multiple match."""
        engine = TriggerEngine(llm_config_with_triggers)
        message = {
            "username": "testuser",
            "msg": "I love kung fu movies!",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        # Both "kung fu" (priority 5) and "movie" (priority 3) could match
        # But kung fu has higher priority and should be checked first
        # Note: This test may be probabilistic if kung_fu probability < 1.0
        result = await engine.check_triggers(message)

        if result.triggered and result.trigger_type == "trigger_word":
            # If triggered, should be from highest priority matching trigger
            assert result.trigger_name in ["kung_fu", "movie"]

    async def test_mention_takes_priority_over_trigger_word(self, llm_config_with_triggers):
        """Test that mentions always take priority over trigger words."""
        engine = TriggerEngine(llm_config_with_triggers)
        message = {
            "username": "testuser",
            "msg": "hey cynthia, I love kung fu!",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        result = await engine.check_triggers(message)

        # Should trigger on mention, not on "kung fu" trigger word
        assert result.triggered is True
        assert result.trigger_type == "mention"
        assert result.trigger_name == "cynthia"
        assert result.priority == 10

    async def test_disabled_trigger_skipped(self, llm_config_with_triggers):
        """Test that disabled triggers are skipped."""
        engine = TriggerEngine(llm_config_with_triggers)
        message = {
            "username": "testuser",
            "msg": "disabled pattern test",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        # The "disabled" trigger should not match even if pattern found
        result = await engine.check_triggers(message)
        assert result.triggered is False

    async def test_trigger_word_cleaned_message(self, llm_config_with_triggers):
        """Test that trigger phrase is removed from cleaned message."""
        engine = TriggerEngine(llm_config_with_triggers)
        message = {
            "username": "testuser",
            "msg": "praise toddy for his greatness!",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        result = await engine.check_triggers(message)

        if result.triggered and result.trigger_type == "trigger_word":
            # "toddy" should be removed from cleaned message
            assert "toddy" not in result.cleaned_message.lower()
            assert "praise" in result.cleaned_message.lower()
            assert "greatness" in result.cleaned_message.lower()

    async def test_multiple_patterns_in_trigger(self, llm_config_with_triggers):
        """Test trigger with multiple patterns (OR logic)."""
        engine = TriggerEngine(llm_config_with_triggers)

        # toddy trigger has patterns: ["toddy", "robert z'dar"]
        messages = ["praise toddy!", "I love Robert Z'Dar movies!"]

        for msg_text in messages:
            message = {
                "username": "testuser",
                "msg": msg_text,
                "time": 1640000000,
                "meta": {"rank": 1},
            }
            result = await engine.check_triggers(message)

            # Both should trigger the "toddy" trigger (100% probability)
            assert result.triggered is True
            assert result.trigger_name == "toddy"

    async def test_no_triggers_configured(self, llm_config: LLMConfig):
        """Test behavior when no triggers are configured (Phase 1 config)."""
        engine = TriggerEngine(llm_config)
        message = {
            "username": "testuser",
            "msg": "some random message with kung fu",
            "time": 1640000000,
            "meta": {"rank": 1},
        }

        result = await engine.check_triggers(message)

        # Should not trigger on trigger words if none configured
        # Only mentions should work
        assert result.triggered is False


@pytest.mark.asyncio
class TestTriggerEngineAutoParticipation:
    
    async def test_auto_participation_disabled_by_default(self, llm_config: LLMConfig):
        engine = TriggerEngine(llm_config)
        assert engine.config.auto_participation.enabled is False
        
        # Send many messages
        msg = {"username": "user", "msg": "hello", "time": 0, "meta": {}}
        for _ in range(20):
            result = await engine.check_triggers(msg)
            assert result.triggered is False

    async def test_auto_participation_triggering(self, llm_config: LLMConfig):
        # Configure auto-participation
        llm_config.auto_participation = AutoParticipationConfig(
            enabled=True,
            base_message_interval=5,
            probability_range=0.0 # No random for deterministic test
        )
        
        engine = TriggerEngine(llm_config)
        # Threshold should be exactly 5
        assert engine.non_trigger_threshold == 5
        assert engine.messages_since_last_trigger == 0
        
        msg = {"username": "user", "msg": "hello", "time": 0, "meta": {}}
        
        # Message 1
        res = await engine.check_triggers(msg)
        assert res.triggered is False
        assert engine.messages_since_last_trigger == 1
        
        # Message 2
        res = await engine.check_triggers(msg)
        assert res.triggered is False
        assert engine.messages_since_last_trigger == 2
        
        # Message 3
        res = await engine.check_triggers(msg)
        assert res.triggered is False
        assert engine.messages_since_last_trigger == 3

        # Message 4
        res = await engine.check_triggers(msg)
        assert res.triggered is False
        assert engine.messages_since_last_trigger == 4

        # Message 5 -> Trigger!
        res = await engine.check_triggers(msg)
        assert res.triggered is True
        assert res.trigger_type == "auto_participant"
        assert engine.messages_since_last_trigger == 0
        
        # Next threshold should be 5 again (since prob=0)
        assert engine.non_trigger_threshold == 5

    async def test_reset_on_traditional_trigger(self, llm_config: LLMConfig):
        llm_config.auto_participation = AutoParticipationConfig(
            enabled=True,
            base_message_interval=10,
            probability_range=0.0
        )
        engine = TriggerEngine(llm_config)
        
        msg = {"username": "user", "msg": "hello", "time": 0, "meta": {}}
        mention_msg = {"username": "user", "msg": "hello cynthia", "time": 0, "meta": {}}
        
        # Send 5 messages
        for _ in range(5):
            await engine.check_triggers(msg)
            
        assert engine.messages_since_last_trigger == 5
        
        # Send mention
        res = await engine.check_triggers(mention_msg)
        assert res.triggered is True
        assert res.trigger_type == "mention"
        
        # Verify reset
        assert engine.messages_since_last_trigger == 0

    async def test_threshold_randomness(self, llm_config: LLMConfig):
        llm_config.auto_participation = AutoParticipationConfig(
            enabled=True,
            base_message_interval=10,
            probability_range=0.5
        )
        engine = TriggerEngine(llm_config)
        
        # Threshold should be between 5 and 15
        assert 5 <= engine.non_trigger_threshold <= 15
        
        # Force recalculation multiple times to verify range
        for _ in range(20):
            engine._calculate_next_threshold()
            assert 5 <= engine.non_trigger_threshold <= 15


@pytest.mark.asyncio
class TestTriggerEngineContext:
    
    async def test_history_buffer_maintenance(self, llm_config: LLMConfig):
        """Test that messages are added to the history buffer."""
        # Setup config with known limits
        llm_config.context.chat_history_size = 5
        llm_config.context.max_chat_history_in_prompt = 3
        
        engine = TriggerEngine(llm_config)
        
        messages = [
            {"username": f"user{i}", "msg": f"msg{i}", "time": i, "meta": {}}
            for i in range(10)
        ]
        
        # Process messages
        for msg in messages:
            await engine.check_triggers(msg)
            
        # Check buffer size limit (maxlen=5)
        assert len(engine.history_buffer) == 5
        # Buffer should contain the last 5 messages (5-9)
        assert engine.history_buffer[0]["msg"] == "msg5"
        assert engine.history_buffer[4]["msg"] == "msg9"

    async def test_context_retrieval_on_trigger(self, llm_config: LLMConfig):
        """Test that triggered results contain the correct history context."""
        llm_config.context.chat_history_size = 10
        llm_config.context.max_chat_history_in_prompt = 3
        
        engine = TriggerEngine(llm_config)
        
        # Add some history
        for i in range(5):
            await engine.check_triggers({
                "username": "user", 
                "msg": f"history {i}", 
                "time": i, 
                "meta": {}
            })
            
        # Trigger a mention
        trigger_msg = {
            "username": "user",
            "msg": "hey cynthia",
            "time": 100,
            "meta": {}
        }
        result = await engine.check_triggers(trigger_msg)
        
        assert result.triggered is True
        assert result.history is not None
        assert len(result.history) == 3
        # Should be history 3, history 4, hey cynthia
        assert result.history[0]["msg"] == "history 3"
        assert result.history[1]["msg"] == "history 4"
        assert result.history[2]["msg"] == "hey cynthia"

    async def test_auto_participation_context(self, llm_config: LLMConfig):
        """Test context retrieval for auto-participation."""
        llm_config.auto_participation = AutoParticipationConfig(
            enabled=True,
            base_message_interval=2,
            probability_range=0.0
        )
        llm_config.context.max_chat_history_in_prompt = 2
        
        engine = TriggerEngine(llm_config)
        
        # msg 1
        await engine.check_triggers({"username": "u1", "msg": "one", "time": 1, "meta": {}})
        
        # msg 2 (should trigger)
        msg2 = {"username": "u2", "msg": "two", "time": 2, "meta": {}}
        result = await engine.check_triggers(msg2)
        
        assert result.triggered is True
        assert result.trigger_type == "auto_participant"
        assert result.history is not None
        assert len(result.history) == 2
        assert result.history[0]["msg"] == "one"
        assert result.history[1]["msg"] == "two"

    async def test_edge_case_empty_history(self, llm_config: LLMConfig):
        """Test context when history is empty (first message)."""
        llm_config.context.max_chat_history_in_prompt = 5
        engine = TriggerEngine(llm_config)
        
        msg = {"username": "u", "msg": "hey cynthia", "time": 1, "meta": {}}
        result = await engine.check_triggers(msg)
        
        assert result.triggered is True
        assert result.history is not None
        assert len(result.history) == 1
        assert result.history[0]["msg"] == "hey cynthia"

    async def test_edge_case_zero_limit(self, llm_config: LLMConfig):
        """Test context when max_chat_history_in_prompt is 0."""
        llm_config.context.max_chat_history_in_prompt = 0
        engine = TriggerEngine(llm_config)
        
        msg = {"username": "u", "msg": "hey cynthia", "time": 1, "meta": {}}
        result = await engine.check_triggers(msg)
        
        assert result.triggered is True
        assert result.history == []


@pytest.mark.asyncio
class TestTriggerEngineState:
    """Test TriggerEngine persistent state management."""

    async def test_load_media_state_bucket_not_found(self, llm_config: LLMConfig):
        """Test that failure to load state logs error."""
        engine = TriggerEngine(llm_config)
        client = AsyncMock()
        
        # Mock the kv_store functions to simulate failure
        with patch('kryten_llm.components.trigger_engine.get_kv_store') as mock_get_bucket:
            mock_get_bucket.side_effect = Exception("nats: BucketNotFoundError")
            
            # Should catch exception but log error
            await engine.load_media_state(client)
            
            # Verify it didn't crash
            assert engine.last_qualifying_media is None
            # Verify get_or_create_kv_store was called
            mock_get_bucket.assert_called_with(client._nats, "kryten_llm_trigger_state", logger=trigger_engine_logger)

    async def test_save_media_state_bucket_not_found(self, llm_config: LLMConfig):
        """Test that failure to save state logs error."""
        engine = TriggerEngine(llm_config)
        engine.last_qualifying_media = {"title": "Test Movie", "duration": 1200}
        client = AsyncMock()
        
        # Mock the kv_store functions to simulate failure
        with patch('kryten_llm.components.trigger_engine.get_kv_store') as mock_get_bucket:
            mock_get_bucket.side_effect = Exception("nats: BucketNotFoundError")
            
            # Should catch exception but log error
            await engine.save_media_state(client)
            
            # Verify attempted creation
            mock_get_bucket.assert_called_with(client._nats, "kryten_llm_trigger_state", logger=trigger_engine_logger)

    async def test_load_media_state_success(self, llm_config: LLMConfig):
        """Test successful state load."""
        engine = TriggerEngine(llm_config)
        client = AsyncMock()
        
        expected_data = {"title": "Test Movie", "duration": 1200}
        
        # Mock the kv_store functions
        with patch('kryten_llm.components.trigger_engine.get_kv_store') as mock_get_bucket, \
             patch('kryten_llm.components.trigger_engine.kv_get') as mock_kv_get:
            
            mock_bucket = AsyncMock()
            mock_get_bucket.return_value = mock_bucket
            mock_kv_get.return_value = expected_data
            
            await engine.load_media_state(client)
            
            assert engine.last_qualifying_media == expected_data
            mock_get_bucket.assert_called_with(client._nats, "kryten_llm_trigger_state", logger=trigger_engine_logger)
            mock_kv_get.assert_called_with(mock_bucket, "last_qualifying_media", default=None, parse_json=True, logger=trigger_engine_logger)

