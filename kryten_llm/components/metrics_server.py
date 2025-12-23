"""Prometheus metrics HTTP server for LLM service.

Uses BaseMetricsServer from kryten-py for the HTTP server infrastructure.
Provides /health and /metrics endpoints for observability.
"""

from kryten import BaseMetricsServer


class MetricsServer(BaseMetricsServer):
    """HTTP server exposing Prometheus metrics for kryten-llm.

    Extends kryten-py's BaseMetricsServer with LLM-specific metrics.
    Default port 28286 (userstats=28282, moderator=28284).
    """

    def __init__(self, app_reference, port: int = 28286):
        """Initialize metrics server.

        Args:
            app_reference: Reference to LLMService for accessing components
            port: HTTP port to listen on (default 28286)
        """
        super().__init__(
            service_name="llm",
            port=port,
            client=app_reference.client,
        )
        self.app = app_reference

    async def _collect_custom_metrics(self) -> list[str]:
        """Collect LLM-specific metrics."""
        lines = []

        # Message processing metrics
        if self.app.health_monitor:
            messages = self.app.health_monitor._messages_processed
            responses = self.app.health_monitor._responses_sent
            errors = self.app.health_monitor._errors_count

            lines.append("# HELP llm_messages_processed Total chat messages processed")
            lines.append("# TYPE llm_messages_processed counter")
            lines.append(f"llm_messages_processed {messages}")
            lines.append("")

            lines.append("# HELP llm_responses_sent Total LLM responses sent to chat")
            lines.append("# TYPE llm_responses_sent counter")
            lines.append(f"llm_responses_sent {responses}")
            lines.append("")

            lines.append("# HELP llm_errors_total Total errors encountered")
            lines.append("# TYPE llm_errors_total counter")
            lines.append(f"llm_errors_total {errors}")
            lines.append("")

            # LLM provider status (per provider)
            for provider, status in self.app.health_monitor._provider_status.items():
                status_val = 1 if status == "ok" else (0 if status == "failed" else -1)
                lines.append(f"# HELP llm_provider_status Provider health status (1=ok, 0=failed, -1=unknown)")
                lines.append(f"# TYPE llm_provider_status gauge")
                lines.append(f'llm_provider_status{{provider="{provider}"}} {status_val}')
                lines.append("")

        # Rate limiter stats
        if self.app.rate_limiter:
            lines.append("# HELP llm_rate_limited_total Messages blocked by rate limiter")
            lines.append("# TYPE llm_rate_limited_total counter")
            lines.append(f"llm_rate_limited_total {getattr(self.app.rate_limiter, '_blocked_count', 0)}")
            lines.append("")

        # Spam detector stats
        if self.app.spam_detector:
            lines.append("# HELP llm_spam_detected_total Messages flagged as spam")
            lines.append("# TYPE llm_spam_detected_total counter")
            lines.append(f"llm_spam_detected_total {getattr(self.app.spam_detector, '_spam_count', 0)}")
            lines.append("")

        # Context log size
        if self.app.command_handler:
            lines.append("# HELP llm_context_log_size Current entries in context log buffer")
            lines.append("# TYPE llm_context_log_size gauge")
            lines.append(f"llm_context_log_size {len(self.app.command_handler._context_log)}")
            lines.append("")

        # Trigger stats
        if self.app.trigger_engine:
            lines.append("# HELP llm_triggers_configured Number of configured triggers")
            lines.append("# TYPE llm_triggers_configured gauge")
            lines.append(f"llm_triggers_configured {len(self.app.trigger_engine.triggers)}")
            lines.append("")

        return lines

    async def _get_health_details(self) -> dict:
        """Get LLM-specific health details."""
        details: dict[str, str | int | bool | float] = {}

        # Service info
        details["personality"] = self.app.config.personality.character_name
        details["default_provider"] = self.app.config.default_provider
        details["dry_run"] = self.app.config.testing.dry_run

        # Message stats
        if self.app.health_monitor:
            details["messages_processed"] = self.app.health_monitor._messages_processed
            details["responses_sent"] = self.app.health_monitor._responses_sent
            details["errors_count"] = self.app.health_monitor._errors_count

            # Provider status summary
            providers_ok = sum(1 for s in self.app.health_monitor._provider_status.values() if s == "ok")
            providers_failed = sum(1 for s in self.app.health_monitor._provider_status.values() if s == "failed")
            details["providers_ok"] = providers_ok
            details["providers_failed"] = providers_failed

        # Trigger stats
        if self.app.trigger_engine:
            details["triggers_configured"] = len(self.app.trigger_engine.triggers)

        # Context log size
        if self.app.command_handler:
            details["context_log_size"] = len(self.app.command_handler._context_log)

        # LLM provider configuration
        details["providers_configured"] = len(self.app.config.llm_providers)

        return details
