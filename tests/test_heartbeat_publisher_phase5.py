"""Unit tests for HeartbeatPublisher (Phase 5).

Tests heartbeat loop, publishing, error handling, and configuration support.
"""

import asyncio
import json
import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest

from kryten_llm.components.health_monitor import ServiceHealthMonitor
from kryten_llm.components.heartbeat import HeartbeatPublisher
from kryten_llm.models.config import ServiceMetadata


@pytest.fixture
def service_metadata():
    """Create ServiceMetadata config for testing."""
    return ServiceMetadata(
        service_name="llm-test",
        service_version="1.0.0-test",
        heartbeat_interval_seconds=1,  # Short interval for testing
        enable_service_discovery=True,
        enable_heartbeats=True,
        graceful_shutdown_timeout_seconds=30
    )


@pytest.fixture
def service_metadata_disabled():
    """Create ServiceMetadata with heartbeats disabled."""
    return ServiceMetadata(
        service_name="llm-test",
        service_version="1.0.0-test",
        heartbeat_interval_seconds=10,
        enable_service_discovery=True,
        enable_heartbeats=False,  # Disabled
        graceful_shutdown_timeout_seconds=30
    )


@pytest.fixture
def logger():
    """Create mock logger."""
    return Mock(spec=logging.Logger)


@pytest.fixture
def health_monitor(service_metadata, logger):
    """Create ServiceHealthMonitor instance."""
    monitor = ServiceHealthMonitor(service_metadata, logger)
    monitor.update_component_health("nats", True, "Connected")
    monitor.record_provider_success("openai")
    return monitor


@pytest.fixture
def nats_client():
    """Create mock NATS client."""
    client = AsyncMock()
    client.publish = AsyncMock()
    return client


@pytest.fixture
def heartbeat_publisher(service_metadata, health_monitor, nats_client, logger):
    """Create HeartbeatPublisher instance."""
    start_time = 1000.0
    return HeartbeatPublisher(
        config=service_metadata,
        health_monitor=health_monitor,
        nats_client=nats_client,
        logger=logger,
        start_time=start_time
    )


# ============================================================================
# Initialization Tests
# ============================================================================

def test_initialization(heartbeat_publisher, service_metadata, health_monitor, nats_client, logger):
    """Test heartbeat publisher initializes correctly."""
    assert heartbeat_publisher.config == service_metadata
    assert heartbeat_publisher.health_monitor == health_monitor
    assert heartbeat_publisher.nats == nats_client
    assert heartbeat_publisher.logger == logger
    assert heartbeat_publisher.start_time == 1000.0
    assert heartbeat_publisher._running is False
    assert heartbeat_publisher._heartbeat_task is None


# ============================================================================
# Start/Stop Tests
# ============================================================================

@pytest.mark.asyncio
async def test_start_heartbeat_publisher(heartbeat_publisher, logger):
    """Test starting heartbeat publisher."""
    await heartbeat_publisher.start()
    
    assert heartbeat_publisher._running is True
    assert heartbeat_publisher._heartbeat_task is not None
    logger.info.assert_called()
    
    # Clean up
    await heartbeat_publisher.stop()


@pytest.mark.asyncio
async def test_start_when_disabled(service_metadata_disabled, health_monitor, nats_client, logger):
    """Test starting heartbeat publisher when disabled in config."""
    publisher = HeartbeatPublisher(
        config=service_metadata_disabled,
        health_monitor=health_monitor,
        nats_client=nats_client,
        logger=logger,
        start_time=1000.0
    )
    
    await publisher.start()
    
    assert publisher._running is False
    assert publisher._heartbeat_task is None
    logger.info.assert_called_with("Heartbeats disabled in configuration")


@pytest.mark.asyncio
async def test_start_already_running(heartbeat_publisher, logger):
    """Test starting when already running logs warning."""
    await heartbeat_publisher.start()
    
    # Try to start again
    logger.reset_mock()
    await heartbeat_publisher.start()
    
    logger.warning.assert_called_with("Heartbeat publisher already running")
    
    # Clean up
    await heartbeat_publisher.stop()


@pytest.mark.asyncio
async def test_stop_heartbeat_publisher(heartbeat_publisher, logger):
    """Test stopping heartbeat publisher."""
    await heartbeat_publisher.start()
    assert heartbeat_publisher._running is True
    
    await heartbeat_publisher.stop()
    
    assert heartbeat_publisher._running is False
    logger.info.assert_called()


@pytest.mark.asyncio
async def test_stop_when_not_running(heartbeat_publisher):
    """Test stopping when not running does nothing."""
    assert heartbeat_publisher._running is False
    
    # Should not raise exception
    await heartbeat_publisher.stop()
    
    assert heartbeat_publisher._running is False


@pytest.mark.asyncio
async def test_stop_cancels_task(heartbeat_publisher):
    """Test stopping cancels the heartbeat task."""
    await heartbeat_publisher.start()
    task = heartbeat_publisher._heartbeat_task
    
    assert task is not None
    assert not task.done()
    
    await heartbeat_publisher.stop()
    
    assert task.done()


