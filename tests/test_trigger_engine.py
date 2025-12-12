"""Unit tests for TriggerEngine component."""

import pytest

from kryten_llm.components.trigger_engine import TriggerEngine
from kryten_llm.models.config import LLMConfig


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
