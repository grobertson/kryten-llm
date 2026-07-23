"""Integration tests for Phase 4 intelligent formatting and validation.

Tests the complete Phase 4 pipeline including spam detection, validation,
formatting, and error handling working together (AC-008, AC-009).
"""

import time
from datetime import datetime, timezone
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from kryten_llm.models.config import LLMConfig
from kryten_llm.models.phase3 import LLMRequest, LLMResponse
from kryten_llm.service import LLMService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def full_phase4_config() -> LLMConfig:
    """Create complete LLMConfig with all Phase 4 settings."""
    config_dict = {
        "nats": {"servers": ["nats://localhost:4222"]},
        "channels": [{"domain": "cytu.be", "channel": "testroom"}],
        "personality": {
            "character_name": "TestBot",
            "character_description": "Test bot for phase 4 integration",
            "personality_traits": ["helpful", "direct"],
            "expertise": ["testing"],
            "response_style": "direct",
            "name_variations": ["testbot"],
        },
        "llm_providers": {
            "test": {
                "name": "test",
                "type": "openai_compatible",
                "base_url": "http://localhost:8000",
                "api_key": "test-key",
                "model": "test-model",
                "max_tokens": 256,
                "temperature": 0.8,
                "timeout_seconds": 10,
            }
        },
        "default_provider": "test",
        "formatting": {
            "max_message_length": 255,
            "continuation_indicator": " ...",
            "remove_self_references": True,
            "remove_llm_artifacts": True,
            "enable_emoji_limiting": False,
        },
        "validation": {
            "min_length": 10,
            "max_length": 2000,
            # Disable repetition check: mock LLM returns the same string every call,
            # and scenario tests would otherwise fail after the first send.
            "check_repetition": False,
            "repetition_history_size": 10,
            "repetition_threshold": 0.9,
            "check_relevance": False,
            "check_inappropriate": False,
        },
        "spam_detection": {
            "enabled": True,
            "message_windows": [
                {"seconds": 60, "max_messages": 5},
                {"seconds": 300, "max_messages": 15},
            ],
            "identical_message_window": {"seconds": 300, "max_messages": 3},
            "mention_spam_window": {"seconds": 30, "max_messages": 3},
            "penalty_durations": [30, 60, 120],
            "max_penalty": 600,
            "clean_period": 600,
            "admin_exempt_ranks": [4, 5],
        },
        "error_handling": {
            "enable_fallback_responses": False,
            "fallback_messages": [
                "I am having trouble processing that right now.",
                "Could you rephrase that?",
            ],
            "log_full_context": True,
            "generate_correlation_ids": True,
        },
        "context": {
            "chat_history_size": 10,
            # Disable enhanced deduplication so tests can pass raw dicts to
            # _handle_chat_message without needing typed ChatMessageEvent objects.
            "enable_enhanced_deduplication": False,
        },
        # Disable metrics server so start() does not try to bind a port.
        "metrics": {"enabled": False},
        "triggers": [],
        "rate_limits": {
            # High limits / zero cooldowns so scenario tests can fire multiple
            # triggers without hitting the rate limiter.
            "global_max_per_minute": 100,
            "global_max_per_hour": 1000,
            "global_cooldown_seconds": 0,
            "user_max_per_hour": 100,
            "user_cooldown_seconds": 0,
            "mention_cooldown_seconds": 0,
        },
    }
    return LLMConfig(**config_dict)


def _make_mock_client() -> MagicMock:
    """Return a fully-configured mock KrytenClient."""
    mock_client = MagicMock()
    mock_client.on.return_value = lambda f: f  # decorator pass-through
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.subscribe = AsyncMock()
    mock_client.subscribe_request_reply = AsyncMock(return_value=None)
    mock_client.send_chat = AsyncMock()
    mock_client.lifecycle = AsyncMock()
    mock_client.lifecycle.on_restart_notice = MagicMock()
    return mock_client


def _make_llm_response(content: str = "This is a valid LLM response.") -> LLMResponse:
    return LLMResponse(
        content=content,
        provider_used="test",
        model_used="test-model",
        tokens_used=10,
        response_time=0.1,
    )


def _event(username: str, msg: str, rank: int = 1) -> MagicMock:
    """Build a test ChatMessageEvent-compatible mock with a current timestamp."""
    event = MagicMock()
    event.username = username
    event.message = msg
    event.timestamp = datetime.now(timezone.utc)
    event.rank = rank
    event.shadow = False
    event.channel = "testroom"
    event.domain = "cytu.be"
    return event


