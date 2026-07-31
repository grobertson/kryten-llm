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


# ---------------------------------------------------------------------------
# Sprint 18, Sortie 3: Temporal confidence drift sweeper (REQ-380–384)
# ---------------------------------------------------------------------------


class ConfidenceDriftSweeper:
    """Background task that nudges confidence downward for dormant facts (REQ-380–384).

    A fact is **eligible** for drift when its ``last_seen`` (or ``created_at`` as
    fallback) timestamp is older than ``drift_after_days``.  The reduction is
    ``drift_rate_per_day * dormant_days``, floored at ``confidence_floor``.

    This models the intuition that stale, un-corroborated facts should be trusted
    less over time even without a direct contradiction signal.  It is complementary
    to Sprint 13's contradiction-triggered decay and Sprint 10's deletion-based
    retention sweeper — it nudges confidence without deleting facts.

    Default off (``confidence_drift.enabled = false``).  Never raises into the
    service loop (REQ-383).
    """

    def __init__(
        self,
        store: "VectorStore",
        interval_hours: float = 24.0,
        drift_after_days: float = 30.0,
        drift_rate_per_day: float = 0.001,
        floor: float = 0.1,
        health_monitor: Any = None,
    ) -> None:
        self._store = store
        self._interval = interval_hours * 3600.0
        self._drift_after_days = drift_after_days
        self._rate = drift_rate_per_day
        self._floor = floor
        self._monitor = health_monitor
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Schedule the drift sweeper background task."""
        self._task = asyncio.ensure_future(self._loop())
        logger.info(
            "ConfidenceDriftSweeper started (interval=%.1fh, drift_after=%.1fd, "
            "rate=%.4f/day, floor=%.2f)",
            self._interval / 3600.0,
            self._drift_after_days,
            self._rate,
            self._floor,
        )

    async def stop(self) -> None:
        """Cancel the drift sweeper task."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ConfidenceDriftSweeper stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self.sweep()
            except Exception as exc:
                logger.error("ConfidenceDriftSweeper._loop: sweep error: %s", exc, exc_info=True)
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                return

    async def sweep(self) -> int:
        """One drift sweep pass.

        Returns the number of facts whose confidence was updated.
        Never raises — errors are logged and 0 is returned (REQ-383).
        """
        try:
            return await self._sweep_impl()
        except Exception as exc:
            logger.error("ConfidenceDriftSweeper.sweep: unexpected error: %s", exc, exc_info=True)
            return 0

    async def _sweep_impl(self) -> int:
        get_all = getattr(self._store, "get_all", None)
        update_metadata = getattr(self._store, "update_metadata", None)
        if get_all is None or update_metadata is None:
            logger.debug("ConfidenceDriftSweeper: store lacks get_all/update_metadata; skipped")
            return 0

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=self._drift_after_days)

        try:
            records = await get_all()
        except Exception as exc:
            logger.error("ConfidenceDriftSweeper: get_all failed: %s", exc, exc_info=True)
            return 0

        updated_ids: list[str] = []
        updated_metas: list[dict[str, Any]] = []

        for r in records:
            try:
                meta = dict(r.get("metadata") or {})
                old_conf = float(meta.get("confidence", 0.5))
                if old_conf <= self._floor:
                    continue  # Already at floor — skip (REQ-381).

                # Prefer last_seen (corroboration timestamp); fall back to created_at.
                ts_str = meta.get("last_seen") or meta.get("created_at", "")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(str(ts_str))
                except ValueError:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)

                if ts > cutoff:
                    continue  # Not dormant enough — no drift.

                dormant_days = (now - ts).total_seconds() / 86400.0
                reduction = self._rate * dormant_days
                new_conf = max(self._floor, old_conf - reduction)

                if new_conf >= old_conf:
                    continue  # Floating-point edge case; nothing to update.

                meta["confidence"] = new_conf
                rid = r.get("id")
                if rid is not None:
                    updated_ids.append(str(rid))
                    updated_metas.append(meta)

            except Exception as exc:
                logger.warning(
                    "ConfidenceDriftSweeper: error processing fact id=%s: %s",
                    r.get("id"),
                    exc,
                )

        if updated_ids:
            try:
                await update_metadata(updated_ids, updated_metas)
            except Exception as exc:
                logger.error(
                    "ConfidenceDriftSweeper: update_metadata failed: %s", exc, exc_info=True
                )
                return 0

        logger.info(
            "ConfidenceDriftSweeper: scanned %d record(s), drifted %d (cutoff=%s).",
            len(records),
            len(updated_ids),
            cutoff.date().isoformat(),
        )
        return len(updated_ids)


