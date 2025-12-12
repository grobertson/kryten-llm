"""Unit tests for ResponseLogger component.

Tests JSONL logging functionality:
- Log entry structure and content
- File creation and directory handling
- Graceful error handling
- Log disable flag behavior
"""

import json
from unittest.mock import patch

import pytest

from kryten_llm.components import RateLimitDecision, ResponseLogger
from kryten_llm.models.events import TriggerResult


@pytest.mark.asyncio
class TestResponseLoggerBasic:
    """Test basic logging functionality."""

    def test_creates_log_directory(self, llm_config_with_triggers, tmp_path):
        """Should create log directory if it doesn't exist."""
        log_file = tmp_path / "logs" / "test-responses.jsonl"
        llm_config_with_triggers.testing.log_file = str(log_file)

        ResponseLogger(llm_config_with_triggers)

        assert log_file.parent.exists()
        assert log_file.parent.is_dir()

    async def test_log_response_creates_file(self, llm_config_with_triggers, tmp_path):
        """Should create log file on first write."""
        log_file = tmp_path / "logs" / "test-responses.jsonl"
        llm_config_with_triggers.testing.log_file = str(log_file)

        logger = ResponseLogger(llm_config_with_triggers)

        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context="",
        )

        rate_limit_decision = RateLimitDecision(
            allowed=True, reason="Allowed", retry_after=0, details={}
        )

        await logger.log_response(
            trigger_result=trigger_result,
            username="testuser",
            input_message="cynthia hello",
            llm_response="Hello there!",
            formatted_parts=["Hello there!"],
            rate_limit_decision=rate_limit_decision,
            sent=True,
        )

        assert log_file.exists()
        assert log_file.is_file()

    async def test_log_entry_structure(self, llm_config_with_triggers, tmp_path):
        """Should write valid JSONL with all required fields."""
        log_file = tmp_path / "logs" / "test-responses.jsonl"
        llm_config_with_triggers.testing.log_file = str(log_file)

        logger = ResponseLogger(llm_config_with_triggers)

        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="trigger_word",
            trigger_name="toddy",
            priority=8,
            cleaned_message="praise !",
            context="Respond enthusiastically about Robert Z'Dar",
        )

        rate_limit_decision = RateLimitDecision(
            allowed=True, reason="Allowed", retry_after=0, details={"global_count": 1}
        )

        await logger.log_response(
            trigger_result=trigger_result,
            username="testuser",
            input_message="praise toddy",
            llm_response="Robert Z'Dar is legendary!",
            formatted_parts=["Robert Z'Dar is legendary!"],
            rate_limit_decision=rate_limit_decision,
            sent=True,
        )

        # Read and parse JSONL
        with open(log_file, "r", encoding="utf-8") as f:
            line = f.readline()
            entry = json.loads(line)

        # Verify all required fields present
        assert "timestamp" in entry
        assert "trigger_type" in entry
        assert entry["trigger_type"] == "trigger_word"
        assert "trigger_name" in entry
        assert entry["trigger_name"] == "toddy"
        assert "trigger_priority" in entry
        assert entry["trigger_priority"] == 8
        assert "username" in entry
        assert entry["username"] == "testuser"
        assert "input_message" in entry
        assert entry["input_message"] == "praise toddy"
        assert "cleaned_message" in entry
        assert entry["cleaned_message"] == "praise !"
        assert "llm_response" in entry
        assert entry["llm_response"] == "Robert Z'Dar is legendary!"
        assert "formatted_parts" in entry
        assert entry["formatted_parts"] == ["Robert Z'Dar is legendary!"]
        assert "response_sent" in entry
        assert entry["response_sent"] is True
        assert "rate_limit" in entry
        assert isinstance(entry["rate_limit"], dict)
        assert entry["rate_limit"]["allowed"] is True

    async def test_multiple_entries_appended(self, llm_config_with_triggers, tmp_path):
        """Should append entries, not overwrite."""
        log_file = tmp_path / "logs" / "test-responses.jsonl"
        llm_config_with_triggers.testing.log_file = str(log_file)

        logger = ResponseLogger(llm_config_with_triggers)

        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context="",
        )

        rate_limit_decision = RateLimitDecision(
            allowed=True, reason="Allowed", retry_after=0, details={}
        )

        # Log first entry
        await logger.log_response(
            trigger_result=trigger_result,
            username="user1",
            input_message="cynthia hello",
            llm_response="Hello user1!",
            formatted_parts=["Hello user1!"],
            rate_limit_decision=rate_limit_decision,
            sent=True,
        )

        # Log second entry
        await logger.log_response(
            trigger_result=trigger_result,
            username="user2",
            input_message="cynthia hi",
            llm_response="Hi user2!",
            formatted_parts=["Hi user2!"],
            rate_limit_decision=rate_limit_decision,
            sent=True,
        )

        # Read both entries
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 2
        entry1 = json.loads(lines[0])
        entry2 = json.loads(lines[1])

        assert entry1["username"] == "user1"
        assert entry2["username"] == "user2"