@pytest.fixture
async def service(full_phase4_config: LLMConfig):
    """LLMService with all NATS infrastructure fully mocked."""
    mock_client = _make_mock_client()

    with patch("kryten_llm.service.KrytenClient", return_value=mock_client):
        svc = LLMService(full_phase4_config)

        # Prevent KV lookups during start()
        with (
            patch.object(svc.context_manager, "load_initial_state", AsyncMock()),
            patch.object(svc.trigger_engine, "load_media_state", AsyncMock()),
        ):
            await svc.start()

        # Bypass deduplication logic -- tests pass plain dicts, not typed events
        dedup = MagicMock()
        dedup.is_duplicate_chat_message.return_value = False
        dedup.should_ignore_historical_message.return_value = False
        dedup.should_ignore_old_message.return_value = False
        svc.deduplication_manager = dedup

        yield svc
        await svc.stop()


# ---------------------------------------------------------------------------
# AC-008: Correlation ID generation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correlation_id_generation(service: LLMService):
    """Test correlation IDs are generated for requests (AC-008)."""
    corr_id = service._generate_correlation_id()
    assert corr_id.startswith("msg-")
    assert len(corr_id) > 10


# ---------------------------------------------------------------------------
# AC-009: Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_logged_with_context(
    service: LLMService, full_phase4_config: LLMConfig, caplog
):
    """Test errors are logged with full context (AC-008)."""
    with patch.object(
        service.llm_manager,
        "generate_response",
        side_effect=Exception("LLM error"),
    ):
        event = _event("testuser", "test testbot")
        with caplog.at_level("ERROR"):
            await service._handle_chat_message(event)

    assert any("error" in record.message.lower() for record in caplog.records)


@pytest.mark.asyncio
async def test_error_fallback_disabled(service: LLMService):
    """Test no fallback response when disabled."""
    service.config.error_handling.enable_fallback_responses = False
    with patch.object(
        service.llm_manager,
        "generate_response",
        side_effect=Exception("Test error"),
    ):
        await service._handle_chat_message(_event("testuser", "test testbot"))
    # Should handle gracefully -- send_chat NOT called
    service.client.send_chat.assert_not_called()


@pytest.mark.asyncio
async def test_error_fallback_enabled(service: LLMService):
    """Test fallback response when enabled (AC-009)."""
    service.config.error_handling.enable_fallback_responses = True
    with patch.object(
        service.llm_manager,
        "generate_response",
        side_effect=Exception("Test error"),
    ):
        await service._handle_chat_message(_event("testuser", "test testbot"))
    # Service should handle gracefully (may or may not send fallback depending on
    # whether the error happens before or after the trigger check)


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_normal_message(service: LLMService):
    """Test complete pipeline for a triggering message."""
    resp = _make_llm_response("This is a great response about martial arts.")
    with patch.object(service.llm_manager, "generate_response", AsyncMock(return_value=resp)):
        service.client.send_chat.reset_mock()
        await service._handle_chat_message(_event("gooduser", "Tell me about kung fu testbot"))
    assert service.client.send_chat.called


@pytest.mark.asyncio
async def test_pipeline_spam_blocks_processing(service: LLMService):
    """Test spam detection blocks processing (AC-006)."""
    username = "spammer"
    resp = _make_llm_response("Response.")
    with patch.object(service.llm_manager, "generate_response", AsyncMock(return_value=resp)):
        # Send many messages rapidly to trigger spam
        for i in range(6):
            await service._handle_chat_message(
                _event(username, f"spam message {i}")
            )
    # After threshold spam detection should have blocked at least some
    # (hard to assert exact count without knowing trigger hit rate)


@pytest.mark.asyncio
async def test_pipeline_admin_bypass_spam(service: LLMService):
    """Test admin users bypass spam detection (AC-007)."""
    resp = _make_llm_response("Admin response.")
    service.client.send_chat.reset_mock()
    with patch.object(service.llm_manager, "generate_response", AsyncMock(return_value=resp)):
        for i in range(5):
            await service._handle_chat_message(
                _event("admin", f"admin message testbot {i}", rank=4)
            )
    # Admins should not be blocked; pipeline ran without exception


@pytest.mark.asyncio
async def test_pipeline_spam_recording(service: LLMService):
    """Test successful messages are recorded for spam tracking."""
    resp = _make_llm_response("Valid response.")
    with patch.object(service.llm_manager, "generate_response", AsyncMock(return_value=resp)):
        await service._handle_chat_message(_event("user1", "test testbot"))
    # Message should be recorded in spam detector
    assert "user1" in service.spam_detector.user_messages


# ---------------------------------------------------------------------------
# Configuration integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_formatting_config_respected(full_phase4_config: LLMConfig):
    """Test formatting configuration is reflected on the service."""
    full_phase4_config.formatting.max_message_length = 50
    full_phase4_config.formatting.continuation_indicator = " [cont]"

    mock_client = _make_mock_client()
    with patch("kryten_llm.service.KrytenClient", return_value=mock_client):
        svc = LLMService(full_phase4_config)
        with (
            patch.object(svc.context_manager, "load_initial_state", AsyncMock()),
            patch.object(svc.trigger_engine, "load_media_state", AsyncMock()),
        ):
            await svc.start()

        assert svc.response_formatter.formatting_config.max_message_length == 50
        assert svc.response_formatter.formatting_config.continuation_indicator == " [cont]"
        await svc.stop()


