"""Main service class for kryten-llm."""

import asyncio
import logging
from pathlib import Path

from kryten import KrytenClient, LifecycleEventPublisher
from kryten_llm.models.config import LLMConfig
from kryten_llm.components import (
    MessageListener,
    TriggerEngine,
    LLMManager,
    PromptBuilder,
    ResponseFormatter,
    RateLimiter,
    ResponseLogger,
)


logger = logging.getLogger(__name__)


class LLMService:
    """Kryten LLM Service using kryten-py infrastructure."""

    def __init__(self, config: LLMConfig):
        """Initialize the service.
        
        Args:
            config: Validated LLMConfig object
        """
        self.config = config
        
        # Use KrytenClient from kryten-py (no need to build config dict)
        self.client = KrytenClient(config_dict=self.config.model_dump())
        
        # Lifecycle event publisher for service discovery
        self.lifecycle = None  # Initialized after NATS connection
        
        self._shutdown_event = asyncio.Event()
        
        # Phase 1 components
        self.listener = MessageListener(config)
        self.trigger_engine = TriggerEngine(config)
        self.llm_manager = LLMManager(config)
        self.prompt_builder = PromptBuilder(config)
        self.response_formatter = ResponseFormatter(config)
        
        # Phase 2 components
        self.rate_limiter = RateLimiter(config)
        self.response_logger = ResponseLogger(config)

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
        
        # Initialize lifecycle publisher (requires NATS connection)
        self.lifecycle = LifecycleEventPublisher(
            service_name="llm",
            nats_client=self.client._nats,
            logger=logger,
            version="0.1.0"  # TODO: Read from VERSION file
        )
        await self.lifecycle.start()
        
        # Publish startup event (service discovery)
        await self.lifecycle.publish_startup(
            personality=self.config.personality.character_name,
            providers=list(self.config.llm_providers.keys()),
            triggers=len(self.config.triggers)
        )

        # Subscribe to events
        await self.client.subscribe("chatMsg", self._handle_chat_message)
        
        # Phase 1: Components are initialized in __init__, no async start needed

        logger.info("LLM service started and ready")

    async def stop(self) -> None:
        """Stop the service."""
        logger.info("Stopping LLM service")
        self._shutdown_event.set()

        # Publish shutdown event
        if self.lifecycle:
            await self.lifecycle.publish_shutdown(reason="Normal shutdown")
            await self.lifecycle.stop()
        
        # Phase 1: Components have no async cleanup needed
        
        # Disconnect from NATS
        await self.client.disconnect()

        logger.info("LLM service stopped")

    async def wait_for_shutdown(self) -> None:
        """Wait for shutdown signal."""
        await self._shutdown_event.wait()

    async def _handle_chat_message(self, subject: str, data: dict) -> None:
        """Handle chatMsg events.
        
        Processing pipeline (Phase 2 enhanced):
        1. Filter message (MessageListener)
        2. Check triggers (TriggerEngine - ENHANCED with trigger words)
        3. Check rate limits (RateLimiter - NEW)
        4. Build prompts (PromptBuilder - ENHANCED with trigger context)
        5. Generate response (LLMManager)
        6. Format response (ResponseFormatter)
        7. Send to chat or log (based on dry_run)
        8. Record response (RateLimiter - NEW)
        9. Log response (ResponseLogger - NEW)
        """
        # 1. Filter message
        filtered = await self.listener.filter_message(data)
        if not filtered:
            return
        
        # 2. Check triggers (mentions + trigger words with probability)
        trigger_result = await self.trigger_engine.check_triggers(filtered)
        if not trigger_result:
            return
        
        logger.info(
            f"Triggered by {trigger_result.trigger_type} '{trigger_result.trigger_name}': "
            f"{filtered['username']}"
        )
        
        # 3. Check rate limits (NEW - REQ-030)
        rank = filtered.get("meta", {}).get("rank", 1)
        rate_limit_decision = await self.rate_limiter.check_rate_limit(
            filtered["username"],
            trigger_result,
            rank
        )
        
        if not rate_limit_decision.allowed:
            # REQ-032: Log rate limit rejections
            logger.info(
                f"Rate limit blocked response: {rate_limit_decision.reason} "
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
                False
            )
            return
        
        # 4. Build prompts (with trigger context - REQ-034)
        system_prompt = self.prompt_builder.build_system_prompt()
        user_prompt = self.prompt_builder.build_user_prompt(
            filtered["username"],
            trigger_result.cleaned_message,
            trigger_result.context  # NEW: Phase 2 trigger context
        )
        
        # 5. Generate response
        llm_response = await self.llm_manager.generate_response(
            system_prompt,
            user_prompt
        )
        
        if not llm_response:
            logger.error("LLM failed to generate response")
            # Log the failure
            await self.response_logger.log_response(
                filtered["username"],
                trigger_result,
                filtered["msg"],
                "",
                [],
                rate_limit_decision,
                False
            )
            return
        
        # 6. Format response
        formatted_parts = await self.response_formatter.format_response(llm_response)
        
        if not formatted_parts:
            logger.error("Formatter returned empty response")
            await self.response_logger.log_response(
                filtered["username"],
                trigger_result,
                filtered["msg"],
                llm_response,
                [],
                rate_limit_decision,
                False
            )
            return
        
        # 7. Send to chat or log
        sent = False
        for i, part in enumerate(formatted_parts):
            if self.config.testing.dry_run:
                logger.info(f"[DRY RUN] Would send: {part}")
            else:
                await self.client.send_chat_message(part)
                logger.info(f"Sent response part {i+1}/{len(formatted_parts)}")
                sent = True
            
            # Delay between parts
            if i < len(formatted_parts) - 1:
                await asyncio.sleep(self.config.message_processing.split_delay_seconds)
        
        # 8. Record response (update rate limit state - NEW, REQ-031)
        # REQ-033: In dry-run mode, don't update rate limit state
        if sent or not self.config.testing.dry_run:
            await self.rate_limiter.record_response(
                filtered["username"],
                trigger_result
            )
        
        # 9. Log response (NEW - REQ-038)
        await self.response_logger.log_response(
            filtered["username"],
            trigger_result,
            filtered["msg"],
            llm_response,
            formatted_parts,
            rate_limit_decision,
            sent
        )
