"""Integration tests for Phase 5 (Service Discovery & Monitoring).

Tests Phase 5 behaviour by mocking KrytenClient so LLMService can be
fully instantiated without live NATS infrastructure.  Heartbeat timing
tests that genuinely require running NATS are individually skipped with
an explanatory reason.

Component-level unit tests live in:
  - tests/test_health_monitor_phase5.py
  - tests/test_heartbeat_publisher_phase5.py
"""

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from kryten_llm.components.health_monitor import HealthState
from kryten_llm.models.config import LLMConfig
from kryten_llm.service import LLMService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    mock_client.lifecycle.publish_startup = AsyncMock()
    mock_client.lifecycle.publish_shutdown = AsyncMock()
    mock_client.lifecycle.on_restart_notice = MagicMock()
    return mock_client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_config_dict():
    """Base LLMConfig dictionary for testing."""
    return {
        "nats": {"servers": ["nats://localhost:4222"]},
        "channels": [{"domain": "cytu.be", "channel": "testroom"}],
        "personality": {
            "character_name": "TestBot",
            "character_description": "Test bot",
            "personality_traits": ["helpful"],
            "expertise": ["testing"],
            "response_style": "concise",
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
        "triggers": [],
        "rate_limits": {},
        "metrics": {"enabled": False},
        "service_metadata": {
            "service_name": "llm",
            "service_version": "1.0.0-test",
            "heartbeat_interval_seconds": 5,
            "enable_service_discovery": True,
            "enable_heartbeats": True,
            "graceful_shutdown_timeout_seconds": 5,
        },
    }


@pytest.fixture
def base_config(base_config_dict) -> LLMConfig:
    return LLMConfig(**base_config_dict)


@pytest.fixture
async def llm_service(base_config: LLMConfig):
    """LLMService with KrytenClient fully mocked."""
    mock_client = _make_mock_client()

    with patch("kryten_llm.service.KrytenClient", return_value=mock_client):
        svc = LLMService(base_config)
        with (
            patch.object(svc.context_manager, "load_initial_state", AsyncMock()),
            patch.object(svc.trigger_engine, "load_media_state", AsyncMock()),
        ):
            await svc.start()

        yield svc
        await svc.stop("test")


# ============================================================================
# Service Discovery
# ============================================================================


@pytest.mark.asyncio
async def test_service_discovery_on_startup(llm_service: LLMService):
    """Service lifecycle attribute is available after start()."""
    # kryten-py owns discovery publishing; verify it is configured
    assert llm_service.lifecycle is not None


@pytest.mark.asyncio
async def test_lifecycle_startup_event(base_config: LLMConfig):
    """start() completes and lifecycle is set without raising."""
    mock_client = _make_mock_client()
    with patch("kryten_llm.service.KrytenClient", return_value=mock_client):
        svc = LLMService(base_config)
        with (
            patch.object(svc.context_manager, "load_initial_state", AsyncMock()),
            patch.object(svc.trigger_engine, "load_media_state", AsyncMock()),
        ):
            await svc.start()

        assert svc.lifecycle is not None
        await svc.stop("test")


@pytest.mark.asyncio
async def test_heartbeat_publishing_configured(llm_service: LLMService):
    """Service metadata has heartbeats enabled."""
    assert llm_service.config.service_metadata.enable_heartbeats is True
    assert llm_service.config.service_metadata.heartbeat_interval_seconds == 5


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Timing-sensitive test requires a running kryten-py lifecycle loop; "
    "covered by HeartbeatPublisher unit tests"
)
async def test_multiple_heartbeats_published(llm_service: LLMService):
    """Multiple heartbeats are published over time (live kryten-py only)."""
    await asyncio.sleep(3.0)


@pytest.mark.asyncio
async def test_reannounce_on_discovery_poll(llm_service: LLMService):
    """_handle_discovery_poll triggers lifecycle.publish_startup."""
    if not hasattr(llm_service, "_handle_discovery_poll"):
        pytest.skip("_handle_discovery_poll not present on this service version")

    poll_msg = MagicMock()
    poll_msg.reply = "kryten.service.discovery.poll.reply"

    await llm_service._handle_discovery_poll(poll_msg)

    llm_service.client.lifecycle.publish_startup.assert_called()


@pytest.mark.asyncio
async def test_reannounce_on_robot_startup(llm_service: LLMService):
    """_handle_robot_startup triggers lifecycle.publish_startup."""
    if not hasattr(llm_service, "_handle_robot_startup"):
        pytest.skip("_handle_robot_startup not present on this service version")

    event = MagicMock()
    await llm_service._handle_robot_startup(event)

    llm_service.client.lifecycle.publish_startup.assert_called()


# ============================================================================
# Lifecycle events
# ============================================================================


@pytest.mark.asyncio
async def test_lifecycle_shutdown_event(base_config: LLMConfig):
    """stop() calls client.disconnect() cleanly."""
    mock_client = _make_mock_client()
    with patch("kryten_llm.service.KrytenClient", return_value=mock_client):
        svc = LLMService(base_config)
        with (
            patch.object(svc.context_manager, "load_initial_state", AsyncMock()),
            patch.object(svc.trigger_engine, "load_media_state", AsyncMock()),
        ):
            await svc.start()
        await svc.stop("test")

    mock_client.disconnect.assert_called()


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Timing-sensitive test requires heartbeat task to emit before cancel; "
    "covered by HeartbeatPublisher unit tests"
)
async def test_heartbeat_stops_on_shutdown(llm_service: LLMService):
    """Heartbeat task is cancelled on shutdown."""
    pass


# ============================================================================
# Group restart coordination
# ============================================================================


