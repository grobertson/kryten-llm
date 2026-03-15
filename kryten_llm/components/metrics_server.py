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
        """Collect LLM-specific metrics for Prometheus."""
        lines: list[str] = []
        hm = self.app.health_monitor

        if hm:
            self._emit_core_metrics(lines, hm)
            self._emit_provider_metrics(lines, hm)
            self._emit_trigger_metrics(lines, hm)
            self._emit_rate_limit_metrics(lines, hm)
            self._emit_token_metrics(lines, hm)
            self._emit_response_time_metrics(lines, hm)
            self._emit_response_length_metrics(lines, hm)
            self._emit_validation_metrics(lines, hm)
            self._emit_spam_metrics(lines, hm)
            self._emit_media_metrics(lines, hm)
            self._emit_user_metrics(lines, hm)

        # Component state gauges (from service components directly)
        self._emit_component_metrics(lines)

        return lines

    # ── Core Counters ───────────────────────────────────────────────

    def _emit_core_metrics(self, lines: list[str], hm) -> None:
        lines.append("# HELP llm_messages_processed_total Total chat messages processed")
        lines.append("# TYPE llm_messages_processed_total counter")
        lines.append(f"llm_messages_processed_total {hm._messages_processed}")
        lines.append("")

        lines.append("# HELP llm_responses_sent_total Total LLM responses sent to chat")
        lines.append("# TYPE llm_responses_sent_total counter")
        lines.append(f"llm_responses_sent_total {hm._responses_sent}")
        lines.append("")

        lines.append("# HELP llm_errors_total Total errors encountered")
        lines.append("# TYPE llm_errors_total counter")
        lines.append(f"llm_errors_total {hm._errors_count}")
        lines.append("")

        lines.append("# HELP llm_errors_last_5m Errors in the last 5 minutes")
        lines.append("# TYPE llm_errors_last_5m gauge")
        lines.append(f"llm_errors_last_5m {len(hm._errors_window)}")
        lines.append("")

        lines.append(
            "# HELP llm_error_rate Error rate (errors_5m / messages_processed)"
        )
        lines.append("# TYPE llm_error_rate gauge")
        lines.append(f"llm_error_rate {hm._get_error_rate():.6f}")
        lines.append("")

    # ── Provider Metrics ────────────────────────────────────────────

    def _emit_provider_metrics(self, lines: list[str], hm) -> None:
        lines.append(
            "# HELP llm_provider_status Provider health status (1=ok, 0=failed, -1=unknown)"
        )
        lines.append("# TYPE llm_provider_status gauge")
        for provider, status in hm._provider_status.items():
            status_val = 1 if status == "ok" else (0 if status == "failed" else -1)
            lines.append(f'llm_provider_status{{provider="{provider}"}} {status_val}')
        lines.append("")

        lines.append("# HELP llm_provider_requests_total Requests sent to each provider")
        lines.append("# TYPE llm_provider_requests_total counter")
        for provider, count in hm._provider_requests.items():
            lines.append(f'llm_provider_requests_total{{provider="{provider}"}} {count}')
        lines.append("")

        lines.append("# HELP llm_provider_failures_total Failed requests per provider")
        lines.append("# TYPE llm_provider_failures_total counter")
        for provider, count in hm._provider_failures.items():
            lines.append(f'llm_provider_failures_total{{provider="{provider}"}} {count}')
        lines.append("")

    # ── Trigger Metrics ─────────────────────────────────────────────

    def _emit_trigger_metrics(self, lines: list[str], hm) -> None:
        lines.append(
            "# HELP llm_trigger_checks_total Total trigger evaluation attempts"
        )
        lines.append("# TYPE llm_trigger_checks_total counter")
        lines.append(f"llm_trigger_checks_total {hm._trigger_checks}")
        lines.append("")

        lines.append("# HELP llm_trigger_fires_total Total triggers that fired")
        lines.append("# TYPE llm_trigger_fires_total counter")
        lines.append(f"llm_trigger_fires_total {hm._trigger_fires}")
        lines.append("")

        lines.append(
            "# HELP llm_trigger_fires_by_type_total Triggers fired by type"
        )
        lines.append("# TYPE llm_trigger_fires_by_type_total counter")
        for trigger_type, count in hm._trigger_type_counts.items():
            lines.append(
                f'llm_trigger_fires_by_type_total{{type="{trigger_type}"}} {count}'
            )
        lines.append("")

        lines.append(
            "# HELP llm_trigger_fires_by_name_total Triggers fired by name"
        )
        lines.append("# TYPE llm_trigger_fires_by_name_total counter")
        for name, count in hm._trigger_name_counts.items():
            lines.append(
                f'llm_trigger_fires_by_name_total{{name="{name}"}} {count}'
            )
        lines.append("")

    # ── Rate Limit & Cooldown Metrics ───────────────────────────────

    def _emit_rate_limit_metrics(self, lines: list[str], hm) -> None:
        lines.append(
            "# HELP llm_rate_limit_hits_total Total messages blocked by rate limiting"
        )
        lines.append("# TYPE llm_rate_limit_hits_total counter")
        lines.append(f"llm_rate_limit_hits_total {hm._rate_limit_hits_total}")
        lines.append("")

        lines.append(
            "# HELP llm_rate_limit_hits_by_reason_total Rate limit blocks by reason"
        )
        lines.append("# TYPE llm_rate_limit_hits_by_reason_total counter")
        for reason, count in hm._rate_limit_hits.items():
            safe_reason = reason.replace('"', '\\"')
            lines.append(
                f'llm_rate_limit_hits_by_reason_total{{reason="{safe_reason}"}} {count}'
            )
        lines.append("")

        lines.append(
            "# HELP llm_cooldown_hits_total Cooldown blocks by type"
        )
        lines.append("# TYPE llm_cooldown_hits_total counter")
        for cd_type, count in hm._cooldown_hits.items():
            lines.append(
                f'llm_cooldown_hits_total{{type="{cd_type}"}} {count}'
            )
        lines.append("")

        # Live rate limiter gauges
        if self.app.rate_limiter:
            rl = self.app.rate_limiter
            lines.append(
                "# HELP llm_rate_limit_global_minute Current responses in the 1-minute window"
            )
            lines.append("# TYPE llm_rate_limit_global_minute gauge")
            lines.append(
                f"llm_rate_limit_global_minute {len(rl.global_responses_minute)}"
            )
            lines.append("")

            lines.append(
                "# HELP llm_rate_limit_global_hour Current responses in the 1-hour window"
            )
            lines.append("# TYPE llm_rate_limit_global_hour gauge")
            lines.append(
                f"llm_rate_limit_global_hour {len(rl.global_responses_hour)}"
            )
            lines.append("")

            lines.append(
                "# HELP llm_rate_limit_global_max_minute Configured max responses per minute"
            )
            lines.append("# TYPE llm_rate_limit_global_max_minute gauge")
            lines.append(
                f"llm_rate_limit_global_max_minute {rl.rate_limits.global_max_per_minute}"
            )
            lines.append("")

            lines.append(
                "# HELP llm_rate_limit_global_max_hour Configured max responses per hour"
            )
            lines.append("# TYPE llm_rate_limit_global_max_hour gauge")
            lines.append(
                f"llm_rate_limit_global_max_hour {rl.rate_limits.global_max_per_hour}"
            )
            lines.append("")

            lines.append(
                "# HELP llm_rate_limit_user_max_hour Configured max responses per user per hour"
            )
            lines.append("# TYPE llm_rate_limit_user_max_hour gauge")
            lines.append(
                f"llm_rate_limit_user_max_hour {rl.rate_limits.user_max_per_hour}"
            )
            lines.append("")

            lines.append(
                "# HELP llm_rate_limit_tracked_users Number of users with active rate tracking"
            )
            lines.append("# TYPE llm_rate_limit_tracked_users gauge")
            lines.append(
                f"llm_rate_limit_tracked_users {len(rl.user_responses_hour)}"
            )
            lines.append("")

            lines.append(
                "# HELP llm_rate_limit_tracked_triggers Number of triggers with active rate tracking"
            )
            lines.append("# TYPE llm_rate_limit_tracked_triggers gauge")
            lines.append(
                f"llm_rate_limit_tracked_triggers {len(rl.trigger_responses_hour)}"
            )
            lines.append("")

    # ── Token Usage Metrics ─────────────────────────────────────────

    def _emit_token_metrics(self, lines: list[str], hm) -> None:
        lines.append(
            "# HELP llm_token_usage_total Total tokens consumed by provider and model"
        )
        lines.append("# TYPE llm_token_usage_total counter")
        for (provider, model), usage in hm._token_usage.items():
            lines.append(
                f'llm_token_usage_total{{provider="{provider}",model="{model}",type="prompt"}} {usage["prompt"]}'
            )
            lines.append(
                f'llm_token_usage_total{{provider="{provider}",model="{model}",type="completion"}} {usage["completion"]}'
            )
            lines.append(
                f'llm_token_usage_total{{provider="{provider}",model="{model}",type="total"}} {usage["total"]}'
            )
        lines.append("")

        lines.append(
            "# HELP llm_requests_by_model_total Requests handled by each provider/model"
        )
        lines.append("# TYPE llm_requests_by_model_total counter")
        for (provider, model), usage in hm._token_usage.items():
            lines.append(
                f'llm_requests_by_model_total{{provider="{provider}",model="{model}"}} {usage["requests"]}'
            )
        lines.append("")

        # Average tokens per request (useful for dashboards)
        lines.append(
            "# HELP llm_avg_tokens_per_request Average total tokens per request by provider/model"
        )
        lines.append("# TYPE llm_avg_tokens_per_request gauge")
        for (provider, model), usage in hm._token_usage.items():
            avg = usage["total"] / usage["requests"] if usage["requests"] > 0 else 0
            lines.append(
                f'llm_avg_tokens_per_request{{provider="{provider}",model="{model}"}} {avg:.1f}'
            )
        lines.append("")

        lines.append(
            "# HELP llm_avg_prompt_tokens Average prompt tokens per request"
        )
        lines.append("# TYPE llm_avg_prompt_tokens gauge")
        for (provider, model), usage in hm._token_usage.items():
            avg = usage["prompt"] / usage["requests"] if usage["requests"] > 0 else 0
            lines.append(
                f'llm_avg_prompt_tokens{{provider="{provider}",model="{model}"}} {avg:.1f}'
            )
        lines.append("")

        lines.append(
            "# HELP llm_avg_completion_tokens Average completion tokens per request"
        )
        lines.append("# TYPE llm_avg_completion_tokens gauge")
        for (provider, model), usage in hm._token_usage.items():
            avg = usage["completion"] / usage["requests"] if usage["requests"] > 0 else 0
            lines.append(
                f'llm_avg_completion_tokens{{provider="{provider}",model="{model}"}} {avg:.1f}'
            )
        lines.append("")

    # ── Response Time Metrics ───────────────────────────────────────

    def _emit_response_time_metrics(self, lines: list[str], hm) -> None:
        lines.append(
            "# HELP llm_response_time_seconds Response time percentiles by provider/model"
        )
        lines.append("# TYPE llm_response_time_seconds gauge")
        for (provider, model), times in hm._response_times.items():
            if not times:
                continue
            pcts = hm.get_response_time_percentiles(provider, model)
            lines.append(
                f'llm_response_time_seconds{{provider="{provider}",model="{model}",quantile="0.5"}} {pcts["p50"]:.4f}'
            )
            lines.append(
                f'llm_response_time_seconds{{provider="{provider}",model="{model}",quantile="0.9"}} {pcts["p90"]:.4f}'
            )
            lines.append(
                f'llm_response_time_seconds{{provider="{provider}",model="{model}",quantile="0.99"}} {pcts["p99"]:.4f}'
            )
            lines.append(
                f'llm_response_time_seconds{{provider="{provider}",model="{model}",quantile="avg"}} {pcts["avg"]:.4f}'
            )
        lines.append("")

    # ── Response Length Metrics ──────────────────────────────────────

    def _emit_response_length_metrics(self, lines: list[str], hm) -> None:
        lengths = hm._response_lengths
        if lengths:
            avg_len = sum(lengths) / len(lengths)
            max_len = max(lengths)
            min_len = min(lengths)
        else:
            avg_len = max_len = min_len = 0

        lines.append(
            "# HELP llm_response_length_chars_avg Average response length in characters"
        )
        lines.append("# TYPE llm_response_length_chars_avg gauge")
        lines.append(f"llm_response_length_chars_avg {avg_len:.1f}")
        lines.append("")

        lines.append(
            "# HELP llm_response_length_chars_max Maximum response length in characters"
        )
        lines.append("# TYPE llm_response_length_chars_max gauge")
        lines.append(f"llm_response_length_chars_max {max_len}")
        lines.append("")

        lines.append(
            "# HELP llm_response_length_chars_min Minimum response length in characters"
        )
        lines.append("# TYPE llm_response_length_chars_min gauge")
        lines.append(f"llm_response_length_chars_min {min_len}")
        lines.append("")

    # ── Validation Metrics ──────────────────────────────────────────

    def _emit_validation_metrics(self, lines: list[str], hm) -> None:
        lines.append(
            "# HELP llm_validation_failures_total Total response validation failures"
        )
        lines.append("# TYPE llm_validation_failures_total counter")
        lines.append(f"llm_validation_failures_total {hm._validation_failures_total}")
        lines.append("")

        lines.append(
            "# HELP llm_validation_failures_by_reason_total Validation failures by reason"
        )
        lines.append("# TYPE llm_validation_failures_by_reason_total counter")
        for reason, count in hm._validation_failures.items():
            safe_reason = reason.replace('"', '\\"')[:64]
            lines.append(
                f'llm_validation_failures_by_reason_total{{reason="{safe_reason}"}} {count}'
            )
        lines.append("")

    # ── Spam Metrics ────────────────────────────────────────────────

    def _emit_spam_metrics(self, lines: list[str], hm) -> None:
        lines.append(
            "# HELP llm_spam_detected_total Total messages flagged as spam"
        )
        lines.append("# TYPE llm_spam_detected_total counter")
        lines.append(f"llm_spam_detected_total {hm._spam_detected_total}")
        lines.append("")

        lines.append(
            "# HELP llm_spam_by_reason_total Spam detections by reason"
        )
        lines.append("# TYPE llm_spam_by_reason_total counter")
        for reason, count in hm._spam_by_reason.items():
            safe_reason = reason.replace('"', '\\"')[:64]
            lines.append(
                f'llm_spam_by_reason_total{{reason="{safe_reason}"}} {count}'
            )
        lines.append("")

    # ── Media Change Metrics ────────────────────────────────────────

    def _emit_media_metrics(self, lines: list[str], hm) -> None:
        lines.append(
            "# HELP llm_media_changes_total Total media changes observed"
        )
        lines.append("# TYPE llm_media_changes_total counter")
        lines.append(f"llm_media_changes_total {hm._media_changes_processed}")
        lines.append("")

        lines.append(
            "# HELP llm_media_changes_triggered_total Media changes that triggered a response"
        )
        lines.append("# TYPE llm_media_changes_triggered_total counter")
        lines.append(f"llm_media_changes_triggered_total {hm._media_changes_triggered}")
        lines.append("")

    # ── Per-User Metrics ────────────────────────────────────────────

    def _emit_user_metrics(self, lines: list[str], hm) -> None:
        lines.append(
            "# HELP llm_responses_by_user_total Responses sent per user (top chatters)"
        )
        lines.append("# TYPE llm_responses_by_user_total counter")
        # Emit all tracked users
        for username, count in hm._user_response_counts.items():
            safe_user = username.replace('"', '\\"')
            lines.append(
                f'llm_responses_by_user_total{{user="{safe_user}"}} {count}'
            )
        lines.append("")

        lines.append(
            "# HELP llm_unique_users_interacted Total unique users the bot has responded to"
        )
        lines.append("# TYPE llm_unique_users_interacted gauge")
        lines.append(
            f"llm_unique_users_interacted {len(hm._user_response_counts)}"
        )
        lines.append("")

    # ── Component State Metrics ─────────────────────────────────────

    def _emit_component_metrics(self, lines: list[str]) -> None:
        # Context log size
        if self.app.command_handler:
            lines.append(
                "# HELP llm_context_log_size Current entries in context log buffer"
            )
            lines.append("# TYPE llm_context_log_size gauge")
            lines.append(
                f"llm_context_log_size {len(self.app.command_handler._context_log)}"
            )
            lines.append("")

        # Trigger configuration count
        if self.app.trigger_engine:
            lines.append(
                "# HELP llm_triggers_configured Number of configured triggers"
            )
            lines.append("# TYPE llm_triggers_configured gauge")
            lines.append(
                f"llm_triggers_configured {len(self.app.trigger_engine.triggers)}"
            )
            lines.append("")

        # Chat history buffer depth
        if self.app.context_manager:
            history = getattr(self.app.context_manager, "_chat_history", [])
            lines.append(
                "# HELP llm_chat_history_size Messages in the chat history buffer"
            )
            lines.append("# TYPE llm_chat_history_size gauge")
            lines.append(f"llm_chat_history_size {len(history)}")
            lines.append("")

        # Configured providers count
        lines.append(
            "# HELP llm_providers_configured Number of configured LLM providers"
        )
        lines.append("# TYPE llm_providers_configured gauge")
        lines.append(
            f"llm_providers_configured {len(self.app.config.llm_providers)}"
        )
        lines.append("")

        # Config-derived guide marks (useful for Grafana thresholds)
        if self.app.config.formatting:
            lines.append(
                "# HELP llm_config_max_message_length Configured max message length"
            )
            lines.append("# TYPE llm_config_max_message_length gauge")
            lines.append(
                f"llm_config_max_message_length {self.app.config.formatting.max_message_length}"
            )
            lines.append("")

        if self.app.config.validation:
            lines.append(
                "# HELP llm_config_validation_min_length Configured validation min length"
            )
            lines.append("# TYPE llm_config_validation_min_length gauge")
            lines.append(
                f"llm_config_validation_min_length {self.app.config.validation.min_length}"
            )
            lines.append("")

            lines.append(
                "# HELP llm_config_validation_max_length Configured validation max length"
            )
            lines.append("# TYPE llm_config_validation_max_length gauge")
            lines.append(
                f"llm_config_validation_max_length {self.app.config.validation.max_length}"
            )
            lines.append("")

        # Dry-run status
        lines.append(
            "# HELP llm_dry_run Whether service is in dry-run mode (1=yes, 0=no)"
        )
        lines.append("# TYPE llm_dry_run gauge")
        lines.append(
            f"llm_dry_run {1 if self.app.config.testing.dry_run else 0}"
        )
        lines.append("")

    async def _get_health_details(self) -> dict:
        """Get LLM-specific health details."""
        details: dict[str, str | int | bool | float] = {}

        # Service info
        details["personality"] = self.app.config.personality.character_name
        details["default_provider"] = self.app.config.default_provider
        details["dry_run"] = self.app.config.testing.dry_run

        hm = self.app.health_monitor
        if hm:
            details["messages_processed"] = hm._messages_processed
            details["responses_sent"] = hm._responses_sent
            details["errors_count"] = hm._errors_count

            # Provider status summary
            providers_ok = sum(
                1 for s in hm._provider_status.values() if s == "ok"
            )
            providers_failed = sum(
                1 for s in hm._provider_status.values() if s == "failed"
            )
            details["providers_ok"] = providers_ok
            details["providers_failed"] = providers_failed

            # Extended health info
            details["trigger_fires"] = hm._trigger_fires
            details["rate_limit_hits"] = hm._rate_limit_hits_total
            details["spam_detected"] = hm._spam_detected_total
            details["validation_failures"] = hm._validation_failures_total
            details["media_changes"] = hm._media_changes_processed
            details["unique_users"] = len(hm._user_response_counts)

        # Trigger stats
        if self.app.trigger_engine:
            details["triggers_configured"] = len(self.app.trigger_engine.triggers)

        # Context log size
        if self.app.command_handler:
            details["context_log_size"] = len(self.app.command_handler._context_log)

        # LLM provider configuration
        details["providers_configured"] = len(self.app.config.llm_providers)

        return details