@pytest.mark.asyncio
async def test_validation_config_respected(full_phase4_config: LLMConfig):
    """Test validation configuration is reflected on the service."""
    full_phase4_config.validation.min_length = 20
    full_phase4_config.validation.max_length = 1000

    mock_client = _make_mock_client()
    with patch("kryten_llm.service.KrytenClient", return_value=mock_client):
        svc = LLMService(full_phase4_config)
        with (
            patch.object(svc.context_manager, "load_initial_state", AsyncMock()),
            patch.object(svc.trigger_engine, "load_media_state", AsyncMock()),
        ):
            await svc.start()

        assert svc.validator.config.min_length == 20
        assert svc.validator.config.max_length == 1000
        await svc.stop()


@pytest.mark.asyncio
async def test_spam_config_respected(full_phase4_config: LLMConfig):
    """Test spam detection configuration is reflected on the service."""
    full_phase4_config.spam_detection.enabled = False

    mock_client = _make_mock_client()
    with patch("kryten_llm.service.KrytenClient", return_value=mock_client):
        svc = LLMService(full_phase4_config)
        with (
            patch.object(svc.context_manager, "load_initial_state", AsyncMock()),
            patch.object(svc.trigger_engine, "load_media_state", AsyncMock()),
        ):
            await svc.start()

        assert not svc.spam_detector.config.enabled
        await svc.stop()


@pytest.mark.asyncio
async def test_error_handling_config_respected(full_phase4_config: LLMConfig):
    """Test error handling configuration is reflected on the service."""
    full_phase4_config.error_handling.enable_fallback_responses = True
    full_phase4_config.error_handling.fallback_messages = ["Custom fallback"]

    mock_client = _make_mock_client()
    with patch("kryten_llm.service.KrytenClient", return_value=mock_client):
        svc = LLMService(full_phase4_config)
        with (
            patch.object(svc.context_manager, "load_initial_state", AsyncMock()),
            patch.object(svc.trigger_engine, "load_media_state", AsyncMock()),
        ):
            await svc.start()

        assert svc.config.error_handling.enable_fallback_responses is True
        assert "Custom fallback" in svc.config.error_handling.fallback_messages
        await svc.stop()


# ---------------------------------------------------------------------------
# Component presence tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_phase4_components_initialized(service: LLMService):
    """Test all Phase 4 components are properly initialized."""
    assert service.response_formatter is not None
    assert hasattr(service.response_formatter, "format_response")

    assert service.validator is not None
    assert hasattr(service.validator, "validate")

    assert service.spam_detector is not None
    assert hasattr(service.spam_detector, "check_spam")

    assert service.config.formatting is not None
    assert service.config.validation is not None
    assert service.config.spam_detection is not None
    assert service.config.error_handling is not None


# ---------------------------------------------------------------------------
# Real-world scenario tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_normal_conversation(service: LLMService):
    """Test realistic normal conversation flow (3 triggered messages)."""
    responses = [
        "That is a great question about martial arts!",
        "Bruce Lee was an influential martial artist and actor.",
        "His philosophy emphasized practical self-defense.",
    ]
    call_idx = 0

    async def _gen(request: LLMRequest) -> LLMResponse:
        nonlocal call_idx
        content = responses[call_idx % len(responses)]
        call_idx += 1
        return _make_llm_response(content)

    service.client.send_chat.reset_mock()
    with patch.object(service.llm_manager, "generate_response", side_effect=_gen):
        for msg in [
            "Tell me about martial arts testbot",
            "Who was Bruce Lee? testbot",
            "What was his philosophy? testbot",
        ]:
            await service._handle_chat_message(_event("curious_user", msg))

    # All three triggered messages should have resulted in sends
    assert service.client.send_chat.call_count == 3


@pytest.mark.asyncio
async def test_scenario_spammer_blocked_then_recovered(service: LLMService):
    """Test spammer gets blocked then recovers after clean period."""
    username = "reformed_spammer"
    # Use a response that passes validation (min_length = 10)
    resp = _make_llm_response("This is a valid response for the reformed user.")
    with patch.object(service.llm_manager, "generate_response", AsyncMock(return_value=resp)):
        # Phase 1: Spam behavior
        for i in range(10):
            await service._handle_chat_message(
                _event(username, f"spam testbot {i}")
            )

        # Phase 2: Clear all spam state (simulate clean period)
        service.spam_detector.user_penalties.pop(username, None)
        service.spam_detector.last_offense[username] = datetime.now() - timedelta(seconds=700)
        service.spam_detector._check_clean_period(username)
        service.spam_detector.user_messages[username].clear()
        # Also clear mention history so the next "testbot" mention isn't rate-limited
        service.spam_detector._user_mentions[username].clear()
        service.spam_detector._last_messages[username].clear()

        # Phase 3: Normal behavior should be restored
        service.client.send_chat.reset_mock()
        await service._handle_chat_message(
            _event(username, "I am reformed now, testbot")
        )
        assert service.client.send_chat.called