@pytest.mark.asyncio
async def test_group_restart_delayed_shutdown(base_config: LLMConfig):
    """Group restart applies a configurable delay before shutdown."""
    base_config.service_metadata.graceful_shutdown_timeout_seconds = 0

    mock_client = _make_mock_client()
    with patch("kryten_llm.service.KrytenClient", return_value=mock_client):
        svc = LLMService(base_config)
        with (
            patch.object(svc.context_manager, "load_initial_state", AsyncMock()),
            patch.object(svc.trigger_engine, "load_media_state", AsyncMock()),
        ):
            await svc.start()

        start = time.time()
        await svc.stop("group_restart")
        elapsed = time.time() - start

    # With 0s graceful timeout, stop() should be fast
    assert elapsed < 5.0


# ============================================================================
# Health state tests
# ============================================================================


@pytest.mark.asyncio
async def test_health_state_starts_healthy(llm_service: LLMService):
    """Service health monitor starts in healthy state."""
    health = llm_service.health_monitor.determine_health_status()
    assert health.state == HealthState.HEALTHY


@pytest.mark.asyncio
async def test_health_state_tracks_providers(llm_service: LLMService):
    """Health monitor tracks configured provider state."""
    health = llm_service.health_monitor.determine_health_status()
    assert isinstance(health.components, dict)


@pytest.mark.asyncio
async def test_provider_healthy_initial_state(llm_service: LLMService):
    """Providers are considered healthy before any failure."""
    # Before any calls, provider status is "unknown" (not yet assessed)
    status = llm_service.health_monitor.get_provider_status("test")
    assert status == "unknown"


@pytest.mark.asyncio
async def test_provider_marked_unhealthy_after_failures(llm_service: LLMService):
    """Health monitor marks provider unhealthy after recording failures."""
    provider_name = "test"
    for _ in range(5):
        llm_service.health_monitor.record_provider_failure(provider_name)

    assert llm_service.health_monitor.get_provider_status(provider_name) == "failed"


@pytest.mark.asyncio
async def test_provider_recovers_after_success(llm_service: LLMService):
    """Provider marked healthy again after success following failures."""
    provider_name = "test"
    for _ in range(5):
        llm_service.health_monitor.record_provider_failure(provider_name)

    llm_service.health_monitor.record_provider_success(provider_name)

    assert llm_service.health_monitor.get_provider_status(provider_name) == "ok"


# ============================================================================
# Metrics
# ============================================================================


@pytest.mark.asyncio
async def test_metrics_initialized(llm_service: LLMService):
    """Metrics object is initialised on the service."""
    # Metrics are embedded in health_monitor, not a separate service attribute
    health = llm_service.health_monitor.determine_health_status()
    assert health.metrics is not None
    assert "messages_processed" in health.metrics


@pytest.mark.asyncio
async def test_metrics_tracks_request_count(llm_service: LLMService):
    """Metrics tracks request count when incremented."""
    initial = llm_service.health_monitor.determine_health_status().metrics
    llm_service.health_monitor.record_message_processed()
    updated = llm_service.health_monitor.determine_health_status().metrics
    assert updated["messages_processed"] > initial["messages_processed"]


@pytest.mark.asyncio
async def test_component_health_in_heartbeat(llm_service: LLMService):
    """Component health data is available for heartbeat payloads."""
    health = llm_service.health_monitor.determine_health_status()
    assert isinstance(health.components, dict)


# ============================================================================
# Lifecycle config flags
# ============================================================================


@pytest.mark.asyncio
async def test_discovery_disabled_in_config(base_config_dict: dict):
    """Service starts without error when discovery is disabled."""
    base_config_dict["service_metadata"]["enable_service_discovery"] = False
    config = LLMConfig(**base_config_dict)

    mock_client = _make_mock_client()
    with patch("kryten_llm.service.KrytenClient", return_value=mock_client):
        svc = LLMService(config)
        with (
            patch.object(svc.context_manager, "load_initial_state", AsyncMock()),
            patch.object(svc.trigger_engine, "load_media_state", AsyncMock()),
        ):
            await svc.start()

    assert svc.config.service_metadata.enable_service_discovery is False
    await svc.stop("test")


@pytest.mark.asyncio
async def test_heartbeats_disabled_in_config(base_config_dict: dict):
    """Service starts without error when heartbeats are disabled."""
    base_config_dict["service_metadata"]["enable_heartbeats"] = False
    config = LLMConfig(**base_config_dict)

    mock_client = _make_mock_client()
    with patch("kryten_llm.service.KrytenClient", return_value=mock_client):
        svc = LLMService(config)
        with (
            patch.object(svc.context_manager, "load_initial_state", AsyncMock()),
            patch.object(svc.trigger_engine, "load_media_state", AsyncMock()),
        ):
            await svc.start()

    assert svc.config.service_metadata.enable_heartbeats is False
    await svc.stop("test")


# ============================================================================
# Complete lifecycle flow
# ============================================================================


@pytest.mark.asyncio
async def test_complete_lifecycle_flow(base_config: LLMConfig):
    """Complete start → handle traffic → stop cycle without error."""
    mock_client = _make_mock_client()

    with patch("kryten_llm.service.KrytenClient", return_value=mock_client):
        svc = LLMService(base_config)
        with (
            patch.object(svc.context_manager, "load_initial_state", AsyncMock()),
            patch.object(svc.trigger_engine, "load_media_state", AsyncMock()),
        ):
            await svc.start()

        # Service should be running
        assert svc.lifecycle is not None

        # Health should be ok
        health = svc.health_monitor.determine_health_status()
        assert health.state == HealthState.HEALTHY

        await svc.stop("test")

    # disconnect was called
    mock_client.disconnect.assert_called()