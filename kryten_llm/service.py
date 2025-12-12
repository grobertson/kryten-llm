"""Main service class for kryten-llm."""

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from kryten import KrytenClient, LifecycleEventPublisher  # type: ignore[import-untyped]

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
from kryten_llm.components.health_monitor import ServiceHealthMonitor
from kryten_llm.components.heartbeat import HeartbeatPublisher
from kryten_llm.components.spam_detector import SpamDetector
from kryten_llm.components.validator import ResponseValidator
from kryten_llm.models.config import LLMConfig

logger = logging.getLogger(__name__)


class LLMService:
    """Kryten LLM Service using kryten-py infrastructure."""

    def __init__(self, config: LLMConfig):
        """Initialize the service.

        Args:
            config: Validated LLMConfig object
        """
        self.config = config

        # Use KrytenClient from kryten-py
        self.client = KrytenClient(self.config.model_dump())

        # Lifecycle event publisher for service discovery
        self.lifecycle: LifecycleEventPublisher | None = None  # Initialized after NATS connection

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
        self.heartbeat_publisher: HeartbeatPublisher | None = (
            None  # Initialized after NATS connection
        )

    async def start(self) -> None:
        """Start the service."""
        logger.info("Starting LLM service")

        if self.config.testing.dry_run:
            logger.warning("⚠ DRY RUN MODE - Responses will NOT be sent to chat")

        logger.info(f"Bot personality: {self.config.personality.character_name}")
        logger.info(f"Default LLM provider: {self.config.default_provider}")
        logger.info(f"Triggers configured: {len(self.config.triggers)}")

        # Connect to NATS
        await self.client.connect()

        # Phase 5: Initialize health monitor
        self.health_monitor = ServiceHealthMonitor(
            config=self.config.service_metadata, logger=logger
        )

        # Phase 5: Update initial NATS health status
        self.health_monitor.update_component_health("nats", True, "Connected to NATS")

        # Initialize lifecycle publisher (requires NATS connection)
        self.lifecycle = LifecycleEventPublisher(
            service_name=self.config.service_metadata.service_name,
            nats_client=self.client._nats,
            logger=logger,
            version=self.config.service_metadata.service_version,
        )
        await self.lifecycle.start()

        # Phase 5: Register group restart callback (REQ-008)
        self.lifecycle.on_restart_notice(self._handle_group_restart)

        # Phase 5: Initialize heartbeat publisher
        self.heartbeat_publisher = HeartbeatPublisher(
            config=self.config.service_metadata,
            health_monitor=self.health_monitor,
            nats_client=self.client._nats,
            logger=logger,
            start_time=self.start_time,
        )

        # Phase 5: Publish startup event (service discovery - REQ-001, REQ-004)
        if self.config.service_metadata.enable_service_discovery:
            await self.lifecycle.publish_startup(
                personality=self.config.personality.character_name,
                providers_configured=len(self.config.llm_providers),
                triggers_loaded=len(self.config.triggers),
            )

        # Phase 5: Start heartbeat publishing (REQ-002)
        await self.heartbeat_publisher.start()

        # Phase 5: Subscribe to discovery poll (REQ-005)
        await self.client._nats.subscribe(
            "kryten.service.discovery.poll", cb=self._handle_discovery_poll
        )

        # Phase 5: Subscribe to robot startup (REQ-006)
        await self.client._nats.subscribe(
            "kryten.lifecycle.robot.startup", cb=self._handle_robot_startup
        )

        # Subscribe to chatMsg events directly via NATS
        # Build subject: kryten.events.cytube.{domain}.{channel}.chatMsg
        channel_config = self.config.channels[0]  # Use first configured channel
        subject = (
            f"kryten.events.cytube.{channel_config['domain']}.{channel_config['channel']}.chatMsg"
        )
        await self.client._nats.subscribe(subject, cb=self._on_nats_message)
        logger.info(f"Subscribed to: {subject}")

        # Phase 3: Start ContextManager to track video changes
        await self.context_manager.start(self.client._nats)

        logger.info("LLM service started and ready")

    async def stop(self, reason: str = "Normal shutdown") -> None:
        """Stop the service with graceful shutdown.

        Phase 5 Implementation (REQ-007).

        Args:
            reason: Shutdown reason
        """
        logger.info(f"Stopping LLM service: {reason}")
        self._shutdown_event.set()

        # Phase 5: Stop heartbeat publishing
        if self.heartbeat_publisher:
            await self.heartbeat_publisher.stop()

        # Phase 5: Publish shutdown event (REQ-004)
        if self.lifecycle and self.health_monitor:
            await self.lifecycle.publish_shutdown(
                reason=reason,
                messages_processed=self.health_monitor._messages_processed,
                responses_sent=self.health_monitor._responses_sent,
            )
            await self.lifecycle.stop()

        # Phase 1: Components have no async cleanup needed

        # Disconnect from NATS
        await self.client.disconnect()

        logger.info("LLM service stopped")

    async def wait_for_shutdown(self) -> None:
        """Wait for shutdown signal."""
        await self._shutdown_event.wait()

    async def _on_nats_message(self, msg: Any) -> None:
        """Handle incoming NATS message and decode it."""
        try:
            data = json.loads(msg.data.decode())
            await self._handle_chat_message(msg.subject, data)
        except Exception as e:
            logger.error(f"Error decoding NATS message: {e}", exc_info=True)

    async def _handle_chat_message(self, subject: str, data: dict) -> None:
        """Handle chatMsg events.

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
        """
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

            # 7. Build prompts (Phase 3)
            system_prompt = self.prompt_builder.build_system_prompt()
            user_prompt = self.prompt_builder.build_user_prompt(
                filtered["username"],
                trigger_result.cleaned_message or filtered["msg"],
                trigger_result.context,  # Phase 2 trigger context
                context,  # Phase 3 video + chat context
            )

            # 8. Generate response (Phase 3)
            from kryten_llm.models.phase3 import LLMRequest

            # Get temperature/max_tokens from default provider config
            default_provider = self.config.llm_providers.get(self.config.default_provider)
            temperature = default_provider.temperature if default_provider else 0.8
            max_tokens = default_provider.max_tokens if default_provider else 256

            llm_request = LLMRequest(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                preferred_provider=trigger_result.preferred_provider
                if hasattr(trigger_result, "preferred_provider")
                else None,
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
                        channel_config["channel"], part, domain=channel_config["domain"]
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
            "message": message,
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
