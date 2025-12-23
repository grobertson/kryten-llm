"""Heartbeat publishing for Phase 5.

Publishes periodic health status to NATS.
"""

import asyncio
import json
import logging
from typing import Optional

from kryten.subject_builder import normalize_token  # type: ignore[import-untyped]
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
        start_time: float,
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

            # Publish to NATS - normalize service name for consistent subject matching
            normalized_service_name = normalize_token(self.config.service_name)
            subject = f"kryten.service.heartbeat.{normalized_service_name}"
            data = json.dumps(payload).encode("utf-8")

            await self.nats.publish(subject, data)

            self.logger.debug(
                f"Published heartbeat: {payload['health']} "
                f"({payload['status']['messages_processed']} messages processed)"
            )

        except Exception as e:
            self.logger.error(f"Failed to publish heartbeat: {e}", exc_info=True)