@pytest.mark.asyncio
class TestResponseLoggerRateLimitScenarios:
    """Test logging with different rate limit scenarios."""

    async def test_log_blocked_response(self, llm_config_with_triggers, tmp_path):
        """Should log blocked responses with rate limit details."""
        log_file = tmp_path / "logs" / "test-responses.jsonl"
        llm_config_with_triggers.testing.log_file = str(log_file)

        logger = ResponseLogger(llm_config_with_triggers)

        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context="",
        )

        rate_limit_decision = RateLimitDecision(
            allowed=False,
            reason="Global per-minute limit reached",
            retry_after=45,
            details={"global_minute_count": 2, "limit": 2},
        )

        await logger.log_response(
            trigger_result=trigger_result,
            username="testuser",
            input_message="cynthia hello",
            llm_response="",  # Empty when blocked
            formatted_parts=[],
            rate_limit_decision=rate_limit_decision,
            sent=False,
        )

        # Read and verify
        with open(log_file, "r", encoding="utf-8") as f:
            entry = json.loads(f.readline())

        assert entry["response_sent"] is False
        assert entry["rate_limit"]["allowed"] is False
        assert entry["rate_limit"]["reason"] == "Global per-minute limit reached"
        assert entry["rate_limit"]["retry_after"] == 45
        assert "details" in entry["rate_limit"]

    async def test_log_with_empty_llm_response(self, llm_config_with_triggers, tmp_path):
        """Should handle empty LLM response (e.g., LLM failure)."""
        log_file = tmp_path / "logs" / "test-responses.jsonl"
        llm_config_with_triggers.testing.log_file = str(log_file)

        logger = ResponseLogger(llm_config_with_triggers)

        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context="",
        )

        rate_limit_decision = RateLimitDecision(
            allowed=True, reason="Allowed", retry_after=0, details={}
        )

        await logger.log_response(
            trigger_result=trigger_result,
            username="testuser",
            input_message="cynthia hello",
            llm_response="",  # LLM failed
            formatted_parts=[],
            rate_limit_decision=rate_limit_decision,
            sent=False,
        )

        # Read and verify
        with open(log_file, "r", encoding="utf-8") as f:
            entry = json.loads(f.readline())

        assert entry["llm_response"] == ""
        assert entry["formatted_parts"] == []
        assert entry["response_sent"] is False


@pytest.mark.asyncio
class TestResponseLoggerConfigFlags:
    """Test configuration flag behavior."""

    async def test_log_responses_disabled(self, llm_config_with_triggers, tmp_path):
        """Should not write to file when log_responses=False."""
        log_file = tmp_path / "logs" / "test-responses.jsonl"
        llm_config_with_triggers.testing.log_file = str(log_file)
        llm_config_with_triggers.testing.log_responses = False

        logger = ResponseLogger(llm_config_with_triggers)

        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context="",
        )

        rate_limit_decision = RateLimitDecision(
            allowed=True, reason="Allowed", retry_after=0, details={}
        )

        await logger.log_response(
            trigger_result=trigger_result,
            username="testuser",
            input_message="cynthia hello",
            llm_response="Hello!",
            formatted_parts=["Hello!"],
            rate_limit_decision=rate_limit_decision,
            sent=True,
        )

        # Log file should not be created
        assert not log_file.exists()

    async def test_log_responses_enabled_by_default(self, llm_config_with_triggers, tmp_path):
        """Should write to file when log_responses=True (default)."""
        log_file = tmp_path / "logs" / "test-responses.jsonl"
        llm_config_with_triggers.testing.log_file = str(log_file)
        llm_config_with_triggers.testing.log_responses = True

        logger = ResponseLogger(llm_config_with_triggers)

        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context="",
        )

        rate_limit_decision = RateLimitDecision(
            allowed=True, reason="Allowed", retry_after=0, details={}
        )

        await logger.log_response(
            trigger_result=trigger_result,
            username="testuser",
            input_message="cynthia hello",
            llm_response="Hello!",
            formatted_parts=["Hello!"],
            rate_limit_decision=rate_limit_decision,
            sent=True,
        )

        # Log file should be created
        assert log_file.exists()


