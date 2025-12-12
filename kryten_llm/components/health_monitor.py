"""Service health monitoring for Phase 5.

Tracks health of individual components and determines overall service health.
"""

import logging
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

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
    - LLM providers (stateless API calls - ok/failed/unknown)
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
            component: Component name (e.g., "nats", "rate_limiter")
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
            if comp.name not in ["nats"]
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
        return socket.gethostname()