# ============================================================================
# Publishing Tests
# ============================================================================

@pytest.mark.asyncio
async def test_publish_heartbeat_called(heartbeat_publisher, nats_client):
    """Test that heartbeats are published."""
    await heartbeat_publisher.start()
    
    # Wait for at least one heartbeat
    await asyncio.sleep(1.5)
    
    # Check NATS publish was called
    assert nats_client.publish.called
    
    # Clean up
    await heartbeat_publisher.stop()


@pytest.mark.asyncio
async def test_heartbeat_subject_format(heartbeat_publisher, nats_client):
    """Test heartbeat published to correct subject."""
    await heartbeat_publisher.start()
    
    # Wait for heartbeat
    await asyncio.sleep(1.5)
    
    # Check subject
    call_args = nats_client.publish.call_args
    subject = call_args[0][0]
    assert subject == "kryten.service.heartbeat.llm-test"
    
    # Clean up
    await heartbeat_publisher.stop()


@pytest.mark.asyncio
async def test_heartbeat_payload_structure(heartbeat_publisher, nats_client):
    """Test heartbeat payload has correct structure."""
    await heartbeat_publisher.start()
    
    # Wait for heartbeat
    await asyncio.sleep(1.5)
    
    # Get payload
    call_args = nats_client.publish.call_args
    data = call_args[0][1]
    payload = json.loads(data.decode('utf-8'))
    
    # Check structure
    assert "service" in payload
    assert "version" in payload
    assert "hostname" in payload
    assert "timestamp" in payload
    assert "uptime_seconds" in payload
    assert "health" in payload
    assert "status" in payload
    
    # Clean up
    await heartbeat_publisher.stop()


@pytest.mark.asyncio
async def test_heartbeat_includes_health_status(heartbeat_publisher, nats_client, health_monitor):
    """Test heartbeat includes health status from monitor."""
    # Set some health state
    health_monitor.record_message_processed()
    health_monitor.record_response_sent()
    
    await heartbeat_publisher.start()
    await asyncio.sleep(1.5)
    
    # Get payload
    call_args = nats_client.publish.call_args
    data = call_args[0][1]
    payload = json.loads(data.decode('utf-8'))
    
    # Check health data
    assert payload["health"] == "healthy"
    assert payload["status"]["messages_processed"] == 1
    assert payload["status"]["responses_sent"] == 1
    
    # Clean up
    await heartbeat_publisher.stop()


@pytest.mark.asyncio
async def test_heartbeat_uptime_calculation(heartbeat_publisher, nats_client):
    """Test heartbeat calculates uptime correctly."""
    with patch('time.time', return_value=1100.0):  # 100 seconds after start_time
        await heartbeat_publisher.start()
        await asyncio.sleep(1.5)
        
        # Get payload
        call_args = nats_client.publish.call_args
        data = call_args[0][1]
        payload = json.loads(data.decode('utf-8'))
        
        # Check uptime is approximately 100 seconds
        assert 99 <= payload["uptime_seconds"] <= 101
        
        # Clean up
        await heartbeat_publisher.stop()


# ============================================================================
# Interval Tests
# ============================================================================

@pytest.mark.asyncio
async def test_heartbeat_interval_respected(heartbeat_publisher, nats_client):
    """Test heartbeats published at configured interval."""
    await heartbeat_publisher.start()
    
    # Wait for multiple heartbeats
    await asyncio.sleep(2.5)
    
    # Should have published 2-3 times (at ~1s intervals)
    call_count = nats_client.publish.call_count
    assert 2 <= call_count <= 3
    
    # Clean up
    await heartbeat_publisher.stop()


@pytest.mark.asyncio
async def test_different_interval(health_monitor, nats_client, logger):
    """Test heartbeat with different interval."""
    config = ServiceMetadata(
        service_name="llm-test",
        service_version="1.0.0-test",
        heartbeat_interval_seconds=2,  # 2 second interval
        enable_service_discovery=True,
        enable_heartbeats=True,
        graceful_shutdown_timeout_seconds=30
    )
    
    publisher = HeartbeatPublisher(
        config=config,
        health_monitor=health_monitor,
        nats_client=nats_client,
        logger=logger,
        start_time=1000.0
    )
    
    await publisher.start()
    await asyncio.sleep(3.5)
    
    # Should have published 1-2 times (at ~2s intervals)
    call_count = nats_client.publish.call_count
    assert 1 <= call_count <= 2
    
    # Clean up
    await publisher.stop()


# ============================================================================
# Error Handling Tests
# ============================================================================

@pytest.mark.asyncio
async def test_publish_error_logged(heartbeat_publisher, nats_client, logger):
    """Test publish errors are logged but don't crash loop."""
    # Make publish fail
    nats_client.publish.side_effect = Exception("NATS error")
    
    await heartbeat_publisher.start()
    await asyncio.sleep(1.5)
    
    # Error should be logged
    logger.error.assert_called()
    error_msg = logger.error.call_args[0][0]
    assert "Failed to publish heartbeat" in error_msg
    
    # Publisher should still be running
    assert heartbeat_publisher._running is True
    
    # Clean up
    await heartbeat_publisher.stop()