@pytest.mark.asyncio
class TestResponseLoggerErrorHandling:
    """Test error handling and edge cases."""

    async def test_handles_file_write_error_gracefully(self, llm_config_with_triggers, tmp_path):
        """Should handle file I/O errors without crashing."""
        log_file = tmp_path / "logs" / "test-responses.jsonl"
        llm_config_with_triggers.testing.log_file = str(log_file)

        logger = ResponseLogger(llm_config_with_triggers)

        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context="",
        )

        rate_limit_decision = RateLimitDecision(
            allowed=True, reason="Allowed", retry_after=0, details={}
        )

        # Mock file open to raise exception
        with patch("builtins.open", side_effect=OSError("Disk full")):
            # Should not raise exception
            await logger.log_response(
                trigger_result=trigger_result,
                username="testuser",
                input_message="cynthia hello",
                llm_response="Hello!",
                formatted_parts=["Hello!"],
                rate_limit_decision=rate_limit_decision,
                sent=True,
            )

    async def test_handles_special_characters_in_messages(self, llm_config_with_triggers, tmp_path):
        """Should properly escape special characters in JSON."""
        log_file = tmp_path / "logs" / "test-responses.jsonl"
        llm_config_with_triggers.testing.log_file = str(log_file)

        logger = ResponseLogger(llm_config_with_triggers)

        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message='test "quotes" and \\backslashes\\',
            context="",
        )

        rate_limit_decision = RateLimitDecision(
            allowed=True, reason="Allowed", retry_after=0, details={}
        )

        await logger.log_response(
            trigger_result=trigger_result,
            username="testuser",
            input_message='cynthia test "quotes" and \\backslashes\\',
            llm_response='Response with "quotes" and \\backslashes\\',
            formatted_parts=['Response with "quotes" and \\backslashes\\'],
            rate_limit_decision=rate_limit_decision,
            sent=True,
        )

        # Should be valid JSON
        with open(log_file, "r", encoding="utf-8") as f:
            entry = json.loads(f.readline())

        assert '"quotes"' in entry["input_message"]
        assert "\\backslashes\\" in entry["input_message"]

    async def test_handles_unicode_in_messages(self, llm_config_with_triggers, tmp_path):
        """Should properly handle unicode characters."""
        log_file = tmp_path / "logs" / "test-responses.jsonl"
        llm_config_with_triggers.testing.log_file = str(log_file)

        logger = ResponseLogger(llm_config_with_triggers)

        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="test émojis 🎉🔥",
            context="",
        )

        rate_limit_decision = RateLimitDecision(
            allowed=True, reason="Allowed", retry_after=0, details={}
        )

        await logger.log_response(
            trigger_result=trigger_result,
            username="testuser",
            input_message="cynthia test émojis 🎉🔥",
            llm_response="Response with émojis 🎉🔥",
            formatted_parts=["Response with émojis 🎉🔥"],
            rate_limit_decision=rate_limit_decision,
            sent=True,
        )

        # Should be valid JSON with unicode preserved
        with open(log_file, "r", encoding="utf-8") as f:
            entry = json.loads(f.readline())

        assert "émojis" in entry["input_message"]
        assert "🎉" in entry["input_message"]

    async def test_handles_very_long_messages(self, llm_config_with_triggers, tmp_path):
        """Should handle very long messages without issues."""
        log_file = tmp_path / "logs" / "test-responses.jsonl"
        llm_config_with_triggers.testing.log_file = str(log_file)

        logger = ResponseLogger(llm_config_with_triggers)

        long_message = "x" * 10000

        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message=long_message,
            context="",
        )

        rate_limit_decision = RateLimitDecision(
            allowed=True, reason="Allowed", retry_after=0, details={}
        )

        await logger.log_response(
            trigger_result=trigger_result,
            username="testuser",
            input_message=long_message,
            llm_response=long_message,
            formatted_parts=[long_message],
            rate_limit_decision=rate_limit_decision,
            sent=True,
        )

        # Should be valid JSON
        with open(log_file, "r", encoding="utf-8") as f:
            entry = json.loads(f.readline())

        assert len(entry["input_message"]) == 10000


@pytest.mark.asyncio
class TestResponseLoggerTimestamp:
    """Test timestamp formatting."""

    async def test_timestamp_format(self, llm_config_with_triggers, tmp_path):
        """Should include ISO 8601 formatted timestamp."""
        log_file = tmp_path / "logs" / "test-responses.jsonl"
        llm_config_with_triggers.testing.log_file = str(log_file)

        logger = ResponseLogger(llm_config_with_triggers)

        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context="",
        )

        rate_limit_decision = RateLimitDecision(
            allowed=True, reason="Allowed", retry_after=0, details={}
        )

        await logger.log_response(
            trigger_result=trigger_result,
            username="testuser",
            input_message="cynthia hello",
            llm_response="Hello!",
            formatted_parts=["Hello!"],
            rate_limit_decision=rate_limit_decision,
            sent=True,
        )

        # Read and verify timestamp
        with open(log_file, "r", encoding="utf-8") as f:
            entry = json.loads(f.readline())

        # Should be parseable as ISO 8601
        from datetime import datetime

        timestamp = datetime.fromisoformat(entry["timestamp"])
        assert timestamp is not None
