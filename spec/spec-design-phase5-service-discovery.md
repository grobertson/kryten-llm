# Phase 5 Specification: Service Discovery & Monitoring

**Document Version**: 1.0  
**Phase**: 5 of 6  
**Estimated Effort**: 3-4 hours  
**Dependencies**: Phase 4 Complete  
**Status**: Draft

---

## Executive Summary

Phase 5 integrates kryten-llm into the broader Kryten ecosystem monitoring and coordination infrastructure. This phase leverages the existing `kryten-py` library's `LifecycleEventPublisher` class to implement service discovery, heartbeat monitoring, health reporting, and graceful shutdown coordination.

**Key Integration Point**: The `kryten-py` library already provides all required functionality through:
- `LifecycleEventPublisher` class for lifecycle events
- `HealthStatus` model for health reporting
- NATS KeyValue store for service registry

**Implementation Strategy**: Wrap and configure existing kryten-py functionality rather than reimplementing.

---

## Goals

### Primary Goals

1. **Service Discovery**: Announce service presence to Kryten ecosystem
2. **Health Monitoring**: Report service health status periodically
3. **Lifecycle Coordination**: Participate in system-wide lifecycle events
4. **Graceful Shutdown**: Coordinate shutdowns with other services

### Non-Goals

- Implementing custom health check infrastructure (use kryten-py)
- Building custom service registry (use NATS KV)
- Creating new monitoring protocols (use existing patterns)

---

## Requirements

### REQ-001: Service Discovery on Startup

**Priority**: MUST  
**Category**: Service Discovery

**Description**: Service MUST publish discovery announcement when fully initialized.

**Details**:
- Publish to `kryten.service.discovery` subject
- Include service metadata: name, version, features, hostname, timestamp
- Use `LifecycleEventPublisher.publish_startup()` from kryten-py
- Publish after NATS connection established and all components initialized
- Include LLM-specific metadata: providers configured, triggers loaded, personality name

**Success Criteria**:
- Discovery message received by monitoring services
- Metadata includes all required fields
- Published only after service ready to handle requests

---

### REQ-002: Heartbeat Publishing

**Priority**: MUST  
**Category**: Health Monitoring

**Description**: Service MUST publish heartbeat messages periodically.

**Details**:
- Publish to `kryten.service.heartbeat.llm` subject
- Interval: Every 10 seconds (configurable)
- Include health status: healthy, degraded, or failing
- Include uptime, event counts, error counts
- Stop publishing when shutting down

**Payload Example**:
```json
{
  "service": "llm",
  "version": "1.0.0",
  "hostname": "server01",
  "timestamp": "2025-12-11T10:30:00Z",
  "uptime_seconds": 3600,
  "health": "healthy",
  "status": {
    "nats_connected": true,
    "llm_providers": {
      "openai": "ok",
      "anthropic": "ok",
      "github": "unknown"
    },
    "rate_limiter_active": true,
    "spam_detector_active": true,
    "messages_processed": 150,
    "responses_sent": 45,
    "errors_last_hour": 2
  }
}
```

**Success Criteria**:
- Heartbeats published at consistent intervals
- Health status accurately reflects service state
- Monitoring services can track service availability

---

### REQ-003: Health Status Determination

**Priority**: MUST  
**Category**: Health Monitoring

**Description**: Service MUST accurately determine its health status.

**Health States**:
1. **Healthy**: All systems operational
   - NATS connected
   - At least one LLM provider available
   - No critical errors in last 5 minutes
   - All Phase 4 components operational

2. **Degraded**: Operational but impaired
   - All configured LLM providers have status "failed"
   - High error rate (>10% in last 5 minutes)
   - Rate limiter or spam detector inactive

3. **Failing**: Unable to fulfill core function
   - NATS disconnected
   - All configured LLM providers have status "failed" and retries exhausted
   - Critical component failure

**Success Criteria**:
- Health state matches actual service capability
- Transitions between states logged clearly
- Degraded state allows continued operation

---

### REQ-004: Lifecycle Event Publishing

**Priority**: MUST  
**Category**: Lifecycle Management

**Description**: Service MUST publish lifecycle events at key moments.

**Events**:

1. **Startup Event** (`kryten.lifecycle.llm.startup`)
   - Published when service fully initialized
   - Includes configuration summary (sanitized)
   - Signals readiness to process messages

2. **Shutdown Event** (`kryten.lifecycle.llm.shutdown`)
   - Published before beginning shutdown
   - Includes reason (normal, error, signal)
   - Includes uptime and final statistics

**Note on LLM Provider Status**: LLM providers make stateless API calls and do not have persistent connections like WebSockets. Provider health is tracked based on the result of the most recent API request:
- **OK**: Most recent request succeeded
- **FAILED**: Most recent request failed
- **UNKNOWN**: No requests made to this provider yet

Provider status is included in heartbeat messages but does not generate dedicated lifecycle events.

**Implementation Note**: Use `LifecycleEventPublisher` methods directly for startup and shutdown.

**Success Criteria**:
- All lifecycle events published at correct times
- Event payloads include required metadata
- Monitoring services can track service lifecycle

---

### REQ-005: Re-registration on Discovery Poll

**Priority**: MUST  
**Category**: Service Discovery

**Description**: Service MUST re-announce itself when discovery poll received.

**Details**:
- Subscribe to `kryten.service.discovery.poll` subject
- When received, republish startup event
- Used when kryten-robot restarts and needs to rebuild service registry
- Ensures service registry stays current after restarts

**Success Criteria**:
- Poll triggers immediate re-announcement
- Re-announcement identical to initial startup
- Works multiple times during service lifetime