@pytest.mark.asyncio
async def test_publish_error_recovery(heartbeat_publisher, nats_client, logger):
    """Test publisher recovers from publish errors."""
    # Make first publish fail, then succeed
    nats_client.publish.side_effect = [
        Exception("NATS error"),
        None,  # Success
    ]
    
    await heartbeat_publisher.start()
    await asyncio.sleep(2.5)
    
    # Should have tried multiple times
    assert nats_client.publish.call_count >= 2
    
    # Clean up
    await heartbeat_publisher.stop()


@pytest.mark.asyncio
async def test_heartbeat_loop_error_handling(heartbeat_publisher, logger):
    """Test heartbeat loop handles errors gracefully."""
    # Simulate error in loop
    original_publish = heartbeat_publisher._publish_heartbeat
    call_count = [0]
    
    async def failing_publish():
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("Test error")
        await original_publish()
    
    heartbeat_publisher._publish_heartbeat = failing_publish
    
    await heartbeat_publisher.start()
    await asyncio.sleep(2.5)
    
    # Error should be logged
    logger.error.assert_called()
    
    # Loop should continue after error
    assert heartbeat_publisher._running is True
    
    # Clean up
    await heartbeat_publisher.stop()


# ============================================================================
# Integration Scenarios
# ============================================================================

@pytest.mark.asyncio
async def test_full_lifecycle(heartbeat_publisher, nats_client, logger):
    """Test complete start-publish-stop lifecycle."""
    # Start
    await heartbeat_publisher.start()
    assert heartbeat_publisher._running is True
    
    # Verify publishing
    await asyncio.sleep(1.5)
    assert nats_client.publish.called
    
    # Stop
    await heartbeat_publisher.stop()
    assert heartbeat_publisher._running is False
    
    # Verify cleanup
    logger.info.assert_any_call("Heartbeat publisher stopped")


@pytest.mark.asyncio
async def test_health_state_changes_reflected(heartbeat_publisher, nats_client, health_monitor):
    """Test heartbeats reflect health state changes."""
    await heartbeat_publisher.start()
    
    # Wait for first heartbeat (healthy)
    await asyncio.sleep(1.5)
    nats_client.publish.reset_mock()
    
    # Change health state to degraded
    health_monitor.update_component_health("rate_limiter", False, "Error")
    
    # Wait for next heartbeat
    await asyncio.sleep(1.5)
    
    # Get latest payload
    call_args = nats_client.publish.call_args
    data = call_args[0][1]
    payload = json.loads(data.decode('utf-8'))
    
    # Should reflect degraded state
    assert payload["health"] == "degraded"
    
    # Clean up
    await heartbeat_publisher.stop()


@pytest.mark.asyncio
async def test_provider_status_in_heartbeat(heartbeat_publisher, nats_client, health_monitor):
    """Test provider status included in heartbeat."""
    health_monitor.record_provider_success("openai")
    health_monitor.record_provider_failure("anthropic")
    
    await heartbeat_publisher.start()
    await asyncio.sleep(1.5)
    
    # Get payload
    call_args = nats_client.publish.call_args
    data = call_args[0][1]
    payload = json.loads(data.decode('utf-8'))
    
    # Check provider status
    providers = payload["status"]["llm_providers"]
    assert providers["openai"] == "ok"
    assert providers["anthropic"] == "failed"
    
    # Clean up
    await heartbeat_publisher.stop()


@pytest.mark.asyncio
async def test_concurrent_operations(heartbeat_publisher, nats_client, health_monitor):
    """Test heartbeat publisher works with concurrent health updates."""
    await heartbeat_publisher.start()
    
    # Simulate concurrent health updates
    async def update_health():
        for i in range(10):
            health_monitor.record_message_processed()
            health_monitor.record_response_sent()
            await asyncio.sleep(0.1)
    
    # Run updates concurrently with heartbeat loop
    update_task = asyncio.create_task(update_health())
    await asyncio.sleep(1.5)
    await update_task
    
    # Verify heartbeats still publishing
    assert nats_client.publish.called
    
    # Get latest payload
    call_args = nats_client.publish.call_args
    data = call_args[0][1]
    payload = json.loads(data.decode('utf-8'))
    
    # Metrics should reflect updates
    assert payload["status"]["messages_processed"] > 0
    
    # Clean up
    await heartbeat_publisher.stop()


@pytest.mark.asyncio
async def test_rapid_start_stop(heartbeat_publisher):
    """Test rapid start/stop doesn't cause issues."""
    for _ in range(3):
        await heartbeat_publisher.start()
        await asyncio.sleep(0.5)
        await heartbeat_publisher.stop()
        await asyncio.sleep(0.1)
    
    # Should not raise exceptions
    assert heartbeat_publisher._running is False
