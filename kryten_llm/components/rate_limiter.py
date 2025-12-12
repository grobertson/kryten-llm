"""Rate limiting for bot responses."""

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from kryten_llm.models.config import LLMConfig
from kryten_llm.models.events import TriggerResult

logger = logging.getLogger(__name__)


@dataclass
class RateLimitDecision:
    """Result of rate limit check.

    Implements REQ-021: Detailed decision with reason and retry time.
    """

    allowed: bool  # True if response allowed
    reason: str  # Human-readable reason
    retry_after: int  # Seconds until next allowed (0 if allowed)
    details: dict  # Additional context (limits, counts, cooldowns)


class RateLimiter:
    """Manages rate limiting for bot responses.

    Implements multi-level rate limiting:
    - Global rate limits (REQ-011)
    - Per-user rate limits (REQ-012)
    - Per-trigger rate limits (REQ-013)
    - Global cooldown (REQ-014)
    - User cooldown (REQ-015)
    - Mention cooldown (REQ-016)
    - Trigger cooldown (REQ-017)
    - Admin multipliers (REQ-018, REQ-019, REQ-020)

    State is stored in-memory (REQ-023, CON-002).
    """

    def __init__(self, config: LLMConfig):
        """Initialize rate limiter with configuration.

        Args:
            config: LLM configuration containing rate_limits settings
        """
        self.config = config
        self.rate_limits = config.rate_limits

        # Global rate tracking (REQ-011)
        self.global_responses_minute: deque[datetime] = deque()
        self.global_responses_hour: deque[datetime] = deque()
        self.last_response_time: datetime | None = None

        # Per-user rate tracking (REQ-012)
        self.user_responses_hour: dict[str, deque[datetime]] = {}
        self.user_last_response: dict[str, datetime] = {}

        # Per-trigger rate tracking (REQ-013)
        self.trigger_responses_hour: dict[str, deque[datetime]] = {}
        self.trigger_last_response: dict[str, datetime] = {}

        # Mention-specific tracking (REQ-016)
        self.last_mention_response: datetime | None = None

        logger.info(
            f"RateLimiter initialized: global={self.rate_limits.global_max_per_minute}/min, "
            f"{self.rate_limits.global_max_per_hour}/hr, "
            f"user={self.rate_limits.user_max_per_hour}/hr"
        )

    async def check_rate_limit(
        self, username: str, trigger_result: TriggerResult, rank: int = 1
    ) -> RateLimitDecision:
        """Check if response is allowed by rate limits.

        Checks in order (first failure returns decision):
        1. Global rate limits (per minute, per hour)
        2. Global cooldown (time since last response)
        3. User rate limits (per hour)
        4. User cooldown (time since last response to this user)
        5. Mention cooldown (if trigger_type="mention")
        6. Trigger rate limits (max per hour)
        7. Trigger cooldown (time since last activation)

        Applies admin multipliers if rank >= 3 (REQ-018, REQ-019, REQ-020).

        Args:
            username: Username triggering response
            trigger_result: TriggerResult from TriggerEngine
            rank: User rank (default 1, admin >= 3)

        Returns:
            RateLimitDecision with allowed=True/False and details
        """
        now = datetime.now()
        is_admin = self._is_admin(rank)

        # Clean old timestamps from all deques
        self._clean_old_timestamps(self.global_responses_minute, 60)
        self._clean_old_timestamps(self.global_responses_hour, 3600)

        # Check global limits (REQ-011)
        decision = self._check_global_limits(is_admin)
        if decision:
            return decision

        # Check global cooldown (REQ-014)
        if self.last_response_time:
            cooldown = self._apply_admin_multiplier(
                self.rate_limits.global_cooldown_seconds,
                self.rate_limits.admin_cooldown_multiplier,
                is_admin,
            )
            elapsed = (now - self.last_response_time).total_seconds()
            if elapsed < cooldown:
                retry_after = int(cooldown - elapsed)
                return RateLimitDecision(
                    allowed=False,
                    reason="global cooldown active",
                    retry_after=retry_after,
                    details={
                        "last_response": self.last_response_time.isoformat(),
                        "cooldown_seconds": cooldown,
                        "elapsed": elapsed,
                        "is_admin": is_admin,
                    },
                )

        # Check user limits (REQ-012, REQ-015)
        decision = self._check_user_limits(username, is_admin, now)
        if decision:
            return decision

        # Check mention cooldown (REQ-016)
        if trigger_result.trigger_type == "mention":
            if self.last_mention_response:
                cooldown = self._apply_admin_multiplier(
                    self.rate_limits.mention_cooldown_seconds,
                    self.rate_limits.admin_cooldown_multiplier,
                    is_admin,
                )
                elapsed = (now - self.last_mention_response).total_seconds()
                if elapsed < cooldown:
                    retry_after = int(cooldown - elapsed)
                    return RateLimitDecision(
                        allowed=False,
                        reason="mention cooldown active",
                        retry_after=retry_after,
                        details={
                            "last_mention": self.last_mention_response.isoformat(),
                            "cooldown_seconds": cooldown,
                            "elapsed": elapsed,
                            "is_admin": is_admin,
                        },
                    )

        # Check trigger-specific limits (REQ-013, REQ-017)
        if trigger_result.trigger_type == "trigger_word" and trigger_result.trigger_name:
            decision = self._check_trigger_limits(trigger_result, is_admin, now)
            if decision:
                return decision

        # All checks passed
        logger.debug(f"Rate limit check passed for {username} (rank={rank})")
        return RateLimitDecision(
            allowed=True,
            reason="allowed",
            retry_after=0,
            details={
                "global_count_minute": len(self.global_responses_minute),
                "global_count_hour": len(self.global_responses_hour),
                "user_count_hour": len(self.user_responses_hour.get(username, [])),
                "is_admin": is_admin,
            },
        )

    async def record_response(self, username: str, trigger_result: TriggerResult) -> None:
        """Record that a response was sent (update state).

        Implements REQ-022: Update state after responses are sent.

        Args:
            username: Username who triggered response
            trigger_result: TriggerResult from trigger check
        """
        now = datetime.now()

        # Update global tracking
        self.global_responses_minute.append(now)
        self.global_responses_hour.append(now)
        self.last_response_time = now

        # Update per-user tracking
        if username not in self.user_responses_hour:
            self.user_responses_hour[username] = deque()
        self.user_responses_hour[username].append(now)
        self.user_last_response[username] = now

        # Update mention tracking
        if trigger_result.trigger_type == "mention":
            self.last_mention_response = now

        # Update per-trigger tracking
        if trigger_result.trigger_type == "trigger_word" and trigger_result.trigger_name:
            trigger_name = trigger_result.trigger_name
            if trigger_name not in self.trigger_responses_hour:
                self.trigger_responses_hour[trigger_name] = deque()
            self.trigger_responses_hour[trigger_name].append(now)
            self.trigger_last_response[trigger_name] = now

        logger.debug(
            f"Response recorded for {username} "
            f"(trigger: {trigger_result.trigger_type}/{trigger_result.trigger_name})"
        )

    def _is_admin(self, rank: int) -> bool:
        """Check if user is admin/moderator.

        Implements REQ-018: Admin detection via rank.

        Args:
            rank: User rank from message metadata

        Returns:
            True if rank >= 3 (admin/moderator)
        """
        return rank >= 3

    def _apply_admin_multiplier(
        self, value: int | float, multiplier: float, is_admin: bool
    ) -> int | float:
        """Apply admin multiplier to cooldown or limit.

        Implements REQ-019, REQ-020: Admin multipliers for cooldowns and limits.

        Args:
            value: Original value (cooldown or limit)
            multiplier: Multiplier to apply if admin
            is_admin: Whether user is admin

        Returns:
            Modified value if admin, original value otherwise
        """
        if is_admin:
            result = value * multiplier
            return int(result) if isinstance(value, int) else result
        return value

    def _clean_old_timestamps(self, timestamps: deque[datetime], window_seconds: int) -> None:
        """Remove timestamps older than window from deque.

        Args:
            timestamps: Deque of timestamps to clean
            window_seconds: Time window in seconds
        """
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()

    def _check_global_limits(self, is_admin: bool) -> RateLimitDecision | None:
        """Check global rate limits.

        Implements REQ-011: Global per-minute and per-hour limits.

        Args:
            is_admin: Whether user is admin

        Returns:
            RateLimitDecision if blocked, None if allowed
        """
        # Check per-minute limit
        limit_minute = self._apply_admin_multiplier(
            self.rate_limits.global_max_per_minute,
            self.rate_limits.admin_limit_multiplier,
            is_admin,
        )
        if len(self.global_responses_minute) >= limit_minute:
            # Calculate retry_after based on oldest timestamp
            if self.global_responses_minute:
                oldest = self.global_responses_minute[0]
                retry_after = int(60 - (datetime.now() - oldest).total_seconds())
                retry_after = max(1, retry_after)
            else:
                retry_after = 60

            return RateLimitDecision(
                allowed=False,
                reason="global per-minute limit reached",
                retry_after=retry_after,
                details={
                    "count": len(self.global_responses_minute),
                    "limit": limit_minute,
                    "is_admin": is_admin,
                },
            )

        # Check per-hour limit
        limit_hour = self._apply_admin_multiplier(
            self.rate_limits.global_max_per_hour, self.rate_limits.admin_limit_multiplier, is_admin
        )
        if len(self.global_responses_hour) >= limit_hour:
            if self.global_responses_hour:
                oldest = self.global_responses_hour[0]
                retry_after = int(3600 - (datetime.now() - oldest).total_seconds())
                retry_after = max(1, retry_after)
            else:
                retry_after = 3600

            return RateLimitDecision(
                allowed=False,
                reason="global per-hour limit reached",
                retry_after=retry_after,
                details={
                    "count": len(self.global_responses_hour),
                    "limit": limit_hour,
                    "is_admin": is_admin,
                },
            )

        return None

    def _check_user_limits(
        self, username: str, is_admin: bool, now: datetime
    ) -> RateLimitDecision | None:
        """Check per-user rate limits.

        Implements REQ-012, REQ-015: Per-user limits and cooldowns.

        Args:
            username: Username to check
            is_admin: Whether user is admin
            now: Current datetime

        Returns:
            RateLimitDecision if blocked, None if allowed
        """
        # Clean user's timestamp deque
        if username in self.user_responses_hour:
            self._clean_old_timestamps(self.user_responses_hour[username], 3600)

        # Check per-user per-hour limit
        limit_hour = self._apply_admin_multiplier(
            self.rate_limits.user_max_per_hour, self.rate_limits.admin_limit_multiplier, is_admin
        )
        user_count = len(self.user_responses_hour.get(username, []))
        if user_count >= limit_hour:
            if self.user_responses_hour.get(username):
                oldest = self.user_responses_hour[username][0]
                retry_after = int(3600 - (now - oldest).total_seconds())
                retry_after = max(1, retry_after)
            else:
                retry_after = 3600

            return RateLimitDecision(
                allowed=False,
                reason="user per-hour limit reached",
                retry_after=retry_after,
                details={
                    "username": username,
                    "count": user_count,
                    "limit": limit_hour,
                    "is_admin": is_admin,
                },
            )

        # Check user cooldown
        if username in self.user_last_response:
            cooldown = self._apply_admin_multiplier(
                self.rate_limits.user_cooldown_seconds,
                self.rate_limits.admin_cooldown_multiplier,
                is_admin,
            )
            elapsed = (now - self.user_last_response[username]).total_seconds()
            if elapsed < cooldown:
                retry_after = int(cooldown - elapsed)
                return RateLimitDecision(
                    allowed=False,
                    reason="user cooldown active",
                    retry_after=retry_after,
                    details={
                        "username": username,
                        "last_response": self.user_last_response[username].isoformat(),
                        "cooldown_seconds": cooldown,
                        "elapsed": elapsed,
                        "is_admin": is_admin,
                    },
                )

        return None

    def _check_trigger_limits(
        self, trigger_result: TriggerResult, is_admin: bool, now: datetime
    ) -> RateLimitDecision | None:
        """Check per-trigger rate limits.

        Implements REQ-013, REQ-017: Per-trigger limits and cooldowns.

        Args:
            trigger_result: TriggerResult from trigger check
            is_admin: Whether user is admin
            now: Current datetime

        Returns:
            RateLimitDecision if blocked, None if allowed
        """
        trigger_name = trigger_result.trigger_name

        # If no trigger name, allow (shouldn't happen in practice)
        if trigger_name is None:
            return None

        # Find trigger config
        trigger_config = None
        for t in self.config.triggers:
            if t.name == trigger_name:
                trigger_config = t
                break

        if not trigger_config:
            # Trigger not found in config, allow by default
            return None

        # Clean trigger's timestamp deque
        if trigger_name in self.trigger_responses_hour:
            self._clean_old_timestamps(self.trigger_responses_hour[trigger_name], 3600)

        # Check per-trigger per-hour limit
        limit_hour = self._apply_admin_multiplier(
            trigger_config.max_responses_per_hour, self.rate_limits.admin_limit_multiplier, is_admin
        )
        trigger_count = len(self.trigger_responses_hour.get(trigger_name, []))
        if trigger_count >= limit_hour:
            if self.trigger_responses_hour.get(trigger_name):
                oldest = self.trigger_responses_hour[trigger_name][0]
                retry_after = int(3600 - (now - oldest).total_seconds())
                retry_after = max(1, retry_after)
            else:
                retry_after = 3600

            return RateLimitDecision(
                allowed=False,
                reason=f"trigger '{trigger_name}' per-hour limit reached",
                retry_after=retry_after,
                details={
                    "trigger_name": trigger_name,
                    "count": trigger_count,
                    "limit": limit_hour,
                    "is_admin": is_admin,
                },
            )

        # Check trigger cooldown
        if trigger_name in self.trigger_last_response:
            cooldown = self._apply_admin_multiplier(
                trigger_config.cooldown_seconds,
                self.rate_limits.admin_cooldown_multiplier,
                is_admin,
            )
            elapsed = (now - self.trigger_last_response[trigger_name]).total_seconds()
            if elapsed < cooldown:
                retry_after = int(cooldown - elapsed)
                return RateLimitDecision(
                    allowed=False,
                    reason=f"trigger '{trigger_name}' cooldown active",
                    retry_after=retry_after,
                    details={
                        "trigger_name": trigger_name,
                        "last_response": self.trigger_last_response[trigger_name].isoformat(),
                        "cooldown_seconds": cooldown,
                        "elapsed": elapsed,
                        "is_admin": is_admin,
                    },
                )

        return None
