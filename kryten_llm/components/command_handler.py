"""Command handler for kryten-llm service.

Handles request/reply commands on kryten.llm.command subject.
Provides system.ping, context logging, and other service management commands.
"""

import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from kryten import KrytenClient


@dataclass
class ContextLogEntry:
    """A logged context entry for an LLM request."""

    timestamp: datetime
    correlation_id: str | None
    username: str
    trigger_message: str
    trigger_type: str
    system_prompt: str
    user_prompt: str
    context_data: dict[str, Any]
    response: str | None = None
    provider: str | None = None
    model: str | None = None
    tokens_used: int = 0
    response_time: float = 0.0
    success: bool = True


class CommandHandler:
    """Handles commands on kryten.llm.command subject."""

    def __init__(
        self,
        client: KrytenClient,
        service_name: str = "llm",
        version: str = "unknown",
        start_time: float | None = None,
        max_log_entries: int = 100,
        metrics_port: int | None = None,
        get_config: Callable[[], Any] | None = None,
        apply_config: Callable[[Any], Awaitable[None]] | None = None,
        reload_config: Callable[[], Awaitable[dict[str, Any]]] | None = None,
        get_rate_limit_snapshot: Callable[[], dict[str, Any]] | None = None,
    ):
        """Initialize command handler.

        Args:
            client: KrytenClient instance
            service_name: Service name for responses
            version: Service version
            start_time: Service start timestamp
            max_log_entries: Maximum context log entries to keep
            metrics_port: HTTP port for metrics endpoint (if enabled)
            get_config: Callback to retrieve the current config object
            apply_config: Callback to atomically apply a new config object
            reload_config: Callback to reload config from disk/source
            get_rate_limit_snapshot: Callback for live rate-limit counters
        """
        self.client = client
        self.service_name = service_name
        self.version = version
        self.start_time = start_time or time.time()
        self.metrics_port = metrics_port
        self.logger = logging.getLogger(__name__)

        # Context log - circular buffer of recent requests
        self._context_log: deque[ContextLogEntry] = deque(maxlen=max_log_entries)

        # Subscribers for live context streaming
        self._log_subscribers: list[str] = []

        self._get_config = get_config
        self._apply_config_cb = apply_config
        self._reload_config_cb = reload_config
        self._get_rate_limit_snapshot = get_rate_limit_snapshot

        self._subscription = None

    async def start(self) -> None:
        """Subscribe to command subject."""
        subject = "kryten.llm.command"
        self._subscription = await self.client.subscribe_request_reply(
            subject, self._handle_command
        )
        self.logger.info(f"Command handler subscribed to {subject}")

    async def stop(self) -> None:
        """Unsubscribe from command subject."""
        if self._subscription:
            # KrytenClient manages subscription cleanup
            self._subscription = None
        self.logger.info("Command handler stopped")

    def set_reload_callback(
        self, reload_callback: Callable[[], Awaitable[dict[str, Any]]] | None
    ) -> None:
        """Update runtime reload callback (used when reloader is initialized later)."""
        self._reload_config_cb = reload_callback

    def log_context(
        self,
        correlation_id: str | None,
        username: str,
        trigger_message: str,
        trigger_type: str,
        system_prompt: str,
        user_prompt: str,
        context_data: dict[str, Any],
        response: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tokens_used: int = 0,
        response_time: float = 0.0,
        success: bool = True,
    ) -> None:
        """Log a context entry for an LLM request.

        Args:
            correlation_id: Request correlation ID
            username: Username who triggered the request
            trigger_message: The message that triggered the request
            trigger_type: Type of trigger (mention, keyword, etc.)
            system_prompt: The system prompt sent to LLM
            user_prompt: The user prompt sent to LLM
            context_data: Context data (video, recent messages, etc.)
            response: LLM response (if available)
            provider: LLM provider used
            model: Model used
            tokens_used: Tokens consumed
            response_time: Response time in seconds
            success: Whether the request succeeded
        """
        entry = ContextLogEntry(
            timestamp=datetime.now(),
            correlation_id=correlation_id,
            username=username,
            trigger_message=trigger_message,
            trigger_type=trigger_type,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            context_data=context_data,
            response=response,
            provider=provider,
            model=model,
            tokens_used=tokens_used,
            response_time=response_time,
            success=success,
        )
        self._context_log.append(entry)

        # Publish to live stream subject (fire and forget)
        self._publish_log_entry(entry)

    def _publish_log_entry(self, entry: ContextLogEntry) -> None:
        """Publish a log entry to the live stream subject."""
        import asyncio

        try:
            # Convert entry to dict for publishing
            data = {
                "timestamp": entry.timestamp.isoformat(),
                "correlation_id": entry.correlation_id,
                "username": entry.username,
                "trigger_message": entry.trigger_message,
                "trigger_type": entry.trigger_type,
                "system_prompt_preview": (
                    entry.system_prompt[:200] + "..."
                    if len(entry.system_prompt) > 200
                    else entry.system_prompt
                ),
                "user_prompt_preview": (
                    entry.user_prompt[:500] + "..."
                    if len(entry.user_prompt) > 500
                    else entry.user_prompt
                ),
                "context_summary": {
                    "video_title": (
                        entry.context_data.get("current_video", {}).get("title")
                        if entry.context_data.get("current_video")
                        else None
                    ),
                    "message_count": len(entry.context_data.get("recent_messages", [])),
                },
                "response_preview": (
                    entry.response[:300] + "..."
                    if entry.response and len(entry.response) > 300
                    else entry.response
                ),
                "provider": entry.provider,
                "model": entry.model,
                "tokens_used": entry.tokens_used,
                "response_time": entry.response_time,
                "success": entry.success,
            }

            # Publish to stream subject (non-blocking)
            asyncio.create_task(self.client.publish("kryten.llm.context.log", data))
        except Exception as e:
            self.logger.debug(f"Failed to publish log entry: {e}")

    async def _handle_command(self, request: dict) -> dict:
        """Handle incoming command requests.

        Args:
            request: Command request dict

        Returns:
            Response dict
        """
        command = request.get("command", "")

        if not command:
            return {
                "service": self.service_name,
                "success": False,
                "error": "Missing 'command' field",
            }

        # Check service routing
        service = request.get("service")
        if service and service not in ("llm", "system"):
            return {
                "service": self.service_name,
                "success": False,
                "error": f"Command intended for '{service}', not '{self.service_name}'",
            }

        # Dispatch command
        handlers = {
            "system.ping": self._handle_ping,
            "system.health": self._handle_health,
            "system.reload": self._handle_system_reload,
            "context.recent": self._handle_context_recent,
            "context.get": self._handle_context_get,
            "personality.get": self._handle_personality_get,
            "personality.update": self._handle_personality_update,
            "triggers.list": self._handle_triggers_list,
            "triggers.update": self._handle_triggers_update,
            "triggers.toggle": self._handle_triggers_toggle,
            "rate_limits.get": self._handle_rate_limits_get,
            "rate_limits.update": self._handle_rate_limits_update,
            "providers.list": self._handle_providers_list,
        }

        handler = handlers.get(command)
        if not handler:
            return {
                "service": self.service_name,
                "command": command,
                "success": False,
                "error": f"Unknown command: {command}",
            }

        try:
            result = await handler(request)
            return {
                "service": self.service_name,
                "command": command,
                "success": True,
                "data": result,
            }
        except Exception as e:
            self.logger.error(f"Error handling command '{command}': {e}", exc_info=True)
            return {
                "service": self.service_name,
                "command": command,
                "success": False,
                "error": str(e),
            }

    async def _handle_ping(self, request: dict) -> dict:
        """Handle system.ping command.

        Returns:
            Ping response with service info
        """
        uptime = time.time() - self.start_time

        response = {
            "pong": True,
            "service": self.service_name,
            "version": self.version,
            "uptime_seconds": uptime,
            "timestamp": datetime.now().isoformat(),
        }

        # Include metrics endpoint if configured
        if self.metrics_port:
            response["metrics_endpoint"] = f"http://localhost:{self.metrics_port}/metrics"

        return response

    async def _handle_health(self, request: dict) -> dict:
        """Handle system.health command.

        Returns:
            Health status
        """
        uptime = time.time() - self.start_time

        return {
            "status": "healthy",
            "service": self.service_name,
            "version": self.version,
            "uptime_seconds": uptime,
            "context_log_size": len(self._context_log),
        }

    async def _handle_context_recent(self, request: dict) -> dict:
        """Handle context.recent command - get recent context log entries.

        Args:
            request: May contain 'limit' (default 10)

        Returns:
            Recent log entries
        """
        limit = min(request.get("limit", 10), 50)

        entries = []
        for entry in list(self._context_log)[-limit:]:
            entries.append(
                {
                    "timestamp": entry.timestamp.isoformat(),
                    "correlation_id": entry.correlation_id,
                    "username": entry.username,
                    "trigger_message": entry.trigger_message[:100],
                    "trigger_type": entry.trigger_type,
                    "response_preview": entry.response[:100] if entry.response else None,
                    "provider": entry.provider,
                    "model": entry.model,
                    "tokens_used": entry.tokens_used,
                    "response_time": entry.response_time,
                    "success": entry.success,
                }
            )

        return {
            "entries": entries,
            "total": len(self._context_log),
        }

    async def _handle_context_get(self, request: dict) -> dict:
        """Handle context.get command - get full details for a specific entry.

        Args:
            request: Must contain 'correlation_id' or 'index'

        Returns:
            Full context entry details
        """
        correlation_id = request.get("correlation_id")
        index = request.get("index")

        entry = None

        if correlation_id:
            for e in self._context_log:
                if e.correlation_id == correlation_id:
                    entry = e
                    break
        elif index is not None:
            try:
                entries = list(self._context_log)
                if 0 <= index < len(entries):
                    entry = entries[index]
            except (IndexError, TypeError):
                pass

        if not entry:
            raise ValueError("Entry not found")

        return {
            "timestamp": entry.timestamp.isoformat(),
            "correlation_id": entry.correlation_id,
            "username": entry.username,
            "trigger_message": entry.trigger_message,
            "trigger_type": entry.trigger_type,
            "system_prompt": entry.system_prompt,
            "user_prompt": entry.user_prompt,
            "context_data": entry.context_data,
            "response": entry.response,
            "provider": entry.provider,
            "model": entry.model,
            "tokens_used": entry.tokens_used,
            "response_time": entry.response_time,
            "success": entry.success,
        }

    def _require_config(self) -> Any:
        """Return current config or raise if command handler was not wired for config ops."""
        if not self._get_config:
            raise RuntimeError("Configuration access is not available")
        return self._get_config()

    async def _apply_config(self, new_config: Any) -> None:
        """Apply a full config object through the service callback."""
        if not self._apply_config_cb:
            raise RuntimeError("Configuration updates are not enabled")
        await self._apply_config_cb(new_config)

    async def _handle_system_reload(self, request: dict) -> dict:
        """Handle system.reload by invoking configured reload callback."""
        if not self._reload_config_cb:
            raise RuntimeError("Hot reload is not configured for this service")
        return await self._reload_config_cb()

    async def _handle_personality_get(self, request: dict) -> dict:
        """Handle personality.get command."""
        config = self._require_config()
        return config.personality.model_dump()

    async def _handle_personality_update(self, request: dict) -> dict:
        """Handle personality.update command."""
        config = self._require_config()
        allowed_fields = {
            "character_name",
            "character_description",
            "personality_traits",
            "expertise",
            "response_style",
            "name_variations",
        }
        updates = {k: v for k, v in request.items() if k in allowed_fields}
        if not updates:
            raise ValueError("No personality fields provided to update")

        new_config = config.model_copy(deep=True)
        for field, value in updates.items():
            setattr(new_config.personality, field, value)

        await self._apply_config(new_config)
        return new_config.personality.model_dump()

    async def _handle_triggers_list(self, request: dict) -> dict:
        """Handle triggers.list command."""
        config = self._require_config()
        return {"triggers": [trigger.model_dump() for trigger in config.triggers]}

    async def _handle_triggers_update(self, request: dict) -> dict:
        """Handle triggers.update command."""
        config = self._require_config()
        trigger_name = request.get("name")
        if not trigger_name:
            raise ValueError("Missing required field: name")

        allowed_fields = {
            "patterns",
            "probability",
            "cooldown_seconds",
            "context",
            "response_style",
            "max_responses_per_hour",
            "priority",
            "enabled",
            "llm_provider",
            "preferred_provider",
        }
        updates = {k: v for k, v in request.items() if k in allowed_fields}
        if not updates:
            raise ValueError("No trigger fields provided to update")

        new_config = config.model_copy(deep=True)
        target_trigger = None
        for trigger in new_config.triggers:
            if trigger.name == trigger_name:
                target_trigger = trigger
                break

        if target_trigger is None:
            raise ValueError(f"Trigger not found: {trigger_name}")

        for field, value in updates.items():
            setattr(target_trigger, field, value)

        await self._apply_config(new_config)
        return target_trigger.model_dump()

    async def _handle_triggers_toggle(self, request: dict) -> dict:
        """Handle triggers.toggle command."""
        config = self._require_config()
        trigger_name = request.get("name")
        if not trigger_name:
            raise ValueError("Missing required field: name")

        new_config = config.model_copy(deep=True)
        target_trigger = None
        for trigger in new_config.triggers:
            if trigger.name == trigger_name:
                target_trigger = trigger
                break

        if target_trigger is None:
            raise ValueError(f"Trigger not found: {trigger_name}")

        target_trigger.enabled = not target_trigger.enabled
        await self._apply_config(new_config)

        return {
            "name": target_trigger.name,
            "enabled": target_trigger.enabled,
        }

    async def _handle_rate_limits_get(self, request: dict) -> dict:
        """Handle rate_limits.get command."""
        config = self._require_config()
        payload = {
            "config": config.rate_limits.model_dump(),
        }
        if self._get_rate_limit_snapshot:
            payload["live"] = self._get_rate_limit_snapshot()
        return payload

    async def _handle_rate_limits_update(self, request: dict) -> dict:
        """Handle rate_limits.update command."""
        config = self._require_config()
        allowed_fields = set(config.rate_limits.model_fields.keys())
        updates = {k: v for k, v in request.items() if k in allowed_fields}
        if not updates:
            raise ValueError("No rate limit fields provided to update")

        new_config = config.model_copy(deep=True)
        for field, value in updates.items():
            setattr(new_config.rate_limits, field, value)

        await self._apply_config(new_config)
        return new_config.rate_limits.model_dump()

    async def _handle_providers_list(self, request: dict) -> dict:
        """Handle providers.list command."""
        config = self._require_config()
        providers = []
        for name, provider in config.llm_providers.items():
            api_key = provider.api_key or ""
            masked_key = "" if not api_key else f"{api_key[:4]}..."
            providers.append(
                {
                    "name": name,
                    "type": provider.type,
                    "base_url": provider.base_url,
                    "model": provider.model,
                    "priority": provider.priority,
                    "max_tokens": provider.max_tokens,
                    "temperature": provider.temperature,
                    "timeout_seconds": provider.timeout_seconds,
                    "fallback": provider.fallback,
                    "api_key_masked": masked_key,
                    "is_default": name == config.default_provider,
                }
            )

        providers.sort(key=lambda p: p["priority"])
        return {
            "default_provider": config.default_provider,
            "default_provider_priority": config.default_provider_priority,
            "providers": providers,
        }