---

### REQ-006: Robot Startup Notification

**Priority**: SHOULD  
**Category**: Lifecycle Coordination

**Description**: Service SHOULD respond to kryten-robot startup notifications.

**Details**:
- Subscribe to `kryten.lifecycle.robot.startup` subject
- When received, republish discovery (same as discovery poll)
- Allows coordinated service group startup
- Log robot startup for awareness

**Success Criteria**:
- Robot startup triggers re-registration
- Works in addition to discovery poll
- Does not interfere with normal operation

---

### REQ-007: Graceful Shutdown Handling

**Priority**: MUST  
**Category**: Lifecycle Management

**Description**: Service MUST shutdown gracefully when requested.

**Shutdown Process**:
1. Receive shutdown signal (SIGTERM, SIGINT) or group restart notice
2. Stop accepting new chat messages (unsubscribe)
3. Finish processing in-flight LLM requests (with timeout)
4. Publish shutdown lifecycle event
5. Close NATS connection
6. Exit cleanly

**Timeout**: Maximum 30 seconds for graceful shutdown

**Success Criteria**:
- No chat messages lost during shutdown
- Shutdown event published successfully
- Service exits with code 0 on normal shutdown
- Forced shutdown after timeout expires

---

### REQ-008: Group Restart Coordination

**Priority**: SHOULD  
**Category**: Lifecycle Coordination

**Description**: Service SHOULD participate in system-wide restart coordination.

**Details**:
- Subscribe to `kryten.lifecycle.group.restart` subject
- When received, initiate graceful shutdown after delay
- Delay specified in restart notice (default 5 seconds)
- Log restart notice with reason and initiator
- Use `LifecycleEventPublisher.on_restart_notice()` callback

**Success Criteria**:
- Group restart notice triggers delayed shutdown
- Delay period honored accurately
- Restart notice logged with all details
- Other services can coordinate restarts

---

### REQ-009: Service Metadata Configuration

**Priority**: MUST  
**Category**: Configuration

**Description**: Service metadata MUST be configurable.

**Configuration Fields**:
```python
class ServiceMetadata(BaseModel):
    """Service discovery metadata."""
    
    service_name: str = Field(default="llm", description="Service identifier")
    service_version: str = Field(default="1.0.0", description="Service version")
    heartbeat_interval_seconds: int = Field(default=10, ge=1, le=60, description="Heartbeat interval")
    enable_service_discovery: bool = Field(default=True, description="Enable service discovery")
    enable_heartbeats: bool = Field(default=True, description="Enable heartbeat publishing")
    graceful_shutdown_timeout_seconds: int = Field(default=30, ge=5, le=120, description="Graceful shutdown timeout")
```

**Success Criteria**:
- All metadata fields configurable via config file
- Defaults sensible for production
- Can disable discovery/heartbeats for testing

---

### REQ-010: Component Health Tracking

**Priority**: MUST  
**Category**: Health Monitoring

**Description**: Service MUST track health of individual components.

**Components to Track**:
1. **NATS Connection**: Connected/disconnected
2. **LLM Providers**: Status per provider based on last API call (ok/failed/unknown)
3. **Rate Limiter**: Active/inactive
4. **Spam Detector**: Active/inactive
5. **Response Formatter**: Operational/error
6. **Response Validator**: Operational/error

**Health Check Methods**:
```python
def check_nats_health(self) -> ComponentHealth:
    """Check NATS connection health."""
    
def check_llm_providers_health(self) -> ComponentHealth:
    """Check LLM provider availability."""
    
def check_phase4_components_health(self) -> ComponentHealth:
    """Check Phase 4 component health."""
```

**Success Criteria**:
- Each component health tracked independently
- Overall health derived from component statuses
- Component failures reflected in health status

---

## Architecture

### Component Integration

