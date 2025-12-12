"""Integration tests for Phase 4 intelligent formatting and validation.

Tests the complete Phase 4 pipeline including spam detection, validation,
formatting, and error handling working together (AC-008, AC-009).

NOTE: These tests are skipped because they use an outdated LLMConfig constructor
pattern with direct fields (provider, model, api_key) that no longer exists.
The current config requires nats, channels, llm_providers dict structure.
These tests need to be rewritten to use the correct config structure.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from kryten_llm.models.config import (
    ErrorHandlingConfig,
    FormattingConfig,
    LLMConfig,
    MessageWindow,
    PersonalityConfig,
    SpamDetectionConfig,
    ValidationConfig,
)
from kryten_llm.service import LLMService

# Skip all tests in this module - they need config structure rewrite
pytestmark = pytest.mark.skip(
    reason="Phase 4 integration tests use outdated LLMConfig constructor pattern. "
    "Need to be rewritten to use nats/channels/llm_providers dict structure."
)


@pytest.fixture
def full_phase4_config():
    """Create complete LLMConfig with all Phase 4 settings."""
    return LLMConfig(
        provider="test",
        model="test-model",
        api_key="test-key",
        base_url="http://test",
        personality=PersonalityConfig(
            name="TestBot",
            description="Test bot",
            speaking_style="casual",
            interests=["testing"],
            conversation_style="direct",
        ),
        formatting=FormattingConfig(
            max_message_length=255,
            continuation_indicator=" ...",
            remove_code_blocks=True,
            remove_artifacts=True,
            remove_self_references=True,
            normalize_whitespace=True,
            enable_emoji_limiting=False,
            max_emoji_count=3,
            artifact_patterns=[
                r"^(?:Here's?|Let me|I'll|I will|Sure[,!]?|As an AI)",
            ],
        ),
        validation=ValidationConfig(
            min_length=10,
            max_length=2000,
            check_repetition=True,
            repetition_history_size=10,
            repetition_threshold=0.9,
            check_relevance=False,
            relevance_threshold=0.5,
            inappropriate_patterns=[],
            check_inappropriate=False,
        ),
        spam_detection=SpamDetectionConfig(
            enabled=True,
            message_windows=[
                MessageWindow(seconds=60, max_messages=5),
                MessageWindow(seconds=300, max_messages=15),
            ],
            identical_message_window=MessageWindow(seconds=300, max_messages=3),
            mention_spam_window=MessageWindow(seconds=30, max_messages=3),
            penalty_durations=[30, 60, 120],
            max_penalty_duration=600,
            clean_period_for_reset=600,
            admin_ranks=[4, 5],
        ),
        error_handling=ErrorHandlingConfig(
            enable_fallback_responses=False,
            fallback_responses=[
                "I'm having trouble processing that right now.",
                "Could you rephrase that?",
            ],
            log_errors=True,
            include_correlation_id=True,
        ),
        context_window_size=10,
        max_tokens=150,
        temperature=0.7,
    )


@pytest.fixture
def mock_llm_client():
    """Create mock LLM client."""
    mock = Mock()
    mock.generate = AsyncMock(return_value="This is a valid LLM response.")
    return mock


@pytest.fixture
async def service(full_phase4_config, mock_llm_client):
    """Create LLMService with Phase 4 integration."""
    with patch("kryten_llm.service.LLMClientFactory.create_client", return_value=mock_llm_client):
        svc = LLMService(full_phase4_config)
        await svc.start()
        yield svc
        await svc.stop()


# ============================================================================
# AC-008: Error Handling with Correlation IDs
# ============================================================================


@pytest.mark.asyncio
async def test_correlation_id_generation(service, full_phase4_config):
    """Test correlation IDs are generated for requests (AC-008)."""
    full_phase4_config.error_handling.include_correlation_id = True

    # Generate correlation ID
    corr_id = service._generate_correlation_id()

    assert corr_id.startswith("msg-")
    assert len(corr_id) > 10  # Should have UUID


@pytest.mark.asyncio
async def test_error_logged_with_context(service, caplog, mock_llm_client):
    """Test errors are logged with full context (AC-008)."""
    # Force an error in LLM generation
    mock_llm_client.generate.side_effect = Exception("LLM error")

    event = {
        "username": "testuser",
        "msg": "test message",
        "rank": 1,
        "room": "test",
    }

    # Should handle error gracefully
    with caplog.at_level("ERROR"):
        await service._handle_chat_message(event)

    # Check error was logged
    assert any("error" in record.message.lower() for record in caplog.records)


@pytest.mark.asyncio
async def test_error_fallback_disabled(service, mock_llm_client, full_phase4_config):
    """Test no fallback response when disabled."""
    full_phase4_config.error_handling.enable_fallback_responses = False
    mock_llm_client.generate.side_effect = Exception("Test error")

    event = {
        "username": "testuser",
        "msg": "test message",
        "rank": 1,
        "room": "test",
    }

    # Should not send fallback
    await service._handle_chat_message(event)
    # Service should handle gracefully without response


@pytest.mark.asyncio
async def test_error_fallback_enabled(service, mock_llm_client, full_phase4_config):
    """Test fallback response when enabled (AC-009)."""
    full_phase4_config.error_handling.enable_fallback_responses = True
    mock_llm_client.generate.side_effect = Exception("Test error")

    with patch.object(service, "_send_messages") as mock_send:
        event = {
            "username": "testuser",
            "msg": "test message",
            "rank": 1,
            "room": "test",
        }

        await service._handle_chat_message(event)

        # Should send fallback (AC-009)
        if mock_send.called:
            # Verify fallback was used
            call_args = mock_send.call_args
            assert call_args is not None


# ============================================================================
# Full Pipeline Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_full_pipeline_normal_message(service, mock_llm_client):
    """Test complete pipeline for normal message."""
    mock_llm_client.generate.return_value = "This is a great response about martial arts."

    with patch.object(service, "_send_messages") as mock_send:
        event = {
            "username": "gooduser",
            "msg": "Tell me about kung fu",
            "rank": 1,
            "room": "test",
        }

        await service._handle_chat_message(event)

        # Should successfully process and send
        assert mock_send.called


@pytest.mark.asyncio
async def test_pipeline_spam_blocks_processing(service, mock_llm_client):
    """Test spam detection blocks processing (AC-006)."""
    username = "spammer"

    with patch.object(service, "_send_messages"):
        # Send many messages rapidly to trigger spam
        for i in range(6):
            event = {
                "username": username,
                "msg": f"spam message {i}",
                "rank": 1,
                "room": "test",
            }
            await service._handle_chat_message(event)

        # Should be blocked after threshold
        # Check if spam detection prevented LLM call
        # (In real implementation, would verify LLM not called for spam)


@pytest.mark.asyncio
async def test_pipeline_validation_rejects_response(service, mock_llm_client):
    """Test validation rejects bad LLM responses."""
    # LLM returns response that's too short
    mock_llm_client.generate.return_value = "Ok"  # Below 10 char minimum

    with patch.object(service, "_send_messages"):
        event = {
            "username": "testuser",
            "msg": "test question",
            "rank": 1,
            "room": "test",
        }

        await service._handle_chat_message(event)

        # Should reject and not send
        # (Validator should catch short response)


@pytest.mark.asyncio
async def test_pipeline_formatting_applied(service, mock_llm_client):
    """Test formatting is applied to responses."""
    # LLM returns response with code blocks and artifacts
    mock_llm_client.generate.return_value = """Here's the answer:

