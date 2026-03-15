"""Service health monitoring for Phase 5.

Tracks health of individual components and determines overall service health.
Extended with comprehensive metrics for Prometheus/Grafana observability.
"""

import logging
import socket
from collections import defaultdict
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

        # --- Extended metrics ---

        # Trigger type counters: mention, trigger_word, auto_participation, media_change
        self._trigger_type_counts: dict[str, int] = defaultdict(int)

        # Per-trigger-name fire counts
        self._trigger_name_counts: dict[str, int] = defaultdict(int)

        # Per-user response counts
        self._user_response_counts: dict[str, int] = defaultdict(int)

        # Rate limit hit counters by reason
        self._rate_limit_hits: dict[str, int] = defaultdict(int)
        self._rate_limit_hits_total = 0

        # Cooldown hit counters by type
        self._cooldown_hits: dict[str, int] = defaultdict(int)

        # Token usage by provider/model: {(provider, model): {prompt, completion, total}}
        self._token_usage: dict[tuple[str, str], dict[str, int]] = defaultdict(
            lambda: {"prompt": 0, "completion": 0, "total": 0, "requests": 0}
        )

        # Response time tracking by provider/model: list of response times
        self._response_times: dict[tuple[str, str], list[float]] = defaultdict(list)

        # Response length (chars) tracking
        self._response_lengths: list[int] = []

        # Provider request counts (success/failure per provider)
        self._provider_requests: dict[str, int] = defaultdict(int)
        self._provider_failures: dict[str, int] = defaultdict(int)

        # Trigger probability: checked vs fired
        self._trigger_checks = 0
        self._trigger_fires = 0

        # Validation failure counters
        self._validation_failures: dict[str, int] = defaultdict(int)
        self._validation_failures_total = 0

        # Spam detection counters
        self._spam_detected_total = 0
        self._spam_by_reason: dict[str, int] = defaultdict(int)

        # Media change counters
        self._media_changes_processed = 0
        self._media_changes_triggered = 0

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
        self._provider_failures[provider_name] += 1
        self.logger.warning(f"Provider {provider_name} status: failed")

    def get_provider_status(self, provider_name: str) -> str:
        """Get current status of LLM provider.

        Args:
            provider_name: Name of the provider

        Returns:
            "ok", "failed", or "unknown"
        """
        return self._provider_status.get(provider_name, "unknown")

    # --- Extended recording methods ---

    def record_trigger_fired(self, trigger_type: str, trigger_name: str | None = None) -> None:
        """Record a trigger firing."""
        self._trigger_type_counts[trigger_type] += 1
        self._trigger_fires += 1
        if trigger_name:
            self._trigger_name_counts[trigger_name] += 1

    def record_trigger_check(self) -> None:
        """Record that a trigger check was performed (for probability tracking)."""
        self._trigger_checks += 1

    def record_user_response(self, username: str) -> None:
        """Record a response was sent to a specific user."""
        self._user_response_counts[username] += 1

    def record_rate_limit_hit(self, reason: str) -> None:
        """Record a rate limit hit by reason category."""
        self._rate_limit_hits[reason] += 1
        self._rate_limit_hits_total += 1

    def record_cooldown_hit(self, cooldown_type: str) -> None:
        """Record a cooldown block by type (global, user, mention, trigger)."""
        self._cooldown_hits[cooldown_type] += 1

    def record_llm_response(
        self,
        provider: str,
        model: str,
        response_time: float,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        response_length: int = 0,
    ) -> None:
        """Record detailed LLM response metrics."""
        key = (provider, model)
        self._provider_requests[provider] += 1

        if total_tokens is not None:
            self._token_usage[key]["total"] += total_tokens
        if prompt_tokens is not None:
            self._token_usage[key]["prompt"] += prompt_tokens
        if completion_tokens is not None:
            self._token_usage[key]["completion"] += completion_tokens
        self._token_usage[key]["requests"] += 1

        # Keep last 1000 response times for percentile calculations
        times = self._response_times[key]
        times.append(response_time)
        if len(times) > 1000:
            self._response_times[key] = times[-1000:]

        if response_length > 0:
            self._response_lengths.append(response_length)
            if len(self._response_lengths) > 1000:
                self._response_lengths = self._response_lengths[-1000:]

    def record_validation_failure(self, reason: str) -> None:
        """Record a validation failure by reason."""
        self._validation_failures[reason] += 1
        self._validation_failures_total += 1

    def record_spam_detected(self, reason: str) -> None:
        """Record spam detection event."""
        self._spam_detected_total += 1
        self._spam_by_reason[reason] += 1

    def record_media_change(self, triggered: bool) -> None:
        """Record a media change event."""
        self._media_changes_processed += 1
        if triggered:
            self._media_changes_triggered += 1

    def get_response_time_percentiles(
        self, provider: str, model: str
    ) -> dict[str, float]:
        """Calculate response time percentiles for a provider/model pair."""
        key = (provider, model)
        times = sorted(self._response_times.get(key, []))
        if not times:
            return {"p50": 0.0, "p90": 0.0, "p99": 0.0, "avg": 0.0}

        n = len(times)
        return {
            "p50": times[int(n * 0.50)] if n > 0 else 0.0,
            "p90": times[int(n * 0.90)] if n > 1 else times[-1],
            "p99": times[int(n * 0.99)] if n > 2 else times[-1],
            "avg": sum(times) / n,
        }

    def update_component_health(self, component: str, healthy: bool, message: str = "") -> None:
        """Update health status of a component.

        Args:
            component: Component name (e.g., "nats", "rate_limiter")
            healthy: Whether component is healthy
            message: Health status message
        """
        self._component_health[component] = ComponentHealth(
            name=component, healthy=healthy, message=message, last_check=datetime.now()
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
        _providers_ok = [name for name, status in self._provider_status.items() if status == "ok"]
        providers_failed = [
            name for name, status in self._provider_status.items() if status == "failed"
        ]
        _providers_unknown = [
            name for name, status in self._provider_status.items() if status == "unknown"
        ]
        all_providers_failed = len(self._provider_status) > 0 and len(providers_failed) == len(
            self._provider_status
        )

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
            timestamp=datetime.now(),
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
                "nats_connected": self._component_health.get(
                    "nats", ComponentHealth("nats", False, "", datetime.now())
                ).healthy,
                "llm_providers": llm_providers_status,
                "rate_limiter_active": self._component_health.get(
                    "rate_limiter", ComponentHealth("rate_limiter", True, "", datetime.now())
                ).healthy,
                "spam_detector_active": self._component_health.get(
                    "spam_detector", ComponentHealth("spam_detector", True, "", datetime.now())
                ).healthy,
                "messages_processed": health.metrics["messages_processed"],
                "responses_sent": health.metrics["responses_sent"],
                "errors_last_hour": health.metrics["errors_last_5min"],
            },
        }

    def _get_hostname(self) -> str:
        """Get system hostname."""
        return socket.gethostname()