# ---------------------------------------------------------------------------
# Sprint 19, Sortie 1: Semantic fact compaction sweeper (REQ-385–389)
# ---------------------------------------------------------------------------


class CompactionSweeper:
    """Background task that merges semantically near-duplicate facts (REQ-385–389).

    For each user with at least ``min_facts_to_compact`` facts, the sweeper
    re-embeds all fact texts and applies full pairwise agglomerative clustering
    (union-find, O(N²)).  Any pair with cosine similarity ≥ ``merge_threshold``
    is joined; entire connected components form a cluster.  Multi-member clusters
    are merged into one canonical fact (highest-importance text, summed importance
    capped at ``importance_cap``, importance-weighted confidence average).

    Default off — no service impact until explicitly enabled (REQ-389).
    Never raises into the service loop (REQ-386).
    """

    def __init__(
        self,
        store: "VectorStore",
        embedder: Any,
        interval_hours: float = 24.0,
        min_facts_to_compact: int = 10,
        merge_threshold: float = 0.85,
        importance_cap: int = 10000,
        health_monitor: Any = None,
        dry_run: bool = False,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._interval = interval_hours * 3600.0
        self._min_facts = min_facts_to_compact
        self._threshold = merge_threshold
        self._importance_cap = importance_cap
        self._monitor = health_monitor
        self._dry_run = dry_run
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Schedule the compaction background task."""
        self._task = asyncio.ensure_future(self._loop())
        logger.info(
            "CompactionSweeper started (interval=%.1fh, threshold=%.2f, min_facts=%d%s)",
            self._interval / 3600.0,
            self._threshold,
            self._min_facts,
            " [dry-run]" if self._dry_run else "",
        )

    async def stop(self) -> None:
        """Cancel the compaction task."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CompactionSweeper stopped")

    # ------------------------------------------------------------------
    # Loop + sweep
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Sweep immediately on start, then repeat on interval."""
        while True:
            try:
                await self.sweep()
            except Exception as exc:
                logger.error("CompactionSweeper._loop: sweep error: %s", exc, exc_info=True)
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                return

    async def sweep(self) -> int:
        """Full pass across all users.

        Returns total facts merged/deleted (or that *would* be in dry-run mode).
        Never raises.
        """
        try:
            return await self._sweep_impl()
        except Exception as exc:
            logger.error("CompactionSweeper.sweep: unexpected error: %s", exc, exc_info=True)
            return 0

    async def _sweep_impl(self) -> int:
        try:
            records = await self._store.get_all()
        except Exception as exc:
            logger.error("CompactionSweeper: get_all failed: %s", exc, exc_info=True)
            return 0

        # Group by user
        by_user: dict[str, list[dict[str, Any]]] = {}
        for r in records:
            uid = str(r.get("metadata", {}).get("user") or r.get("id", ""))
            by_user.setdefault(uid, []).append(r)

        total_merged = 0
        for uid, user_records in by_user.items():
            try:
                n = await self._sweep_user(uid, user_records)
                total_merged += n
            except Exception as exc:
                logger.warning(
                    "CompactionSweeper: error processing user=%s: %s", uid, exc, exc_info=True
                )

        if self._monitor is not None:
            try:
                self._monitor.record_memory_facts_compacted(total_merged)
            except Exception:
                pass

        logger.info(
            "CompactionSweeper: scanned %d user(s), %s %d fact(s)%s.",
            len(by_user),
            "would merge" if self._dry_run else "merged",
            total_merged,
            " [dry-run]" if self._dry_run else "",
        )
        return total_merged

    async def _sweep_user(self, uid: str, records: list[dict[str, Any]]) -> int:
        """Compact one user's facts. Returns the number of facts deleted (or would-delete)."""
        if len(records) < self._min_facts:
            return 0

        # Re-embed all fact texts in one batch
        texts = [str(r.get("document") or "") for r in records]
        try:
            vecs = await self._embedder.embed(texts)
        except Exception as exc:
            logger.warning("CompactionSweeper: embed failed for user=%s: %s", uid, exc)
            return 0

        clusters = self._pairwise_cluster(records, vecs, self._threshold)
        now = datetime.now(timezone.utc).isoformat()
        n_deleted = 0

        for cluster in clusters:
            if len(cluster) < 2:
                continue  # singleton — nothing to merge

            # Canonical = highest-importance fact
            canonical = max(cluster, key=lambda r: int(r.get("metadata", {}).get("importance", 1)))
            others = [r for r in cluster if r.get("id") != canonical.get("id")]

            total_imp = sum(int(r.get("metadata", {}).get("importance", 1)) for r in cluster)
            merged_imp = min(total_imp, self._importance_cap)

            weights = [int(r.get("metadata", {}).get("importance", 1)) for r in cluster]
            confs = [float(r.get("metadata", {}).get("confidence", 0.5)) for r in cluster]
            w_sum = max(sum(weights), 1)
            merged_conf = sum(w * c for w, c in zip(weights, confs)) / w_sum

            created_ats = [
                r.get("metadata", {}).get("created_at")
                for r in cluster
                if r.get("metadata", {}).get("created_at")
            ]
            earliest_created = min(created_ats) if created_ats else None

            if self._dry_run:
                logger.info(
                    "[dry-run] user=%s cluster_size=%d canonical=%r would_merge=%d",
                    uid,
                    len(cluster),
                    str(canonical.get("document", ""))[:60],
                    len(others),
                )
                n_deleted += len(others)
                continue

            # Delete non-canonicals
            other_ids = [str(r["id"]) for r in others if r.get("id") is not None]
            if other_ids:
                try:
                    await self._store.delete_ids(other_ids)
                except Exception as exc:
                    logger.warning("CompactionSweeper: delete_ids failed for user=%s: %s", uid, exc)
                    continue

            # Update canonical metadata
            new_meta = dict(canonical.get("metadata") or {})
            new_meta["importance"] = merged_imp
            new_meta["confidence"] = merged_conf
            if earliest_created:
                new_meta["created_at"] = earliest_created
            new_meta["last_seen"] = now
            cid = canonical.get("id")
            if cid is not None:
                try:
                    await self._store.update_metadata([str(cid)], [new_meta])
                except Exception as exc:
                    logger.warning(
                        "CompactionSweeper: update_metadata failed for user=%s id=%s: %s",
                        uid,
                        cid,
                        exc,
                    )

            n_deleted += len(others)

        return n_deleted

    # ------------------------------------------------------------------
    # Clustering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pairwise_cluster(
        records: list[dict[str, Any]],
        vecs: list[list[float]],
        threshold: float,
    ) -> list[list[dict[str, Any]]]:
        """Full pairwise agglomerative clustering via union-find (O(N²)).

        Any pair of facts with cosine similarity ≥ *threshold* is merged into the
        same cluster (transitively, via union-find).  Returns a list of clusters;
        each cluster is a list of records.  Singleton clusters (size 1) are included
        — callers filter on ``len(cluster) >= 2``.
        """
        n = len(records)
        parent = list(range(n))

        def _find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def _union(x: int, y: int) -> None:
            rx, ry = _find(x), _find(y)
            if rx != ry:
                parent[ry] = rx

        for i in range(n):
            for j in range(i + 1, n):
                if CompactionSweeper._cosine(vecs[i], vecs[j]) >= threshold:
                    _union(i, j)

        # Group indices by cluster root
        from collections import defaultdict

        groups: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            groups[_find(i)].append(i)

        return [[records[i] for i in idx_list] for idx_list in groups.values()]

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        """Cosine similarity between two vectors (handles zero-norm gracefully)."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        denom = norm_a * norm_b
        return dot / denom if denom > 0.0 else 0.0