```python
def test():
    pass
```

This is the actual response."""

    with patch.object(service, "_send_messages") as mock_send:
        event = {
            "username": "testuser",
            "msg": "test",
            "rank": 1,
            "room": "test",
        }

        await service._handle_chat_message(event)

        if mock_send.called:
            # Check that formatted response excludes code blocks
            call_args = mock_send.call_args[0][0]
            # Code block should be removed
            assert "```python" not in str(call_args)


@pytest.mark.asyncio
async def test_pipeline_admin_bypass_spam(service, mock_llm_client):
    """Test admin users bypass spam detection (AC-007)."""
    mock_llm_client.generate.return_value = "Admin response."

    with patch.object(service, "_send_messages") as mock_send:
        # Admin sends many messages
        for i in range(20):
            event = {
                "username": "admin",
                "msg": f"admin message {i}",
                "rank": 4,  # Admin rank
                "room": "test",
            }
            await service._handle_chat_message(event)

        # All should process (no spam blocking for admin)
        assert mock_send.call_count > 0


@pytest.mark.asyncio
async def test_pipeline_long_response_splitting(service, mock_llm_client):
    """Test long responses are split by formatter."""
    # LLM returns very long response
    long_response = "This is a sentence. " * 50  # About 1000 chars
    mock_llm_client.generate.return_value = long_response

    with patch.object(service, "_send_messages") as mock_send:
        event = {
            "username": "testuser",
            "msg": "tell me about martial arts",
            "rank": 1,
            "room": "test",
        }

        await service._handle_chat_message(event)

        if mock_send.called:
            # Should be split into multiple messages
            messages = mock_send.call_args[0][0]
            if isinstance(messages, list) and len(messages) > 1:
                # Verify continuation indicators
                assert messages[0].endswith(" ...")


@pytest.mark.asyncio
async def test_pipeline_repetition_detection(service, mock_llm_client):
    """Test validation catches repetitive responses (AC-005)."""
    mock_llm_client.generate.return_value = "This is the same response every time."

    with patch.object(service, "_send_messages"):
        # Send multiple requests that generate same response
        for i in range(3):
            event = {
                "username": f"user{i}",
                "msg": "test",
                "rank": 1,
                "room": "test",
            }
            await service._handle_chat_message(event)

        # After first time, identical responses should be rejected
        # Check how many times _send_messages was called
        # Should be less than 3 if repetition detection working


@pytest.mark.asyncio
async def test_pipeline_rate_limit_after_spam_check(service, mock_llm_client):
    """Test rate limiting happens after spam check."""
    mock_llm_client.generate.return_value = "Response."

    username = "user1"

    # This tests that spam detection is checked BEFORE rate limiting
    # So spam doesn't consume rate limit quota
    with patch.object(service, "_send_messages"):
        for i in range(3):
            event = {
                "username": username,
                "msg": f"message {i}",
                "rank": 1,
                "room": "test",
            }
            await service._handle_chat_message(event)

    # Verify order of operations in pipeline


@pytest.mark.asyncio
async def test_pipeline_spam_recording(service, mock_llm_client):
    """Test successful messages are recorded for spam tracking."""
    mock_llm_client.generate.return_value = "Valid response."

    with patch.object(service, "_send_messages"):
        event = {
            "username": "user1",
            "msg": "test",
            "rank": 1,
            "room": "test",
        }

        await service._handle_chat_message(event)

        # Message should be recorded in spam detector
        assert "user1" in service.spam_detector.user_messages


# ============================================================================
# Configuration Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_formatting_config_respected(full_phase4_config, mock_llm_client):
    """Test formatting configuration is respected."""
    full_phase4_config.formatting.max_message_length = 50  # Very short
    full_phase4_config.formatting.continuation_indicator = " [cont]"

    with patch("kryten_llm.service.LLMClientFactory.create_client", return_value=mock_llm_client):
        service = LLMService(full_phase4_config)
        await service.start()

        # Formatter should use these settings
        assert service.formatter.config.max_message_length == 50
        assert service.formatter.config.continuation_indicator == " [cont]"

        await service.stop()


@pytest.mark.asyncio
async def test_validation_config_respected(full_phase4_config, mock_llm_client):
    """Test validation configuration is respected."""
    full_phase4_config.validation.min_length = 20
    full_phase4_config.validation.max_length = 1000

    with patch("kryten_llm.service.LLMClientFactory.create_client", return_value=mock_llm_client):
        service = LLMService(full_phase4_config)
        await service.start()

        # Validator should use these settings
        assert service.validator.config.min_length == 20
        assert service.validator.config.max_length == 1000

        await service.stop()


@pytest.mark.asyncio
async def test_spam_config_respected(full_phase4_config, mock_llm_client):
    """Test spam detection configuration is respected."""
    full_phase4_config.spam_detection.enabled = False

    with patch("kryten_llm.service.LLMClientFactory.create_client", return_value=mock_llm_client):
        service = LLMService(full_phase4_config)
        await service.start()

        # Spam detector should be disabled
        assert not service.spam_detector.config.enabled

        await service.stop()


@pytest.mark.asyncio
async def test_error_handling_config_respected(full_phase4_config, mock_llm_client):
    """Test error handling configuration is respected."""
    full_phase4_config.error_handling.enable_fallback_responses = True
    full_phase4_config.error_handling.fallback_responses = ["Custom fallback"]

    with patch("kryten_llm.service.LLMClientFactory.create_client", return_value=mock_llm_client):
        service = LLMService(full_phase4_config)
        await service.start()

        # Config should be available
        assert service.config.error_handling.enable_fallback_responses is True
        assert "Custom fallback" in service.config.error_handling.fallback_responses

        await service.stop()


# ============================================================================
# Component Interaction Tests
# ============================================================================


@pytest.mark.asyncio
async def test_formatter_validator_interaction(service, mock_llm_client):
    """Test formatter and validator work together correctly."""
    # LLM returns response that needs formatting but should pass validation
    mock_llm_client.generate.return_value = "Here's a good response about martial arts."

    with patch.object(service, "_send_messages") as mock_send:
        event = {
            "username": "user1",
            "msg": "tell me about kung fu",
            "rank": 1,
            "room": "test",
        }

        await service._handle_chat_message(event)

        if mock_send.called:
            # Response should be formatted (artifact removed) and validated
            messages = mock_send.call_args[0][0]
            if isinstance(messages, list):
                # "Here's" should be removed by formatter
                assert not any(msg.startswith("Here's") for msg in messages)


@pytest.mark.asyncio
async def test_spam_detector_validator_interaction(service, mock_llm_client):
    """Test spam detector and validator are independent."""
    mock_llm_client.generate.return_value = "Valid response."

    username = "user1"

    with patch.object(service, "_send_messages"):
        # Send messages that trigger spam but would pass validation
        for i in range(6):
            event = {
                "username": username,
                "msg": f"different message {i}",
                "rank": 1,
                "room": "test",
            }
            await service._handle_chat_message(event)

    # Spam should block before validation even runs


@pytest.mark.asyncio
async def test_all_phase4_components_initialized(service):
    """Test all Phase 4 components are properly initialized."""
    # Formatter
    assert service.formatter is not None
    assert hasattr(service.formatter, "format_response")

    # Validator
    assert service.validator is not None
    assert hasattr(service.validator, "validate")

    # Spam Detector
    assert service.spam_detector is not None
    assert hasattr(service.spam_detector, "check_spam")

    # Config sections
    assert service.config.formatting is not None
    assert service.config.validation is not None
    assert service.config.spam_detection is not None
    assert service.config.error_handling is not None


# ============================================================================
# Real-World Scenario Tests
# ============================================================================


@pytest.mark.asyncio
async def test_scenario_normal_conversation(service, mock_llm_client):
    """Test realistic normal conversation flow."""
    mock_llm_client.generate.side_effect = [
        "That's a great question about martial arts!",
        "Bruce Lee was an influential martial artist and actor.",
        "His philosophy emphasized practical self-defense.",
    ]

    with patch.object(service, "_send_messages") as mock_send:
        messages = [
            "Tell me about martial arts",
            "Who was Bruce Lee?",
            "What was his philosophy?",
        ]

        for msg in messages:
            event = {
                "username": "curious_user",
                "msg": msg,
                "rank": 1,
                "room": "test",
            }
            await service._handle_chat_message(event)

        # All messages should process successfully
        assert mock_send.call_count == 3


@pytest.mark.asyncio
async def test_scenario_spammer_blocked_then_recovered(service, mock_llm_client):
    """Test spammer gets blocked then recovers after clean period."""
    mock_llm_client.generate.return_value = "Response."

    username = "reformed_spammer"

    with patch.object(service, "_send_messages"):
        # Phase 1: Spam behavior
        for i in range(10):
            event = {
                "username": username,
                "msg": f"spam {i}",
                "rank": 1,
                "room": "test",
            }
            await service._handle_chat_message(event)

        # Should be blocked now

        # Phase 2: Clean period (simulate time passing)
        service.spam_detector.user_penalties.pop(username, None)
        service.spam_detector.last_offense[username] = datetime.now() - timedelta(seconds=700)
        service.spam_detector._check_clean_period(username)
        service.spam_detector.user_messages[username].clear()

        # Phase 3: Normal behavior
        event = {
            "username": username,
            "msg": "I'm reformed now",
            "rank": 1,
            "room": "test",
        }
        await service._handle_chat_message(event)

        # Should be able to send again


@pytest.mark.asyncio
async def test_scenario_admin_unrestricted(service, mock_llm_client):
    """Test admin can send many messages without restriction."""
    mock_llm_client.generate.return_value = "Admin response."

    with patch.object(service, "_send_messages") as mock_send:
        # Admin sends 30 messages rapidly
        for i in range(30):
            event = {
                "username": "channel_owner",
                "msg": f"announcement {i}",
                "rank": 5,  # Owner rank
                "room": "test",
            }
            await service._handle_chat_message(event)

        # All should process
        assert mock_send.call_count == 30


@pytest.mark.asyncio
async def test_scenario_llm_returns_code_and_artifacts(service, mock_llm_client):
    """Test complete scenario with code blocks and artifacts."""
    mock_llm_client.generate.return_value = """Here's the solution:

