"""Main service class for kryten-llm."""

import asyncio
import logging
import time
import uuid
from typing import Any

from kryten import ChatMessageEvent, KrytenClient, KrytenConfig  # type: ignore[import-untyped]
from kryten.subject_builder import build_subject  # type: ignore[import-untyped]

from kryten_llm.components import (
    ContextManager,
    LLMManager,
    MessageListener,
    PromptBuilder,
    RateLimiter,
    ResponseFormatter,
    ResponseLogger,
    TriggerEngine,
)
from kryten_llm.components.command_handler import CommandHandler
from kryten_llm.components.health_monitor import ServiceHealthMonitor
from kryten_llm.components.spam_detector import SpamDetector
from kryten_llm.components.validator import ResponseValidator
from kryten_llm.models.config import LLMConfig
from kryten_llm.models.phase3 import LLMRequest

logger = logging.getLogger(__name__)


class LLMService:
    """Kryten LLM Service using kryten-py infrastructure."""

    def __init__(self, config: LLMConfig):
        """Initialize the service.

        Args:
            config: Validated LLMConfig object
        """
        self.config = config

        # Use KrytenClient from kryten-py with KrytenConfig object instead of dictionary
        # Extract only the fields that KrytenConfig needs from LLMConfig
        kryten_config = KrytenConfig(
            nats=self.config.nats,
            channels=self.config.channels,
            service=self.config.service,
            retry_attempts=self.config.retry_attempts,
            retry_delay=self.config.retry_delay,
            handler_timeout=self.config.handler_timeout,
            max_concurrent_handlers=self.config.max_concurrent_handlers,
            log_level=self.config.log_level,
        )
        self.client = KrytenClient(kryten_config)

        # Phase 5: Service start time for uptime tracking
        self.start_time = time.time()

        self._shutdown_event = asyncio.Event()

        # Phase 1 components
        self.listener = MessageListener(config)
        self.trigger_engine = TriggerEngine(config)
        self.prompt_builder = PromptBuilder(config)
        self.response_formatter = ResponseFormatter(config)

        # Phase 2 components
        self.rate_limiter = RateLimiter(config)

        # Phase 3 components
        self.context_manager = ContextManager(config)
        self.llm_manager = LLMManager(config)
        self.response_logger = ResponseLogger(config)

        # Phase 4 components
        self.validator = ResponseValidator(config.validation)
        self.spam_detector = SpamDetector(config.spam_detection)

        # Phase 5 components
        self.health_monitor: ServiceHealthMonitor | None = None  # Initialized after NATS connection

        # Command handler for request/reply (initialized after NATS connection)
        self.command_handler: CommandHandler | None = None

        # Metrics HTTP server (initialized after NATS connection)
        self.metrics_server = None

    async def start(self) -> None:
        """Start the service."""
        logger.info("Starting LLM service")

        if self.config.testing.dry_run:
            logger.warning("⚠ DRY RUN MODE - Responses will NOT be sent to chat")

        logger.info(f"Bot personality: {self.config.personality.character_name}")
        logger.info(f"Default LLM provider: {self.config.default_provider}")
        logger.info(f"Triggers configured: {len(self.config.triggers)}")

        # Register event handlers BEFORE connect (kryten-py pattern)
        @self.client.on("chatmsg")
        async def handle_chat(event):
            await self._handle_chat_message(event)

        @self.client.on("changemedia")
        async def handle_media_change(event):
            await self.context_manager._handle_video_change(event)
            await self._handle_media_change_trigger(event)

        # Connect to NATS - KrytenClient handles lifecycle/heartbeats automatically
        # based on the 'service' config we provide via model_dump()
        await self.client.connect()

        # Load initial video state from KV store before processing any messages
        await self.context_manager.load_initial_state(self.client)
        await self.trigger_engine.load_media_state(self.client)

        # Sync TriggerEngine with actual current media (REQ: Fix previous media tracking)
        # If we have a current video, ensure TriggerEngine knows about it so it becomes
        # 'previous' when the next change happens.
        if self.context_manager.current_video:
            await self.trigger_engine.sync_state_from_context(
                self.context_manager.current_video, self.client
            )

        # Subscribe to robot startup - re-announce when robot starts
        await self.client.subscribe("kryten.lifecycle.robot.startup", self._handle_robot_startup)
        logger.info("Subscribed to kryten.lifecycle.robot.startup")

        # Phase 5: Initialize health monitor for internal tracking
        self.health_monitor = ServiceHealthMonitor(
            config=self.config.service_metadata, logger=logger
        )

        # Phase 5: Update initial NATS health status
        self.health_monitor.update_component_health("nats", True, "Connected to NATS")

        # Initialize command handler for request/reply commands
        from kryten_llm import __version__
        metrics_port = self.config.metrics.port if self.config.metrics.enabled else None
        self.command_handler = CommandHandler(
            client=self.client,
            service_name="llm",
            version=__version__,
            start_time=self.start_time,
            metrics_port=metrics_port,
        )
        await self.command_handler.start()
        logger.info("Command handler started on kryten.llm.command")

        # Start metrics HTTP server if enabled
        if self.config.metrics.enabled:
            from kryten_llm.components.metrics_server import MetricsServer
            self.metrics_server = MetricsServer(self, port=self.config.metrics.port)
            await self.metrics_server.start()
            logger.info(
                f"Metrics server started on http://{self.config.metrics.host}:{self.config.metrics.port}"
            )

        # Use KrytenClient's built-in lifecycle publisher
        self.lifecycle = self.client.lifecycle

        # Phase 5: Register group restart callback (REQ-008)
        if self.lifecycle:
            self.lifecycle.on_restart_notice(self._handle_group_restart)

        logger.info("ContextManager initialized for video tracking")
        logger.info("LLM service started and ready")

    async def stop(self, reason: str = "Normal shutdown") -> None:
        """Stop the service with graceful shutdown.

        Phase 5 Implementation (REQ-007).

        Args:
            reason: Shutdown reason
        """
        logger.info(f"Stopping LLM service: {reason}")
        self._shutdown_event.set()

        # Stop metrics server
        if self.metrics_server:
            try:
                await self.metrics_server.stop()
                logger.info("Metrics server stopped")
            except RuntimeError as e:
                # Suppress "Site is not registered in runner" error during shutdown
                # This is a harmless race condition in aiohttp/kryten shutdown
                if "not registered in runner" not in str(e):
                    logger.warning(f"Error stopping metrics server: {e}")
            except Exception as e:
                logger.warning(f"Error stopping metrics server: {e}")

        # Stop command handler
        if self.command_handler:
            await self.command_handler.stop()

        # KrytenClient.disconnect() handles lifecycle shutdown automatically
        # Disconnect from NATS
        await self.client.disconnect()

        logger.info("LLM service stopped")

    async def wait_for_shutdown(self) -> None:
        """Wait for shutdown signal."""
        await self._shutdown_event.wait()

    async def _handle_media_change_trigger(self, event: Any) -> None:
        """Handle media change trigger logic."""
        # Convert event to dict for TriggerEngine
        data = {
            "title": event.title,
            "duration": event.duration,
            "type": event.media_type,
        }

        trigger_result = await self.trigger_engine.check_media_change(data, self.client)
        if not trigger_result:
            return

        logger.info(f"Media change triggered: {trigger_result.context}")

        # Build Prompt
        system_prompt = self.prompt_builder.build_system_prompt()
        # TriggerResult.context contains the template data dict
        user_prompt = self.prompt_builder.build_media_change_prompt(
            trigger_result.context, trigger_result.history
        )

        # Generate Response
        try:
            llm_request = LLMRequest(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                preferred_provider=None,  # Use configured priority order
            )
            response = await self.llm_manager.generate_response(llm_request)
        except Exception as e:
            logger.error(f"Failed to generate response for media trigger: {e}")
            return

        if not response:
            return

        # Validate
        validation_result = self.validator.validate_response(
            response.content, user_prompt, context=trigger_result.context
        )
        if not validation_result.valid:
            logger.warning(f"Media trigger response invalid: {validation_result.reason}")
            return

        # Format
        formatted_messages = self.response_formatter.format_response(response.content)

        # Send
        for msg in formatted_messages:
            if not self.config.testing.dry_run:
                channel_config = self.config.channels[0]
                channel_name = (
                    channel_config.channel
                    if hasattr(channel_config, "channel")
                    else channel_config.get("channel")
                )
                try:
                    await self.client.send_chat(channel_name, msg)
                    logger.info(f"Sent media trigger response to {channel_name}: {msg}")
                except Exception as e:
                    logger.error(f"Failed to send message to {channel_name}: {e}")
            else:
                logger.info(f"[DRY RUN] Would send to channel: {msg}")

    async def _handle_chat_message(self, event: ChatMessageEvent) -> None:
        """Handle chatMsg events using typed ChatMessageEvent from kryten-py.

        Processing pipeline (Phase 4 enhanced):
        1. Filter message (MessageListener)
        2. Add to context (ContextManager)
        3. Check triggers (TriggerEngine)
        4. Check spam detection (SpamDetector - NEW Phase 4)
        5. Check rate limits (RateLimiter)
        6. Get context (ContextManager)
        7. Build prompts (PromptBuilder)
        8. Generate response (LLMManager)
        9. Validate response (ResponseValidator - NEW Phase 4)
        10. Format response (ResponseFormatter - ENHANCED Phase 4)
        11. Send to chat or log (based on dry_run)
        12. Record message for spam tracking (SpamDetector - NEW Phase 4)
        13. Record response (RateLimiter)
        14. Log response (ResponseLogger)

        Args:
            event: ChatMessageEvent from kryten-py with typed fields
        """
        # Convert ChatMessageEvent to dict format expected by components
        # TODO: Refactor components to use typed events directly
        data = {
            "username": event.username,
            "msg": event.message,
            "time": int(event.timestamp.timestamp()),
            "meta": {"rank": event.rank},
            "channel": event.channel,
            "domain": event.domain,
        }
        # Generate correlation ID for error tracking (REQ-026)
        correlation_id = (
            self._generate_correlation_id()
            if self.config.error_handling.generate_correlation_ids
            else None
        )

        # Phase 5: Track message processed (REQ-010)
        if self.health_monitor:
            self.health_monitor.record_message_processed()

        filtered = None
        try:
            # 1. Filter message
            filtered = await self.listener.filter_message(data)
            if not filtered:
                return

            # 2. Add message to context (Phase 3)
            # ContextManager will exclude bot's own messages automatically
            self.context_manager.add_chat_message(filtered["username"], filtered["msg"])

            # 3. Check triggers (mentions + trigger words with probability)
            trigger_result = await self.trigger_engine.check_triggers(filtered)
            if not trigger_result:
                return

            logger.info(
                f"Triggered by {trigger_result.trigger_type} '{trigger_result.trigger_name}': "
                f"{filtered['username']}"
            )

            # 4. Check spam detection (Phase 4 - REQ-016 through REQ-022)
            rank = filtered.get("meta", {}).get("rank", 1)
            mention_count = 1 if trigger_result.trigger_type == "mention" else 0
            spam_check = self.spam_detector.check_spam(
                filtered["username"],
                filtered["msg"],
                user_rank=rank,
                mention_count=mention_count,
            )

            if spam_check.is_spam:
                logger.warning(
                    f"[{correlation_id}] Spam detected from "
                    f"{filtered['username']}: {spam_check.reason}"
                )
                # Don't process message further, but record for tracking
                self.spam_detector.record_message(
                    filtered["username"],
                    filtered["msg"],
                    rank,
                    mention_count,
                )
                return

            # 5. Check rate limits (Phase 2)
            rate_limit_decision = await self.rate_limiter.check_rate_limit(
                filtered["username"], trigger_result, rank
            )

            if not rate_limit_decision.allowed:
                logger.info(
                    f"[{correlation_id}] Rate limit blocked response: {rate_limit_decision.reason} "
                    f"(retry in {rate_limit_decision.retry_after}s)"
                )
                # Still log the blocked attempt
                await self.response_logger.log_response(
                    filtered["username"],
                    trigger_result,
                    filtered["msg"],
                    "",  # No LLM response
                    [],
                    rate_limit_decision,
                    False,
                )
                return

            # 6. Get context (Phase 3)
            context = self.context_manager.get_context()

            # Debug: Log context state
            logger.debug(
                f"[{correlation_id}] Context for prompt: "
                f"video={context.get('current_video', {}).get('title') if context.get('current_video') else None}, "
                f"chat_messages={len(context.get('recent_messages', []))}"
            )

            # 7. Build prompts (Phase 3)
            system_prompt = self.prompt_builder.build_system_prompt()
            user_prompt = self.prompt_builder.build_user_prompt(
                filtered["username"],
                trigger_result.cleaned_message or filtered["msg"],
                trigger_result.context,  # Phase 2 trigger context
                context,  # Phase 3 video + chat context
            )

            # Debug: Log user prompt for troubleshooting
            logger.debug(f"[{correlation_id}] User prompt:\n{user_prompt}")

            # 8. Generate response (Phase 3)
            # Get temperature/max_tokens from default provider config
            default_provider = self.config.llm_providers.get(self.config.default_provider)
            temperature = default_provider.temperature if default_provider else 0.8
            max_tokens = default_provider.max_tokens if default_provider else 256

            llm_request = LLMRequest(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                preferred_provider=(
                    trigger_result.preferred_provider
                    if hasattr(trigger_result, "preferred_provider")
                    else None
                ),
            )

            llm_response_obj = await self.llm_manager.generate_response(llm_request)

            if not llm_response_obj:
                logger.error(f"[{correlation_id}] LLM failed to generate response")

                # Phase 5: Record provider failure if we know which one failed
                # Note: llm_manager should ideally tell us which provider failed
                # For now, we'll record this as a general error
                if self.health_monitor:
                    self.health_monitor.record_error()

                await self.response_logger.log_response(
                    filtered["username"],
                    trigger_result,
                    filtered["msg"],
                    "",
                    [],
                    rate_limit_decision,
                    False,
                )
                return

            # Extract content from LLMResponse
            llm_response = llm_response_obj.content

            # Log context for debugging/monitoring via command handler
            if self.command_handler:
                self.command_handler.log_context(
                    correlation_id=correlation_id,
                    username=filtered["username"],
                    trigger_message=filtered["msg"],
                    trigger_type=trigger_result.trigger_type,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    context_data=context,
                    response=llm_response,
                    provider=llm_response_obj.provider_used,
                    model=llm_response_obj.model_used,
                    tokens_used=llm_response_obj.tokens_used,
                    response_time=llm_response_obj.response_time,
                    success=True,
                )

            # Phase 5: Record successful provider API call
            if self.health_monitor and llm_response_obj.provider_used:
                self.health_monitor.record_provider_success(llm_response_obj.provider_used)

            # Log provider metrics
            logger.info(
                f"[{correlation_id}] LLM response from "
                f"{llm_response_obj.provider_used}/{llm_response_obj.model_used} "
                f"({llm_response_obj.tokens_used} tokens, "
                f"{llm_response_obj.response_time:.2f}s)"
            )

            # 9. Validate response (Phase 4 - REQ-009 through REQ-015)
            validation = self.validator.validate(llm_response, filtered["msg"], context)
            if not validation.valid:
                logger.warning(
                    f"[{correlation_id}] Response validation failed: {validation.reason} "
                    f"(severity: {validation.severity})"
                )
                await self.response_logger.log_response(
                    filtered["username"],
                    trigger_result,
                    filtered["msg"],
                    llm_response,
                    [],
                    rate_limit_decision,
                    False,
                )
                return

            # 10. Format response (Phase 4 - REQ-001 through REQ-008)
            formatted_parts = self.response_formatter.format_response(llm_response)

            if not formatted_parts:
                logger.warning(f"[{correlation_id}] Formatter returned empty response")
                await self.response_logger.log_response(
                    filtered["username"],
                    trigger_result,
                    filtered["msg"],
                    llm_response,
                    [],
                    rate_limit_decision,
                    False,
                )
                return

            # 11. Send to chat or log
            sent = False
            for i, part in enumerate(formatted_parts):
                if self.config.testing.dry_run:
                    logger.info(f"[{correlation_id}] [DRY RUN] Would send: {part}")
                else:
                    channel_config = self.config.channels[0]
                    await self.client.send_chat(
                        channel_config.channel, part, domain=channel_config.domain
                    )
                    logger.info(
                        f"[{correlation_id}] Sent response part {i+1}/{len(formatted_parts)}"
                    )
                    sent = True

                # Delay between parts
                if i < len(formatted_parts) - 1:
                    await asyncio.sleep(self.config.message_processing.split_delay_seconds)

            # 12. Record message for spam tracking (Phase 4 - REQ-016)
            self.spam_detector.record_message(
                filtered["username"], filtered["msg"], rank, mention_count
            )

            # 13. Record response (update rate limit state)
            if sent or not self.config.testing.dry_run:
                await self.rate_limiter.record_response(filtered["username"], trigger_result)

                # Phase 5: Track successful response sent
                if self.health_monitor:
                    self.health_monitor.record_response_sent()

            # 14. Log response
            await self.response_logger.log_response(
                filtered["username"],
                trigger_result,
                filtered["msg"],
                llm_response,
                formatted_parts,
                rate_limit_decision,
                sent,
            )

        except Exception as e:
            # Phase 5: Track error
            if self.health_monitor:
                self.health_monitor.record_error()

            # Phase 4 error handling (REQ-023 through REQ-028)
            username = filtered.get("username", "unknown") if filtered else "unknown"
            msg = filtered.get("msg", "") if filtered else ""
            self._handle_error(e, username, msg, correlation_id)

    def _generate_correlation_id(self) -> str:
        """Generate unique correlation ID for request tracking.

        Implements REQ-026 from Phase 4 specification.

        Returns:
            Unique correlation ID (e.g., "msg-a1b2c3d4e5f6")
        """
        return f"msg-{uuid.uuid4().hex[:12]}"

    def _handle_error(
        self, error: Exception, username: str, message: str, correlation_id: str | None
    ):
        """Handle errors with comprehensive logging and optional fallback.

        Implements REQ-023 through REQ-028 from Phase 4 specification.

        Args:
            error: Exception that occurred
            username: User who sent message
            message: Original message
            correlation_id: Correlation ID for tracking
        """
        log_extra = {
            "username": username,
            "original_message": message,
            "error_type": type(error).__name__,
        }

        if correlation_id:
            log_extra["correlation_id"] = correlation_id

        if self.config.error_handling.log_full_context:
            logger.error(
                f"[{correlation_id}] Error processing message from {username}: {message}",
                exc_info=True,
                extra=log_extra,
            )
        else:
            logger.error(
                f"[{correlation_id}] Error processing message from {username}: "
                f"{type(error).__name__}",
                extra=log_extra,
            )

        # Optional: Send fallback response (REQ-028)
        # Note: This would need to be async, so for now just log
        # In a full implementation, this method should be async or queue a fallback task
        if self.config.error_handling.enable_fallback_responses:
            logger.info(
                f"[{correlation_id}] Fallback responses enabled but not implemented in sync method"
            )

    async def _handle_discovery_poll(self, msg: Any) -> None:
        """Handle discovery poll request.

        Phase 5 Implementation (REQ-005).

        Args:
            msg: NATS message
        """
        logger.info("Discovery poll received, re-announcing service")

        if self.config.service_metadata.enable_service_discovery and self.lifecycle:
            await self.lifecycle.publish_startup(
                personality=self.config.personality.character_name,
                providers_configured=len(self.config.llm_providers),
                triggers_loaded=len(self.config.triggers),
                re_announcement=True,
            )

    async def _handle_robot_startup(self, msg: Any) -> None:
        """Handle robot startup notification.

        Phase 5 Implementation (REQ-006).

        Args:
            msg: NATS message
        """
        logger.info("Robot startup detected, re-announcing service")

        if self.config.service_metadata.enable_service_discovery and self.lifecycle:
            await self.lifecycle.publish_startup(
                personality=self.config.personality.character_name,
                providers_configured=len(self.config.llm_providers),
                triggers_loaded=len(self.config.triggers),
                re_announcement=True,
            )

    async def _handle_group_restart(self, data: dict) -> None:
        """Handle group restart notice.

        Phase 5 Implementation (REQ-008).

        Args:
            data: Restart notice data
        """
        delay = data.get("delay_seconds", 5)
        reason = data.get("reason", "Group restart")

        logger.warning(f"Group restart requested: {reason}. Shutting down in {delay}s...")

        # Wait for delay period
        await asyncio.sleep(delay)

        # Initiate graceful shutdown
        await self.stop(reason=f"Group restart: {reason}")

    async def reload_config(self, new_config: "LLMConfig") -> None:
        """Reload configuration with hot-swappable components.

        Phase 6: Hot-reload support for configuration changes without restart.

        Only safe changes are applied:
        - Trigger configurations
        - Rate limits
        - Personality settings
        - Spam detection settings
        - LLM provider settings

        Unsafe changes (NATS, channels) require restart.

        Args:
            new_config: New validated configuration
        """

        logger.info("Applying new configuration...")
        old_config = self.config

        try:
            # Update config reference
            self.config = new_config

            # Rebuild trigger engine with new patterns (Phase 6 pattern caching)
            self.trigger_engine = TriggerEngine(new_config)
            logger.info(f"TriggerEngine rebuilt with {len(self.trigger_engine.triggers)} triggers")

            # Rebuild rate limiter (preserves current state)
            # Note: RateLimiter tracks state internally, new instance loses history
            # For production, consider preserving state
            self.rate_limiter = RateLimiter(new_config)
            logger.info("RateLimiter rebuilt with new limits")

            # Update spam detector
            self.spam_detector = SpamDetector(new_config.spam_detection)
            logger.info("SpamDetector rebuilt with new settings")

            # Update prompt builder (uses personality config)
            self.prompt_builder = PromptBuilder(new_config)
            logger.info(f"PromptBuilder rebuilt for {new_config.personality.character_name}")

            # Update response formatter
            self.response_formatter = ResponseFormatter(new_config)

            # Update response validator
            self.validator = ResponseValidator(new_config.validation)

            # Update LLM manager with new providers
            self.llm_manager = LLMManager(new_config)
            logger.info(f"LLMManager rebuilt with {len(new_config.llm_providers)} providers")

            # Update context manager config (doesn't require rebuild)
            self.context_manager.config = new_config

            logger.info("Configuration hot-reload completed successfully")

        except Exception as e:
            # Rollback on error
            logger.error(f"Config reload failed, rolling back: {e}", exc_info=True)
            self.config = old_config
            raise
