"""Spam detection for user behavior analysis.

Phase 4: Detect and prevent spam behavior with exponential backoff
(REQ-016 through REQ-022).
"""

import logging
from collections import deque, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from kryten_llm.models.config import SpamDetectionConfig


logger = logging.getLogger(__name__)


@dataclass
class SpamCheckResult:
    """Result of spam check.
    
    Implements PAT-003 from Phase 4 specification.
    """
    is_spam: bool
    reason: str
    penalty_duration: Optional[int]  # Penalty duration in seconds
    offense_count: int


class SpamDetector:
    """Detects and prevents user spam behavior.
    
    Phase 4 Implementation (REQ-016 through REQ-022):
    - Message frequency tracking (REQ-016)
    - Identical message detection (REQ-017)
    - Rapid mention spam detection (REQ-018)
    - Exponential backoff penalties (REQ-019)
    - Admin exemptions (REQ-020)
    - Clear logging (REQ-021)
    - In-memory only state (REQ-022)
    """

    def __init__(self, config: SpamDetectionConfig):
        """Initialize spam detector with configuration.
        
        Args:
            config: Spam detection configuration
        """
        self.config = config
        
        # Track message timestamps per user (for rate limiting)
        self._user_messages: dict[str, deque[datetime]] = defaultdict(
            lambda: deque(maxlen=100)
        )
        
        # Track mention timestamps per user (for mention spam)
        self._user_mentions: dict[str, deque[datetime]] = defaultdict(
            lambda: deque(maxlen=50)
        )
        
        # Track penalties per user
        self._user_penalties: dict[str, datetime] = {}
        
        # Track offense counts for exponential backoff
        self._offense_counts: dict[str, int] = defaultdict(int)
        
        # Track last offense time for clean period
        self._last_offense: dict[str, datetime] = {}
        
        # Track last N messages per user (for identical detection)
        self._last_messages: dict[str, deque[str]] = defaultdict(
            lambda: deque(maxlen=20)
        )
        
        logger.info(
            f"SpamDetector initialized: enabled={config.enabled}, "
            f"windows={len(config.message_windows)}, "
            f"mention_window={config.mention_spam_window}s"
        )
    
    # Expose internal state for testing
    @property
    def user_messages(self):
        return self._user_messages
    
    @property
    def user_penalties(self):
        return self._user_penalties
    
    @property
    def offense_counts(self):
        return self._offense_counts
    
    @property
    def last_offense(self):
        return self._last_offense
    
    def check_spam(
        self, 
        username: str, 
        message: str, 
        user_rank: int,
        mention_count: int = 0
    ) -> SpamCheckResult:
        """Check if user is spamming.
        
        Implements spam detection pipeline with multiple checks.
        
        Args:
            username: User sending message
            message: Message text
            user_rank: User's rank (for admin exemption)
            mention_count: Number of mentions in the message (for mention spam detection)
            
        Returns:
            SpamCheckResult indicating spam status and penalty
        """
        if not self.config.enabled:
            return SpamCheckResult(
                is_spam=False,
                reason="Spam detection disabled",
                penalty_duration=None,
                offense_count=0
            )
        
        # Check admin exemption (REQ-020)
        if user_rank in self.config.admin_exempt_ranks:
            return SpamCheckResult(
                is_spam=False,
                reason=f"User exempt from spam detection (admin rank {user_rank})",
                penalty_duration=None,
                offense_count=0
            )
        
        # Check if user is currently under penalty
        if self._is_under_penalty(username):
            penalty_until = self._user_penalties[username]
            remaining = int((penalty_until - datetime.now()).total_seconds())
            return SpamCheckResult(
                is_spam=True,
                reason=f"User under spam penalty ({remaining}s remaining)",
                penalty_duration=remaining,
                offense_count=self._offense_counts[username]
            )
        
        # Check clean period for resetting offense count
        self._check_clean_period(username)
        
        # Check message rate limits (REQ-016)
        rate_violation = self._check_rate_limits(username, mention_count)
        if rate_violation:
            penalty_duration = self._apply_penalty(username)
            return SpamCheckResult(
                is_spam=True,
                reason=rate_violation,
                penalty_duration=penalty_duration,
                offense_count=self._offense_counts[username]
            )
        
        # Check identical message repetition (REQ-017)
        if self._check_identical_messages(username, message):
            penalty_duration = self._apply_penalty(username)
            return SpamCheckResult(
                is_spam=True,
                reason=f"Identical message spam detected (threshold: {self.config.identical_message_threshold})",
                penalty_duration=penalty_duration,
                offense_count=self._offense_counts[username]
            )
        
        # No spam detected
        return SpamCheckResult(
            is_spam=False,
            reason="No spam detected",
            penalty_duration=None,
            offense_count=self._offense_counts.get(username, 0)
        )
    
    def record_message(self, username: str, message: str, user_rank: int, mention_count: int = 0):
        """Record message for spam tracking.
        
        Updates message history and timestamp tracking.
        
        Args:
            username: User who sent message
            message: Message text
            user_rank: User's rank (unused but kept for API compatibility)
            mention_count: Number of mentions to track for mention spam
        """
        now = datetime.now()
        self._user_messages[username].append(now)
        self._last_messages[username].append(message.lower().strip())
        
        # Track mentions separately for mention spam detection
        if mention_count > 0:
            for _ in range(mention_count):
                self._user_mentions[username].append(now)
    
    def _check_rate_limits(self, username: str, mention_count: int) -> Optional[str]:
        """Check if user exceeds rate limits.
        
        Implements REQ-016 (general) and REQ-018 (mention spam).
        
        Args:
            username: User to check
            mention_count: Number of mentions in the message
            
        Returns:
            Violation reason if rate limit exceeded, None otherwise
        """
        now = datetime.now()
        user_timestamps = self._user_messages[username]
        
        # Check mention spam specifically (REQ-018)
        if mention_count > 0:
            mention_window = timedelta(seconds=self.config.mention_spam_window)
            user_mention_timestamps = self._user_mentions[username]
            recent_mentions = sum(
                1 for ts in user_mention_timestamps 
                if now - ts <= mention_window
            )
            
            # Spam if already sent max_messages mentions (current would exceed)
            if recent_mentions >= self.config.mention_spam_threshold:
                return (
                    f"Exceeded mention spam threshold: {recent_mentions + mention_count} mentions "
                    f"in {self.config.mention_spam_window}s "
                    f"(limit: {self.config.mention_spam_threshold})"
                )
        
        # Check general message windows (REQ-016)
        for window in self.config.message_windows:
            window_delta = timedelta(seconds=window.seconds)
            messages_in_window = sum(
                1 for ts in user_timestamps 
                if now - ts <= window_delta
            )
            
            # Count current message
            messages_in_window += 1
            
            if messages_in_window > window.max_messages:
                return (
                    f"Exceeded rate limit: {messages_in_window} messages "
                    f"in {window.seconds}s (limit: {window.max_messages})"
                )
        
        return None
    
    def _check_identical_messages(self, username: str, message: str) -> bool:
        """Check for identical message repetition.
        
        Implements REQ-017: Detects if user sends same message multiple times.
        
        Args:
            username: User to check
            message: Current message
            
        Returns:
            True if identical spam detected
        """
        message_lower = message.lower().strip()
        recent_messages = self._last_messages[username]
        
        if not recent_messages:
            return False
        
        # Count occurrences of this message in recent history
        identical_count = sum(1 for msg in recent_messages if msg == message_lower)
        
        # Spam if already sent max_messages identical messages (this would be max+1)
        return identical_count >= self.config.identical_message_threshold
    
    def _apply_penalty(self, username: str) -> int:
        """Apply exponential backoff penalty.
        
        Implements REQ-019: Penalty duration doubles on each violation.
        
        Args:
            username: User to penalize
            
        Returns:
            Penalty duration in seconds
        """
        # Increment offense count
        self._offense_counts[username] += 1
        offense_count = self._offense_counts[username]
        
        # Calculate penalty duration with exponential backoff
        # Penalty = initial_penalty * (penalty_multiplier ^ (offense_count - 1))
        penalty_seconds = int(
            self.config.initial_penalty * 
            (self.config.penalty_multiplier ** (offense_count - 1))
        )
        
        # Cap at max_penalty
        penalty_seconds = min(penalty_seconds, self.config.max_penalty)
        
        penalty_until = datetime.now() + timedelta(seconds=penalty_seconds)
        self._user_penalties[username] = penalty_until
        self._last_offense[username] = datetime.now()
        
        severity = "WARNING" if offense_count == 1 else "ERROR"
        logger.log(
            logging.WARNING if offense_count == 1 else logging.ERROR,
            f"Spam penalty applied to {username}: {penalty_seconds:.0f}s "
            f"(offense #{offense_count}, severity: {severity})"
        )
        
        return penalty_seconds
    
    def _is_under_penalty(self, username: str) -> bool:
        """Check if user currently under penalty.
        
        Args:
            username: User to check
            
        Returns:
            True if user is under active penalty
        """
        if username not in self._user_penalties:
            return False
        
        penalty_until = self._user_penalties[username]
        
        if datetime.now() >= penalty_until:
            # Penalty expired, clean up
            del self._user_penalties[username]
            return False
        
        return True
    
    def _check_clean_period(self, username: str):
        """Check clean period to reset offense count.
        
        Implements REQ-019: Reset to base penalty after clean period.
        
        Args:
            username: User to check
        """
        if username not in self._last_offense:
            return
        
        last_offense = self._last_offense[username]
        clean_delta = timedelta(seconds=self.config.clean_period)
        
        if datetime.now() - last_offense >= clean_delta:
            # Clean period passed, reset offense count
            old_count = self._offense_counts[username]
            self._offense_counts[username] = 0
            del self._last_offense[username]
            
            logger.info(
                f"Clean period passed for {username}: "
                f"offense count reset from {old_count} to 0"
            )
    
    def _cleanup_old_data(self):
        """Clean up old tracking data (periodic maintenance).
        
        Implements REQ-022: Keep state in memory with periodic cleanup.
        Should be called periodically by service to prevent memory growth.
        """
        now = datetime.now()
        cutoff = now - timedelta(hours=1)
        
        # Clean up old penalties
        expired_penalties = [
            user for user, until in self._user_penalties.items()
            if until < now
        ]
        for user in expired_penalties:
            del self._user_penalties[user]
        
        # Clean up old offense records
        old_offenses = [
            user for user, ts in self._last_offense.items()
            if ts < cutoff
        ]
        for user in old_offenses:
            if user in self._offense_counts:
                del self._offense_counts[user]
            del self._last_offense[user]
        
        # Clean up empty message deques
        empty_users = [
            user for user, msgs in self._user_messages.items()
            if not msgs or (msgs and msgs[-1] < cutoff)
        ]
        for user in empty_users:
            if user in self._user_messages:
                del self._user_messages[user]
            if user in self._last_messages:
                del self._last_messages[user]
        
        if expired_penalties or old_offenses or empty_users:
            logger.debug(
                f"Cleaned up spam tracking data: "
                f"{len(expired_penalties)} penalties, "
                f"{len(old_offenses)} offenses, "
                f"{len(empty_users)} user histories"
            )