```
┌─────────────────────────────────────────────────────────────┐
│                        LLMService                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────────────────────────────────────┐    │
│  │         LifecycleEventPublisher                   │    │
│  │         (from kryten-py library)                  │    │
│  ├───────────────────────────────────────────────────┤    │
│  │ - publish_startup()                               │    │
│  │ - publish_shutdown()                              │    │
│  │ - publish_group_restart()                         │    │
│  │ - on_restart_notice(callback)                     │    │
│  │                                                   │    │
│  │ Note: No connected/disconnected events for       │    │
│  │ stateless LLM API calls                          │    │
│  └───────────────────────────────────────────────────┘    │
│                          │                                  │
│  ┌───────────────────────▼──────────────────────────┐     │
│  │         ServiceHealthMonitor                      │     │
│  │         (New Component)                           │     │
│  ├───────────────────────────────────────────────────┤    │
│  │ - determine_health_status()                       │    │
│  │ - check_component_health()                        │    │
│  │ - get_health_metrics()                            │    │
│  │ - publish_heartbeat() ──────────────────┐         │    │
│  └───────────────────────────────────────────────────┘    │
│                                              │              │
│  ┌───────────────────────────────────────────▼───────┐    │
│  │         HeartbeatPublisher                        │    │
│  │         (New Component)                           │    │
│  ├───────────────────────────────────────────────────┤    │
│  │ - start_heartbeat_loop()                          │    │
│  │ - stop_heartbeat_loop()                           │    │
│  │ - publish_heartbeat_message()                     │    │
│  └───────────────────────────────────────────────────┘    │
│                                                             │
│  Existing Components:                                      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐      │
│  │ LLM Manager  │ │ Rate Limiter │ │ Spam Detector│      │
│  └──────────────┘ └──────────────┘ └──────────────┘      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐      │
│  │  Formatter   │ │  Validator   │ │Context Mgr   │      │
│  └──────────────┘ └──────────────┘ └──────────────┘      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Subject Patterns

**Outbound** (Published by kryten-llm):
- `kryten.service.discovery` - Service announcement
- `kryten.service.heartbeat.llm` - Periodic health status
- `kryten.lifecycle.llm.startup` - Service startup
- `kryten.lifecycle.llm.shutdown` - Service shutdown

**Inbound** (Subscribed by kryten-llm):
- `kryten.service.discovery.poll` - Re-register request
- `kryten.lifecycle.robot.startup` - Robot startup notification
- `kryten.lifecycle.group.restart` - Group restart notice

---

## Detailed Design

### ServiceHealthMonitor Component

**Purpose**: Track component health and determine overall service health.

**File**: `kryten_llm/components/health_monitor.py`

```python
"""Service health monitoring for Phase 5.

Tracks health of individual components and determines overall service health.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from kryten_llm.models.config import ServiceMetadata


class HealthState(Enum):
    """Overall service health states."""
    
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"


@dataclass
class ComponentHealth:
    """Health status of a single component."""
    
    name: str
    healthy: bool
    message: str
    last_check: datetime


@dataclass
class ServiceHealth:
    """Overall service health status."""
    
    state: HealthState
    message: str
    components: dict[str, ComponentHealth]
    metrics: dict[str, int | float]
    timestamp: datetime


class ServiceHealthMonitor:
    """Monitor service health and component status.
    
    Tracks health of:
    - NATS connection
    - LLM providers
    - Phase 4 components (formatter, validator, spam detector)
    - Overall system health
    
    Phase 5 Implementation (REQ-003, REQ-010).
    """
    
    def __init__(self, config: ServiceMetadata, logger: logging.Logger):
        """Initialize health monitor.
        
        Args:
            config: Service metadata configuration
            logger: Logger instance
        """
        self.config = config
        self.logger = logger
        
        # Component health tracking
        self._component_health: dict[str, ComponentHealth] = {}
        
        # LLM provider status tracking (stateless API calls)
        # Status: "ok" = last call succeeded, "failed" = last call failed, "unknown" = no calls yet
        self._provider_status: dict[str, str] = {}  # provider_name -> status
        
        # Metrics tracking
        self._messages_processed = 0
        self._responses_sent = 0
        self._errors_count = 0
        self._errors_window: list[datetime] = []  # Last 5 minutes
        
        # Health state
        self._current_state = HealthState.HEALTHY
        self._state_changed_at = datetime.now()
    
    def record_message_processed(self) -> None:
        """Record a message was processed."""
        self._messages_processed += 1
    
    def record_response_sent(self) -> None:
        """Record a response was sent."""
        self._responses_sent += 1
    
    def record_error(self) -> None:
        """Record an error occurred."""
        self._errors_count += 1
        self._errors_window.append(datetime.now())
        
        # Clean old errors (>5 minutes)
        cutoff = datetime.now() - timedelta(minutes=5)
        self._errors_window = [ts for ts in self._errors_window if ts > cutoff]
    
    def record_provider_success(self, provider_name: str) -> None:
        """Record successful API call to LLM provider.
        
        Args:
            provider_name: Name of the provider (e.g., "openai", "anthropic")
        """
        self._provider_status[provider_name] = "ok"
        self.logger.debug(f"Provider {provider_name} status: ok")
    
    def record_provider_failure(self, provider_name: str) -> None:
        """Record failed API call to LLM provider.
        
        Args:
            provider_name: Name of the provider
        """
        self._provider_status[provider_name] = "failed"
        self.logger.warning(f"Provider {provider_name} status: failed")
    
    def get_provider_status(self, provider_name: str) -> str:
        """Get current status of LLM provider.
        
        Args:
            provider_name: Name of the provider
            
        Returns:
            "ok", "failed", or "unknown"
        """
        return self._provider_status.get(provider_name, "unknown")
    
    def update_component_health(
        self, 
        component: str, 
        healthy: bool, 
        message: str = ""
    ) -> None:
        """Update health status of a component.
        
        Args:
            component: Component name (e.g., "nats", "llm_providers")
            healthy: Whether component is healthy
            message: Health status message
        """
        self._component_health[component] = ComponentHealth(
            name=component,
            healthy=healthy,
            message=message,
            last_check=datetime.now()
        )
        
        self.logger.debug(
            f"Component health updated: {component} = "
            f"{'healthy' if healthy else 'unhealthy'}: {message}"
        )
    
    def determine_health_status(self) -> ServiceHealth:
        """Determine overall service health status.
        
        Implements REQ-003 health state determination.
        
        Returns:
            ServiceHealth with current state and details
        """
        # Check critical components
        nats_health = self._component_health.get("nats")
        
        # Check LLM provider status (stateless API calls)
        providers_ok = [name for name, status in self._provider_status.items() if status == "ok"]
        providers_failed = [name for name, status in self._provider_status.items() if status == "failed"]
        providers_unknown = [name for name, status in self._provider_status.items() if status == "unknown"]
        all_providers_failed = len(self._provider_status) > 0 and len(providers_failed) == len(self._provider_status)
        
        # Determine health state
        if not nats_health or not nats_health.healthy:
            state = HealthState.FAILING
            message = "NATS connection lost"
        elif all_providers_failed:
            state = HealthState.FAILING
            message = "All LLM providers failing"
        elif self._get_error_rate() > 0.10:  # >10% error rate
            state = HealthState.DEGRADED
            message = f"High error rate: {self._get_error_rate():.1%}"
        elif any(
            not comp.healthy 
            for comp in self._component_health.values() 
            if comp.name not in ["nats", "llm_providers"]
        ):
            state = HealthState.DEGRADED
            message = "Some components degraded"
        else:
            state = HealthState.HEALTHY
            message = "All systems operational"
        
        # Track state changes
        if state != self._current_state:
            self.logger.warning(
                f"Health state changed: {self._current_state.value} -> {state.value}"
            )
            self._current_state = state
            self._state_changed_at = datetime.now()
        
        return ServiceHealth(
            state=state,
            message=message,
            components=self._component_health.copy(),
            metrics={
                "messages_processed": self._messages_processed,
                "responses_sent": self._responses_sent,
                "total_errors": self._errors_count,
                "errors_last_5min": len(self._errors_window),
                "error_rate": self._get_error_rate(),
            },
            timestamp=datetime.now()
        )
    
    def _get_error_rate(self) -> float:
        """Calculate error rate over last 5 minutes."""
        recent_errors = len(self._errors_window)
        total_processed = self._messages_processed
        
        if total_processed == 0:
            return 0.0
        
        return recent_errors / total_processed
    
    def get_heartbeat_payload(self, uptime_seconds: float) -> dict:
        """Build heartbeat payload with current health.
        
        Implements REQ-002 heartbeat payload.
        
        Args:
            uptime_seconds: Service uptime in seconds
            
        Returns:
            Dictionary ready for JSON serialization
        """
        health = self.determine_health_status()
        
        # Build per-provider status dict
        llm_providers_status = {}
        for provider_name, status in self._provider_status.items():
            llm_providers_status[provider_name] = status
        
        return {
            "service": self.config.service_name,
            "version": self.config.service_version,
            "hostname": self._get_hostname(),
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": uptime_seconds,
            "health": health.state.value,
            "status": {
                "nats_connected": self._component_health.get("nats", 
                    ComponentHealth("nats", False, "", datetime.now())).healthy,
                "llm_providers": llm_providers_status,
                "rate_limiter_active": self._component_health.get("rate_limiter",
                    ComponentHealth("rate_limiter", True, "", datetime.now())).healthy,
                "spam_detector_active": self._component_health.get("spam_detector",
                    ComponentHealth("spam_detector", True, "", datetime.now())).healthy,
                "messages_processed": health.metrics["messages_processed"],
                "responses_sent": health.metrics["responses_sent"],
                "errors_last_hour": health.metrics["errors_last_5min"],
            }
        }
    
    def _get_hostname(self) -> str:
        """Get system hostname."""
        import socket
        return socket.gethostname()
```

---

### HeartbeatPublisher Component

**Purpose**: Publish periodic heartbeat messages.

**File**: `kryten_llm/components/heartbeat.py`

```python
"""Heartbeat publishing for Phase 5.