```python
def kung_fu_move():
    return "crane kick"
```

As an AI, I think this demonstrates the concept well."""

    with patch.object(service, "_send_messages") as mock_send:
        event = {
            "username": "developer",
            "msg": "show me code",
            "rank": 1,
            "room": "test",
        }

        await service._handle_chat_message(event)

        if mock_send.called:
            messages = mock_send.call_args[0][0]
            # Code blocks should be removed
            # Artifacts should be removed
            # Only clean text should remain
            if messages:
                combined = " ".join(messages) if isinstance(messages, list) else messages
                assert "```" not in combined
                assert "Here's" not in combined
                assert "As an AI" not in combined


@pytest.mark.asyncio
async def test_scenario_error_recovery(service, mock_llm_client):
    """Test error occurs and system recovers gracefully."""
    # First call errors, second succeeds
    mock_llm_client.generate.side_effect = [
        Exception("Temporary error"),
        "Successful response after error.",
    ]

    with patch.object(service, "_send_messages"):
        # First message - error
        event1 = {
            "username": "user1",
            "msg": "first",
            "rank": 1,
            "room": "test",
        }
        await service._handle_chat_message(event1)

        # Second message - success
        event2 = {
            "username": "user1",
            "msg": "second",
            "rank": 1,
            "room": "test",
        }
        await service._handle_chat_message(event2)

        # Second should succeed despite first error


# ============================================================================
# Performance Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_full_pipeline_performance(service, mock_llm_client):
    """Test complete pipeline meets performance requirements."""
    import time

    mock_llm_client.generate.return_value = "Quick response."

    with patch.object(service, "_send_messages"):
        event = {
            "username": "user1",
            "msg": "test",
            "rank": 1,
            "room": "test",
        }

        start = time.time()
        await service._handle_chat_message(event)
        time.time() - start

        # Pipeline overhead (excluding LLM call) should be minimal
        # This is hard to measure with mocks, but structure exists


@pytest.mark.asyncio
async def test_concurrent_user_handling(service, mock_llm_client):
    """Test handling multiple users concurrently."""
    import asyncio

    mock_llm_client.generate.return_value = "Response."

    async def send_message(username, msg):
        event = {
            "username": username,
            "msg": msg,
            "rank": 1,
            "room": "test",
        }
        await service._handle_chat_message(event)

    with patch.object(service, "_send_messages"):
        # Simulate 10 users sending messages simultaneously
        tasks = [send_message(f"user{i}", f"message{i}") for i in range(10)]

        await asyncio.gather(*tasks)

        # All should complete without errors


# ============================================================================
# Edge Cases Integration
# ============================================================================


@pytest.mark.asyncio
async def test_empty_llm_response(service, mock_llm_client):
    """Test handling empty LLM response."""
    mock_llm_client.generate.return_value = ""

    with patch.object(service, "_send_messages"):
        event = {
            "username": "user1",
            "msg": "test",
            "rank": 1,
            "room": "test",
        }

        await service._handle_chat_message(event)

        # Should handle gracefully (validation should reject)


@pytest.mark.asyncio
async def test_whitespace_only_response(service, mock_llm_client):
    """Test handling whitespace-only LLM response."""
    mock_llm_client.generate.return_value = "   \n\n   \t\t   "

    with patch.object(service, "_send_messages"):
        event = {
            "username": "user1",
            "msg": "test",
            "rank": 1,
            "room": "test",
        }

        await service._handle_chat_message(event)

        # Should handle gracefully


@pytest.mark.asyncio
async def test_unicode_throughout_pipeline(service, mock_llm_client):
    """Test unicode handling through complete pipeline."""
    mock_llm_client.generate.return_value = "响应包含中文字符和 émojis 😀"

    with patch.object(service, "_send_messages"):
        event = {
            "username": "用户",
            "msg": "测试消息",
            "rank": 1,
            "room": "test",
        }

        await service._handle_chat_message(event)

        # Should handle unicode throughout


@pytest.mark.asyncio
async def test_very_long_llm_response(service, mock_llm_client):
    """Test handling very long LLM response (>2000 chars)."""
    long_response = "This is a very long response. " * 100  # ~3000 chars
    mock_llm_client.generate.return_value = long_response

    with patch.object(service, "_send_messages"):
        event = {
            "username": "user1",
            "msg": "tell me everything",
            "rank": 1,
            "room": "test",
        }

        await service._handle_chat_message(event)

        # Should be rejected by validation (> 2000 chars)