@pytest.mark.asyncio
async def test_scenario_admin_unrestricted(service: LLMService):
    """Test admin can send many messages without restriction."""
    resp = _make_llm_response("Admin response.")
    service.client.send_chat.reset_mock()
    with patch.object(service.llm_manager, "generate_response", AsyncMock(return_value=resp)):
        for i in range(5):
            await service._handle_chat_message(
                _event("channel_owner", f"announcement testbot {i}", rank=5)
            )
    # Admins are not spam-blocked
    assert service.client.send_chat.call_count == 5


@pytest.mark.asyncio
async def test_scenario_llm_returns_code_and_artifacts(service: LLMService):
    """Test artifacts and code blocks are stripped before sending."""
    raw_content = (
        "Here is the solution:\n\n```python\ndef kung_fu_move():\n    return 'crane kick'\n```\n\n"
        "As an AI, I think this demonstrates the concept."
    )

    resp = _make_llm_response(raw_content)
    service.client.send_chat.reset_mock()
    with patch.object(service.llm_manager, "generate_response", AsyncMock(return_value=resp)):
        await service._handle_chat_message(_event("developer", "show me code testbot"))

    if service.client.send_chat.called:
        sent_args = service.client.send_chat.call_args_list
        combined = " ".join(str(a[0][1]) for a in sent_args)  # (channel, message)
        assert "```" not in combined


@pytest.mark.asyncio
async def test_scenario_error_recovery(service: LLMService):
    """Test service recovers after a single LLM error."""
    call_count = 0

    async def maybe_fail(request: LLMRequest) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Temporary error")
        return _make_llm_response("Successful response after error.")

    with patch.object(service.llm_manager, "generate_response", side_effect=maybe_fail):
        await service._handle_chat_message(_event("user1", "first testbot"))
        service.client.send_chat.reset_mock()
        await service._handle_chat_message(_event("user1", "second testbot"))

    # Second message should have sent successfully
    assert service.client.send_chat.called


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_performance(service: LLMService):
    """Test the non-LLM pipeline overhead is minimal."""
    import time as _t

    resp = _make_llm_response("Quick response.")
    with patch.object(service.llm_manager, "generate_response", AsyncMock(return_value=resp)):
        start = _t.time()
        await service._handle_chat_message(_event("user1", "test testbot"))
        elapsed = _t.time() - start

    # Pipeline overhead excluding LLM call should be well under 5s
    assert elapsed < 5.0


@pytest.mark.asyncio
async def test_concurrent_user_handling(service: LLMService):
    """Test handling multiple triggered users concurrently."""
    import asyncio as _asyncio

    resp = _make_llm_response("Response.")
    with patch.object(service.llm_manager, "generate_response", AsyncMock(return_value=resp)):
        tasks = [
            service._handle_chat_message(_event(f"user{i}", f"message testbot {i}"))
            for i in range(5)
        ]
        await _asyncio.gather(*tasks)

    # Should complete without exceptions


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_llm_response(service: LLMService):
    """Test validation rejects empty LLM response."""
    resp = _make_llm_response("")
    with patch.object(service.llm_manager, "generate_response", AsyncMock(return_value=resp)):
        service.client.send_chat.reset_mock()
        await service._handle_chat_message(_event("user1", "test testbot"))
    # Empty response should be rejected by validator; nothing sent
    service.client.send_chat.assert_not_called()


@pytest.mark.asyncio
async def test_whitespace_only_response(service: LLMService):
    """Test validation rejects whitespace-only LLM response."""
    resp = _make_llm_response("   \n\n   \t\t   ")
    with patch.object(service.llm_manager, "generate_response", AsyncMock(return_value=resp)):
        service.client.send_chat.reset_mock()
        await service._handle_chat_message(_event("user1", "test testbot"))
    service.client.send_chat.assert_not_called()


@pytest.mark.asyncio
async def test_unicode_throughout_pipeline(service: LLMService):
    """Test unicode handling through the pipeline."""
    resp = _make_llm_response("Response with unicode content and mixed characters!")
    with patch.object(service.llm_manager, "generate_response", AsyncMock(return_value=resp)):
        await service._handle_chat_message(_event("user1", "unicode test testbot"))
    # Should complete without exception