Publishes periodic health status to NATS.
"""

import asyncio
import json
import logging
from typing import Optional

from nats.aio.client import Client as NATSClient

from kryten_llm.components.health_monitor import ServiceHealthMonitor
from kryten_llm.models.config import ServiceMetadata


class HeartbeatPublisher:
    """Publish periodic heartbeat messages.
    
    Publishes service health status to kryten.service.heartbeat.llm subject
    at configured interval.
    
    Phase 5 Implementation (REQ-002).
    """
    
    def __init__(
        self,
        config: ServiceMetadata,
        health_monitor: ServiceHealthMonitor,
        nats_client: NATSClient,
        logger: logging.Logger,
        start_time: float
    ):
        """Initialize heartbeat publisher.
        
        Args:
            config: Service metadata configuration
            health_monitor: Health monitoring component
            nats_client: NATS client for publishing
            logger: Logger instance
            start_time: Service start timestamp
        """
        self.config = config
        self.health_monitor = health_monitor
        self.nats = nats_client
        self.logger = logger
        self.start_time = start_time
        
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self) -> None:
        """Start heartbeat publishing loop."""
        if not self.config.enable_heartbeats:
            self.logger.info("Heartbeats disabled in configuration")
            return
        
        if self._running:
            self.logger.warning("Heartbeat publisher already running")
            return
        
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self.logger.info(
            f"Heartbeat publisher started (interval: {self.config.heartbeat_interval_seconds}s)"
        )
    
    async def stop(self) -> None:
        """Stop heartbeat publishing loop."""
        if not self._running:
            return
        
        self._running = False
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("Heartbeat publisher stopped")
    
    async def _heartbeat_loop(self) -> None:
        """Main heartbeat publishing loop."""
        while self._running:
            try:
                await self._publish_heartbeat()
                await asyncio.sleep(self.config.heartbeat_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in heartbeat loop: {e}", exc_info=True)
                await asyncio.sleep(self.config.heartbeat_interval_seconds)
    
    async def _publish_heartbeat(self) -> None:
        """Publish single heartbeat message.
        
        Implements REQ-002 heartbeat publishing.
        """
        try:
            # Calculate uptime
            import time
            uptime = time.time() - self.start_time
            
            # Build payload from health monitor
            payload = self.health_monitor.get_heartbeat_payload(uptime)
            
            # Publish to NATS
            subject = f"kryten.service.heartbeat.{self.config.service_name}"
            data = json.dumps(payload).encode('utf-8')
            
            await self.nats.publish(subject, data)
            
            self.logger.debug(
                f"Published heartbeat: {payload['health']} "
                f"({payload['status']['messages_processed']} messages processed)"
            )
        
        except Exception as e:
            self.logger.error(f"Failed to publish heartbeat: {e}", exc_info=True)
```

---

### LLMService Integration

**Changes to**: `kryten_llm/service.py`

```python
# Add imports
from kryten.lifecycle_events import LifecycleEventPublisher
from kryten_llm.components.health_monitor import ServiceHealthMonitor
from kryten_llm.components.heartbeat import HeartbeatPublisher
from kryten_llm.models.config import ServiceMetadata
import time

class LLMService:
    """Main LLM service with Phase 5 service discovery."""
    
    def __init__(self, config: LLMConfig):
        """Initialize LLM service with Phase 5 components."""
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # ... existing initialization ...
        
        # Phase 5: Service discovery and monitoring
        self.service_metadata = config.service_metadata  # New config section
        self.start_time = time.time()
        
        # Will be initialized in start()
        self.lifecycle_publisher: Optional[LifecycleEventPublisher] = None
        self.health_monitor: Optional[ServiceHealthMonitor] = None
        self.heartbeat_publisher: Optional[HeartbeatPublisher] = None
    
    async def start(self):
        """Start service with Phase 5 discovery."""
        self.logger.info("Starting kryten-llm service...")
        
        # Connect to NATS (existing)
        await self._connect_nats()
        
        # Phase 5: Initialize service discovery components
        await self._initialize_phase5_components()
        
        # Initialize other components (existing Phase 1-4)
        await self._initialize_components()
        
        # Phase 5: Publish startup event (REQ-001, REQ-004)
        if self.service_metadata.enable_service_discovery:
            await self.lifecycle_publisher.publish_startup(
                providers_configured=len(self.config.llm_providers),
                triggers_loaded=len(self.config.triggers),
                personality=self.config.personality.name,
            )
        
        # Phase 5: Start heartbeat publishing (REQ-002)
        await self.heartbeat_publisher.start()
        
        self.logger.info("kryten-llm service started successfully")
    
    async def _initialize_phase5_components(self):
        """Initialize Phase 5 service discovery components."""
        # Lifecycle event publisher (uses kryten-py)
        self.lifecycle_publisher = LifecycleEventPublisher(
            service_name=self.service_metadata.service_name,
            nats_client=self.nats_client,
            logger=self.logger,
            version=self.service_metadata.service_version
        )
        
        await self.lifecycle_publisher.start()
        
        # Register group restart callback (REQ-008)
        self.lifecycle_publisher.on_restart_notice(self._handle_group_restart)
        
        # Health monitor
        self.health_monitor = ServiceHealthMonitor(
            config=self.service_metadata,
            logger=self.logger
        )
        
        # Update initial health status
        self.health_monitor.update_component_health(
            "nats", True, "Connected to NATS"
        )
        
        # Heartbeat publisher
        self.heartbeat_publisher = HeartbeatPublisher(
            config=self.service_metadata,
            health_monitor=self.health_monitor,
            nats_client=self.nats_client,
            logger=self.logger,
            start_time=self.start_time
        )
        
        # Subscribe to discovery poll (REQ-005)
        await self.nats_client.subscribe(
            "kryten.service.discovery.poll",
            cb=self._handle_discovery_poll
        )
        
        # Subscribe to robot startup (REQ-006)
        await self.nats_client.subscribe(
            "kryten.lifecycle.robot.startup",
            cb=self._handle_robot_startup
        )
    
    async def _handle_discovery_poll(self, msg):
        """Handle discovery poll request (REQ-005)."""
        self.logger.info("Discovery poll received, re-announcing service")
        
        if self.service_metadata.enable_service_discovery:
            await self.lifecycle_publisher.publish_startup(
                providers_configured=len(self.config.llm_providers),
                triggers_loaded=len(self.config.triggers),
                personality=self.config.personality.name,
                re_announcement=True
            )
    
    async def _handle_robot_startup(self, msg):
        """Handle robot startup notification (REQ-006)."""
        self.logger.info("Robot startup detected, re-announcing service")
        
        if self.service_metadata.enable_service_discovery:
            await self.lifecycle_publisher.publish_startup(
                providers_configured=len(self.config.llm_providers),
                triggers_loaded=len(self.config.triggers),
                personality=self.config.personality.name,
                re_announcement=True
            )
    
    async def _handle_group_restart(self, data: dict):
        """Handle group restart notice (REQ-008)."""
        delay = data.get('delay_seconds', 5)
        reason = data.get('reason', 'Group restart')
        
        self.logger.warning(
            f"Group restart requested: {reason}. Shutting down in {delay}s..."
        )
        
        # Wait for delay period
        await asyncio.sleep(delay)
        
        # Initiate graceful shutdown
        await self.stop(reason=f"Group restart: {reason}")
    
    async def stop(self, reason: str = "Normal shutdown"):
        """Stop service with graceful shutdown (REQ-007)."""
        self.logger.info(f"Stopping kryten-llm service: {reason}")
        
        # Phase 5: Stop accepting new messages
        # (unsubscribe from chat events)
        
        # Phase 5: Wait for in-flight requests (with timeout)
        timeout = self.service_metadata.graceful_shutdown_timeout_seconds
        # ... implement timeout logic ...
        
        # Phase 5: Stop heartbeats
        if self.heartbeat_publisher:
            await self.heartbeat_publisher.stop()
        
        # Phase 5: Publish shutdown event (REQ-004)
        if self.lifecycle_publisher:
            await self.lifecycle_publisher.publish_shutdown(
                reason=reason,
                messages_processed=self.health_monitor._messages_processed,
                responses_sent=self.health_monitor._responses_sent
            )
            await self.lifecycle_publisher.stop()
        
        # Close NATS connection (existing)
        await self._disconnect_nats()
        
        self.logger.info("kryten-llm service stopped")
    
    # Update existing methods to track health
    
    async def _handle_chat_message(self, event):
        """Handle chat message with health tracking."""
        # ... existing processing ...
        
        # Phase 5: Track metrics
        self.health_monitor.record_message_processed()
        
        try:
            # ... existing LLM processing ...
            # When calling LLM provider, get provider name
            provider_name = "openai"  # Example - get from actual provider used
            
            response = await llm_provider.generate(prompt)
            
            # Phase 5: Record successful API call
            self.health_monitor.record_provider_success(provider_name)
            
            # Phase 5: Track successful response
            self.health_monitor.record_response_sent()
        
        except LLMProviderError as e:
            # Phase 5: Record failed API call to specific provider
            self.health_monitor.record_provider_failure(e.provider_name)
            # Phase 5: Track error
            self.health_monitor.record_error()
            raise
        except Exception as e:
            # Phase 5: Track error
            self.health_monitor.record_error()
            raise
```

---

## Configuration

### Addition to config.example.json

```json
{
  "service_metadata": {
    "service_name": "llm",
    "service_version": "1.0.0",
    "heartbeat_interval_seconds": 10,
    "enable_service_discovery": true,
    "enable_heartbeats": true,
    "graceful_shutdown_timeout_seconds": 30
  }
}
```

### ServiceMetadata Configuration Model

**File**: `kryten_llm/models/config.py`

```python
class ServiceMetadata(BaseModel):
    """Service discovery and monitoring configuration.
    
    Phase 5: Service discovery configuration (REQ-009).
    """
    
    service_name: str = Field(
        default="llm",
        description="Service identifier for discovery"
    )
    
    service_version: str = Field(
        default="1.0.0",
        description="Service version string"
    )
    
    heartbeat_interval_seconds: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Heartbeat publishing interval in seconds"
    )
    
    enable_service_discovery: bool = Field(
        default=True,
        description="Enable service discovery announcements"
    )
    
    enable_heartbeats: bool = Field(
        default=True,
        description="Enable periodic heartbeat publishing"
    )
    
    graceful_shutdown_timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Maximum time to wait for graceful shutdown"
    )


class LLMConfig(KrytenConfig):
    """Extended configuration with Phase 5 service metadata."""
    
    # ... existing fields ...
    
    service_metadata: ServiceMetadata = Field(
        default_factory=ServiceMetadata,
        description="Service discovery and monitoring settings"
    )
```

---

## Acceptance Criteria

### AC-001: Service Discovery on Startup

**Given**: Service starts up successfully  
**When**: All components initialized  
**Then**: Discovery message published to `kryten.service.discovery`  
**And**: Message includes service name, version, hostname, features  
**And**: Message includes LLM-specific metadata (providers, triggers, personality)

**Test**:
```bash
# Monitor discovery subject
nats sub "kryten.service.discovery"

# Start service
poetry run kryten-llm --config config.json

# Verify discovery message received with correct fields
```

---

### AC-002: Heartbeat Publishing

**Given**: Service running normally  
**When**: Heartbeat interval elapses  
**Then**: Heartbeat published to `kryten.service.heartbeat.llm`  
**And**: Includes health state (healthy/degraded/failing)  
**And**: Includes component statuses  
**And**: Includes metrics (messages processed, responses sent, errors)

**Test**:
```bash
# Monitor heartbeats
nats sub "kryten.service.heartbeat.llm"

# Verify heartbeats arrive every 10 seconds
# Verify payload contains required fields
```

---

### AC-003: Health State Accuracy

**Given**: Service with various component states  
**When**: Health status determined  
**Then**: State accurately reflects service capability  

**Test Scenarios**:
1. All components healthy → state = "healthy"
2. All LLM providers failing → state = "failing"
3. High error rate → state = "degraded"
4. NATS disconnected → state = "failing"

---

### AC-004: Lifecycle Events Published

**Given**: Service lifecycle events occur  
**When**: Startup, shutdown, connect, disconnect happens  
**Then**: Appropriate lifecycle event published  
**And**: Event includes relevant metadata

**Test**:
```bash
# Monitor all lifecycle events
nats sub "kryten.lifecycle.llm.>"

# Start service → see startup event
# Stop service → see shutdown event
# Provider status tracked in heartbeats, not separate events
```

---

### AC-005: Re-registration on Poll

**Given**: Service running  
**When**: Discovery poll message received  
**Then**: Service republishes discovery announcement  
**And**: Re-announcement identical to initial startup

**Test**:
```bash
# Send discovery poll
nats pub "kryten.service.discovery.poll" ""

# Verify service republishes discovery
nats sub "kryten.service.discovery"
```

---

### AC-006: Graceful Shutdown

**Given**: Service running with in-flight requests  
**When**: Shutdown signal received  
**Then**: Stop accepting new messages  
**And**: Finish processing current requests (with timeout)  
**And**: Publish shutdown event  
**And**: Exit cleanly

**Test**:
```bash
# Start service
poetry run kryten-llm --config config.json

# Send SIGTERM
kill -TERM <pid>

# Verify shutdown event published
# Verify process exits with code 0
```

---

### AC-007: Group Restart Coordination

**Given**: Service running  
**When**: Group restart notice received  
**Then**: Log restart notice with details  
**And**: Wait for specified delay  
**And**: Initiate graceful shutdown  
**And**: Include restart reason in shutdown event

**Test**:
```bash
# Publish group restart notice
nats pub "kryten.lifecycle.group.restart" '{"reason": "Test restart", "delay_seconds": 3, "initiator": "test"}'

# Verify service logs restart notice
# Verify service waits 3 seconds
# Verify service shuts down gracefully
```

---

### AC-008: Configuration Flexibility

**Given**: Service configuration file  
**When**: Service metadata configured  
**Then**: All metadata fields respected  
**And**: Can disable discovery for testing  
**And**: Can disable heartbeats for testing  
**And**: Can adjust intervals

**Test**:
```json
{
  "service_metadata": {
    "enable_service_discovery": false,
    "enable_heartbeats": false
  }
}
```

Verify no discovery/heartbeat messages published.

---

### AC-009: Component Health Tracking

**Given**: Service with multiple components  
**When**: Component states change  
**Then**: Health monitor tracks each component independently  
**And**: Overall health reflects component statuses  
**And**: Health transitions logged clearly

**Test**:
```python
# Simulate component failures
health_monitor.update_component_health("llm_providers", False, "Provider failed")

# Check health status
status = health_monitor.determine_health_status()
assert status.state == HealthState.FAILING
```

---

### AC-010: Integration with kryten-py

**Given**: kryten-py library available  
**When**: Service uses LifecycleEventPublisher  
**Then**: All lifecycle events use kryten-py methods  
**And**: No duplicate implementations  
**And**: Consistent with other Kryten services

**Test**: Code review to verify using `LifecycleEventPublisher` from kryten-py.

---

## Testing Strategy

### Unit Tests

**File**: `tests/test_health_monitor_phase5.py`

Test cases:
- Health state determination logic
- Component health tracking
- Metrics recording
- Error rate calculation
- Heartbeat payload generation

**File**: `tests/test_heartbeat_publisher_phase5.py`

Test cases:
- Heartbeat loop starts/stops correctly
- Publishes at correct interval
- Handles NATS errors gracefully
- Can be disabled via configuration

### Integration Tests

**File**: `tests/test_phase5_integration.py`

Test cases:
- Full startup sequence with discovery
- Heartbeat publishing over time
- Re-registration on poll
- Graceful shutdown sequence
- Group restart coordination
- Health state transitions

### Manual Testing

**Checklist**:
```bash
# 1. Monitor all Phase 5 subjects
nats sub "kryten.service.>" &
nats sub "kryten.lifecycle.>" &

# 2. Start service
poetry run kryten-llm --config config.json

# Expected:
# - Discovery announcement
# - Startup lifecycle event
# - Heartbeats every 10s

# 3. Send discovery poll
nats pub "kryten.service.discovery.poll" ""

# Expected:
# - Re-announcement received

# 4. Simulate robot restart
nats pub "kryten.lifecycle.robot.startup" '{"service": "robot"}'

# Expected:
# - Re-announcement received

# 5. Test graceful shutdown
kill -TERM <pid>

# Expected:
# - Shutdown event published
# - Clean exit

# 6. Test group restart
nats pub "kryten.lifecycle.group.restart" '{"reason": "Test", "delay_seconds": 5}'

# Expected:
# - Service logs restart notice
# - Waits 5 seconds
# - Shuts down gracefully
```

---

## Implementation Checklist

### Phase 5.1: Core Components (1-1.5 hours)

- [ ] Create `ServiceMetadata` configuration model
- [ ] Create `ServiceHealthMonitor` component
  - [ ] Health state determination logic
  - [ ] Component health tracking
  - [ ] Metrics recording
  - [ ] Heartbeat payload generation
- [ ] Create `HeartbeatPublisher` component
  - [ ] Async heartbeat loop
  - [ ] NATS publishing
  - [ ] Configuration support

### Phase 5.2: Service Integration (1-1.5 hours)

- [ ] Add `LifecycleEventPublisher` to LLMService
- [ ] Initialize Phase 5 components in `start()`
- [ ] Publish startup event with metadata
- [ ] Start heartbeat publishing
- [ ] Subscribe to discovery poll
- [ ] Subscribe to robot startup
- [ ] Subscribe to group restart
- [ ] Implement graceful shutdown
- [ ] Publish shutdown event

### Phase 5.3: Health Tracking (30-45 minutes)

- [ ] Update `_handle_chat_message()` to record metrics
- [ ] Track LLM provider API call results (success/failure)
- [ ] Record provider status after each API call
- [ ] Update health state based on provider statuses
- [ ] Ensure health state accurately reflects reality

### Phase 5.4: Configuration & Testing (45-60 minutes)

- [ ] Add `service_metadata` section to config.example.json
- [ ] Write unit tests for ServiceHealthMonitor
- [ ] Write unit tests for HeartbeatPublisher
- [ ] Write integration tests for full Phase 5 flow
- [ ] Manual testing with NATS monitoring
- [ ] Test with discovery poll
- [ ] Test with group restart
- [ ] Test graceful shutdown

---

## Edge Cases

### Edge Case 1: NATS Reconnection

**Scenario**: NATS connection lost and reconnected  
**Expected Behavior**:
- Health state transitions to FAILING when disconnected
- Heartbeats stop publishing
- When reconnected, health transitions back to HEALTHY
- Heartbeats resume
- Republish discovery announcement after reconnection

**Implementation**: Handle NATS disconnect/reconnect events in LLMService.

---

### Edge Case 2: Multiple Provider Failures

**Scenario**: All configured LLM providers start failing API calls  
**Expected Behavior**:
- Provider status tracked after each API call
- Health state transitions to FAILING when all providers have "failed" status
- State transition logged
- Heartbeats reflect per-provider status
- Service can recover when provider API calls succeed again

**Implementation**: Health state determination checks all components atomically.

---

### Edge Case 3: Shutdown During LLM Request

**Scenario**: Graceful shutdown requested while LLM request in flight  
**Expected Behavior**:
- Service waits up to timeout for request completion
- If request completes in time, response sent
- If timeout expires, request abandoned
- Shutdown event published either way

**Implementation**: Use asyncio.wait_for() with timeout on in-flight tasks.

---

### Edge Case 4: Discovery Poll Spam

**Scenario**: Receive many discovery polls in short time  
**Expected Behavior**:
- Service responds to each poll
- No rate limiting on re-announcements
- Does not impact normal operation
- Logs warning if excessive

**Implementation**: Simple counter and log warning if >10 polls/minute.

---

### Edge Case 5: Heartbeat Publish Failure

**Scenario**: NATS publish fails when sending heartbeat  
**Expected Behavior**:
- Error logged but not raised
- Heartbeat loop continues
- Next heartbeat attempted normally
- Does not crash service

**Implementation**: Wrap publish in try/except, log error, continue loop.

---

## Dependencies

### External Dependencies

- **kryten-py >= 1.0.0**: For LifecycleEventPublisher
- **NATS**: For publishing discovery and heartbeats
- **Python 3.11+**: For asyncio features

### Internal Dependencies

- Phase 4 must be complete (all components operational)
- Configuration system must support new ServiceMetadata
- NATS connection must be established

---

## Migration Notes

### From No Service Discovery to Phase 5

**No breaking changes** - Phase 5 is purely additive.

**Steps**:
1. Update config.json to include `service_metadata` section
2. Restart service
3. Verify discovery and heartbeats publishing
4. No code changes required for existing functionality

### Disabling Phase 5 Features

If needed for testing or debugging:

```json
{
  "service_metadata": {
    "enable_service_discovery": false,
    "enable_heartbeats": false
  }
}
```

Service will function normally without discovery/monitoring.

---

## Performance Considerations

### Heartbeat Overhead

- **Publishing Rate**: 1 message per 10 seconds = 0.1 msg/s
- **Message Size**: ~500 bytes (JSON payload)
- **Bandwidth**: ~50 bytes/second = negligible
- **CPU**: Minimal (JSON serialization + NATS publish)

**Recommendation**: 10-second interval is reasonable. Can increase to 30s if needed.

### Health Check Overhead

- **Frequency**: On every heartbeat (every 10s)
- **Operations**: Component status checks, metric aggregation
- **Cost**: O(n) where n = number of components (~10)
- **Impact**: Negligible (<1ms)

**Recommendation**: No optimization needed.

### Discovery Re-announcement

- **Frequency**: Only on poll/robot startup (rare)
- **Cost**: Single NATS publish
- **Impact**: Negligible

**Recommendation**: No rate limiting needed.

---

## Security Considerations

### No Sensitive Data in Discovery

**Risk**: Discovery messages visible to all NATS subscribers  
**Mitigation**: Do not include API keys, tokens, or sensitive config

**Implementation**:
- Exclude `api_key` from LLM provider info
- Exclude any credentials
- Include only public metadata

### Heartbeat Information Disclosure

**Risk**: Heartbeats reveal service health and metrics  
**Mitigation**: Heartbeats on internal NATS only, not public

**Recommendation**: Ensure NATS not exposed publicly.

### Group Restart DoS

**Risk**: Malicious actor publishes group restart to crash services  
**Mitigation**: NATS access control, require authentication

**Recommendation**: Configure NATS ACLs to restrict who can publish to lifecycle subjects.

---

## Monitoring

### What to Monitor

**Service Availability**:
- Discovery announcements received on startup
- Heartbeats arriving consistently
- Health state not stuck in FAILING

**Health State Transitions**:
- Frequency of HEALTHY ↔ DEGRADED transitions
- Time spent in each state
- Patterns in component failures

**Metrics**:
- Messages processed per heartbeat
- Responses sent per heartbeat
- Error rate trends
- LLM provider availability

### Alerting Rules

**Critical Alerts**:
- No heartbeats for >30 seconds
- Health state = FAILING for >1 minute
- NATS connection lost

**Warning Alerts**:
- Health state = DEGRADED for >5 minutes
- Error rate >5% sustained
- LLM provider failures frequent

---

## Future Enhancements

### Phase 5.1: KeyValue Service Registry

**Goal**: Persist service information in NATS KV store.

**Implementation**:
- Write service info to `kv_kryten_services`
- Key: `llm:hostname`
- Value: Service metadata JSON
- Update on each heartbeat
- TTL = 30 seconds (auto-expire if service dies)

**Benefit**: Other services can query registry for available services.

### Phase 5.2: Prometheus Metrics

**Goal**: Export metrics for Prometheus scraping.

**Implementation**:
- Add HTTP server with `/metrics` endpoint
- Export counters, gauges, histograms
- Integrate with Prometheus/Grafana

**Benefit**: Rich dashboards and historical metrics.

### Phase 5.3: Distributed Tracing

**Goal**: Trace requests across services.

**Implementation**:
- Add OpenTelemetry instrumentation
- Propagate trace context in NATS headers
- Export to Jaeger/Zipkin

**Benefit**: Visualize request flow and debug performance.

---

## Conclusion

Phase 5 integrates kryten-llm into the Kryten ecosystem monitoring infrastructure using the proven patterns from kryten-py. By leveraging the existing `LifecycleEventPublisher` class, implementation is simplified to wrapping and configuring existing functionality.

**Key Success Factors**:
1. Use kryten-py library (don't reimplement)
2. Track component health accurately
3. Publish events at appropriate times
4. Handle graceful shutdown correctly
5. Test thoroughly with NATS monitoring

**Estimated Implementation Time**: 3-4 hours with tests.

**Next Phase**: Phase 6 - Refinement & Optimization
