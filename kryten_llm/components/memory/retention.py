"""Retention sweeper: periodically expires old, low-value facts.

Sprint 10, Sortie 2 — REQ-180 through REQ-186.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kryten_llm.components.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)


class RetentionSweeper:
    """Background task that expires facts by age and/or low importance (REQ-180–186).

    A fact is **eligible** for expiry when:
      * ``age > max_age_days``  (the ``created_at`` metadata field is used)
      * AND ``importance <= expire_below_importance``
        (if ``expire_below_importance == 0`` the importance criterion is
        disabled and only age is checked — "age-only" mode).

    The sweeper is fail-safe: every error is logged and the service loop is
    never crashed (REQ-183).  The sweep runs *before* the first interval so
    that a service restart immediately enforces policy if the store grew
    during downtime.  After the initial sweep it repeats on ``interval_hours``.

    Default off — callers must explicitly enable via config (REQ-184).
    """

    def __init__(
        self,
        store: "VectorStore",
        interval_hours: float = 24.0,
        max_age_days: int = 180,
        expire_below_importance: int = 0,
        batch_size: int = 500,
        health_monitor: Any = None,
    ) -> None:
        self._store = store
        self._interval = interval_hours * 3600.0
        self._max_age_days = max_age_days
        self._expire_below_importance = expire_below_importance
        self._batch_size = batch_size
        self._monitor = health_monitor
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Schedule the sweeper background task (REQ-180)."""
        self._task = asyncio.ensure_future(self._loop())
        logger.info(
            "RetentionSweeper started (interval=%.1fh, max_age=%dd, " "expire_below_importance=%d)",
            self._interval / 3600.0,
            self._max_age_days,
            self._expire_below_importance,
        )

    async def stop(self) -> None:
        """Cancel the sweeper task."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("RetentionSweeper stopped")

    # ------------------------------------------------------------------
    # Loop + sweep
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Repeat sweep on the configured interval (REQ-180)."""
        while True:
            # Run sweep first, then wait — so a restart immediately cleans up.
            try:
                await self.sweep()
            except Exception as exc:
                logger.error("RetentionSweeper._loop: sweep error: %s", exc, exc_info=True)
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                return

    async def sweep(self) -> int:
        """One full sweep pass.

        Returns the number of facts actually deleted (REQ-185).
        Never raises — errors are logged and 0 is returned (REQ-183).
        """
        try:
            return await self._sweep_impl()
        except Exception as exc:
            logger.error("RetentionSweeper.sweep: unexpected error: %s", exc, exc_info=True)
            return 0

    async def _sweep_impl(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._max_age_days)

        try:
            records = await self._store.get_all()
        except Exception as exc:
            logger.error("RetentionSweeper: get_all failed: %s", exc, exc_info=True)
            return 0

        expired_ids: list[str] = []
        for r in records:
            meta = r.get("metadata") or {}
            if self._is_eligible(meta, cutoff):
                rid = r.get("id")
                if rid is not None:
                    expired_ids.append(str(rid))

        if not expired_ids:
            logger.info(
                "RetentionSweeper: scanned %d record(s), 0 eligible for expiry.",
                len(records),
            )
            return 0

        delete_ids = getattr(self._store, "delete_ids", None)
        if delete_ids is None:
            logger.warning(
                "RetentionSweeper: store does not support delete_ids; sweep skipped "
                "(%d eligible fact(s) not deleted).",
                len(expired_ids),
            )
            return 0

        total_deleted = 0
        for i in range(0, len(expired_ids), self._batch_size):
            batch = expired_ids[i : i + self._batch_size]
            try:
                await delete_ids(batch)
                total_deleted += len(batch)
            except Exception as exc:
                logger.error("RetentionSweeper: delete_ids batch failed: %s", exc, exc_info=True)

        if self._monitor is not None:
            try:
                self._monitor.record_memory_facts_expired(total_deleted)
            except Exception:
                pass

        logger.info(
            "RetentionSweeper: scanned %d record(s), expired %d (cutoff=%s).",
            len(records),
            total_deleted,
            cutoff.date().isoformat(),
        )
        return total_deleted

    # ------------------------------------------------------------------
    # Eligibility predicate
    # ------------------------------------------------------------------

    def _is_eligible(self, meta: dict[str, Any], cutoff: datetime) -> bool:
        """Return True when *meta* represents a fact that should be expired.

        Both criteria must pass:
        1. ``created_at`` is present and older than *cutoff*.
        2. ``importance <= expire_below_importance``
           (skipped when ``expire_below_importance == 0``).
        """
        # Importance gate (REQ-181).
        if self._expire_below_importance > 0:
            importance = int(meta.get("importance", 1))
            if importance > self._expire_below_importance:
                return False

        # Age gate (REQ-181).
        created_at = meta.get("created_at")
        if not created_at:
            return False
        try:
            dt = datetime.fromisoformat(str(created_at))
        except ValueError:
            return False
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt < cutoff
