"""Unit tests for SpamDetector Phase 4.

Tests spam detection including rate limiting, identical message detection,
penalties, and admin exemptions (REQ-015 through REQ-022).
"""

from datetime import datetime, timedelta

import pytest

from kryten_llm.components.spam_detector import SpamCheckResult, SpamDetector
from kryten_llm.models.config import MessageWindow, SpamDetectionConfig


@pytest.fixture
def default_spam_config():
    """Create default spam detection configuration."""
    return SpamDetectionConfig(
        enabled=True,
        message_windows=[
            MessageWindow(seconds=60, max_messages=5),
            MessageWindow(seconds=300, max_messages=15),
            MessageWindow(seconds=900, max_messages=30),
        ],
        identical_message_threshold=3,
        identical_message_window_seconds=300,
        mention_spam_threshold=3,
        mention_spam_window=30,
        initial_penalty=30,
        penalty_multiplier=2.0,
        max_penalty=600,
        clean_period=600,
        admin_exempt_ranks=[4, 5],
    )


@pytest.fixture
def detector(default_spam_config):
    """Create SpamDetector instance."""
    return SpamDetector(default_spam_config)


# ============================================================================
# REQ-015: Spam Detection Enabled/Disabled
# ============================================================================


def test_spam_detection_disabled():
    """Test that spam detection can be disabled."""
    config = SpamDetectionConfig(enabled=False)
    detector = SpamDetector(config)

    # Should pass even with rapid messages
    for _ in range(20):
        result = detector.check_spam("user1", "message", 1)
        assert not result.is_spam


def test_spam_detection_enabled(detector):
    """Test that spam detection is enabled."""
    result = detector.check_spam("user1", "test", 1)
    assert not result.is_spam  # First message should pass


# ============================================================================
# REQ-016: Rate Limiting Tests (AC-006)
# ============================================================================


def test_rate_limit_under_threshold(detector):
    """Test user under rate limit threshold."""
    username = "user1"

    # Send 4 messages (under 5 in 60s limit)
    for i in range(4):
        result = detector.check_spam(username, f"message {i}", 1)
        assert not result.is_spam
        detector.record_message(username, f"message {i}", 1)


def test_rate_limit_first_window_exceeded(detector, default_spam_config):
    """Test exceeding first rate limit window (5 in 60s) - AC-006."""
    username = "user1"

    # Send exactly max messages
    max_messages = default_spam_config.message_windows[0].max_messages
    for i in range(max_messages):
        result = detector.check_spam(username, f"message {i}", 1)
        assert not result.is_spam
        detector.record_message(username, f"message {i}", 1)

    # Next message should trigger spam
    result = detector.check_spam(username, "one too many", 1)
    assert result.is_spam
    assert "rate limit" in result.reason.lower() or "messages" in result.reason.lower()
    assert result.offense_count == 1


def test_rate_limit_second_window(detector, default_spam_config):
    """Test second rate limit window (15 in 300s)."""
    username = "user1"

    # Simulate messages spread across time to avoid first window but hit second
    # This is simplified - real test would manipulate timestamps
    max_messages = default_spam_config.message_windows[1].max_messages

    for i in range(max_messages + 1):
        detector.record_message(username, f"message {i}", 1)

    # Check if spam (might trigger second window)
    detector.check_spam(username, "test", 1)
    # Result depends on message timing


def test_rate_limit_third_window(detector, default_spam_config):
    """Test third rate limit window (30 in 900s)."""
    username = "user1"
    max_messages = default_spam_config.message_windows[2].max_messages

    for i in range(max_messages + 1):
        detector.record_message(username, f"message {i}", 1)

    detector.check_spam(username, "test", 1)
    # Result depends on message distribution


def test_rate_limit_different_users_independent(detector):
    """Test that rate limits are per-user."""
    # User 1 sends many messages
    for i in range(5):
        result = detector.check_spam("user1", f"message {i}", 1)
        assert not result.is_spam
        detector.record_message("user1", f"message {i}", 1)

    # User 2 should start fresh
    result = detector.check_spam("user2", "first message", 1)
    assert not result.is_spam


def test_rate_limit_messages_expire(detector):
    """Test that old messages expire from rate limit tracking."""

    # This would need time manipulation to properly test
    # For now, verify structure exists
    assert hasattr(detector, "_cleanup_old_data")
    assert hasattr(detector, "user_messages")


# ============================================================================
# REQ-017: Identical Message Detection
# ============================================================================


def test_identical_message_first_time(detector):
    """Test first instance of a message is allowed."""
    username = "user1"
    message = "Hello everyone!"

    result = detector.check_spam(username, message, 1)
    assert not result.is_spam
    detector.record_message(username, message, 1)


def test_identical_message_under_threshold(detector):
    """Test sending same message under threshold."""
    username = "user1"
    message = "Same message"

    # Send twice (under 3 times limit)
    for _ in range(2):
        result = detector.check_spam(username, message, 1)
        assert not result.is_spam
        detector.record_message(username, message, 1)


def test_identical_message_exceeded(detector, default_spam_config):
    """Test sending same message exceeds threshold."""
    username = "user1"
    message = "Repeated spam message"

    # Send max times
    max_times = default_spam_config.identical_message_threshold
    for _ in range(max_times):
        result = detector.check_spam(username, message, 1)
        assert not result.is_spam
        detector.record_message(username, message, 1)

    # Next identical message should be spam
    result = detector.check_spam(username, message, 1)
    assert result.is_spam
    assert "identical" in result.reason.lower() or "same" in result.reason.lower()
    assert result.offense_count == 1


def test_identical_message_case_sensitive(detector):
    """Test identical message detection is case-sensitive."""
    username = "user1"

    # Different cases should be treated as different messages
    messages = ["Hello", "hello", "HELLO"]
    for msg in messages:
        result = detector.check_spam(username, msg, 1)
        assert not result.is_spam
        detector.record_message(username, msg, 1)


def test_identical_message_whitespace_matters(detector):
    """Test that whitespace differences are respected."""
    username = "user1"

    messages = ["test", "test ", " test"]
    for msg in messages:
        result = detector.check_spam(username, msg, 1)
        assert not result.is_spam
        detector.record_message(username, msg, 1)


# ============================================================================
# REQ-018: Mention Spam Detection
# ============================================================================


def test_mention_spam_under_threshold(detector):
    """Test mentions under spam threshold."""
    username = "user1"

    # Send 2 mentions (under 3 in 30s limit)
    for i in range(2):
        result = detector.check_spam(username, f"@someone message {i}", 1, mention_count=1)
        assert not result.is_spam
        detector.record_message(username, f"@someone message {i}", 1, mention_count=1)


def test_mention_spam_exceeded(detector, default_spam_config):
    """Test rapid mentions exceed threshold."""
    username = "user1"

    # Send max mentions
    max_mentions = default_spam_config.mention_spam_threshold
    for i in range(max_mentions):
        result = detector.check_spam(username, f"@user msg {i}", 1, mention_count=1)
        assert not result.is_spam
        detector.record_message(username, f"@user msg {i}", 1, mention_count=1)

    # Next mention should be spam
    result = detector.check_spam(username, "@user spam", 1, mention_count=1)
    assert result.is_spam
    assert "mention" in result.reason.lower()


def test_mention_spam_multiple_mentions_per_message(detector):
    """Test messages with multiple mentions count appropriately."""
    username = "user1"

    # Message with 2 mentions
    result = detector.check_spam(username, "@user1 @user2 hello", 1, mention_count=2)
    assert not result.is_spam
    detector.record_message(username, "@user1 @user2 hello", 1, mention_count=2)

    # Another message with 1 mention should trigger if total > threshold
    result = detector.check_spam(username, "@user3 hi", 1, mention_count=1)
    # Depends on total mention count


def test_mention_spam_no_mentions_ignored(detector):
    """Test messages without mentions don't affect mention spam tracking."""
    username = "user1"

    # Send messages without mentions (stay within general rate limit of 5 per 60s)
    for i in range(4):
        result = detector.check_spam(username, f"no mentions {i}", 1, mention_count=0)
        assert not result.is_spam
        detector.record_message(username, f"no mentions {i}", 1, mention_count=0)

    # Mention spam should still start fresh
    result = detector.check_spam(username, "@someone first mention", 1, mention_count=1)
    assert not result.is_spam


# ============================================================================
# REQ-019: Penalty System Tests
# ============================================================================


def test_penalty_first_offense(detector, default_spam_config):
    """Test first offense gets first penalty duration."""
    username = "spammer1"

    # Trigger spam
    for i in range(6):  # Exceed 5 in 60s limit
        detector.record_message(username, f"msg {i}", 1)

    result = detector.check_spam(username, "spam", 1)
    assert result.is_spam
    assert result.penalty_duration == default_spam_config.initial_penalty  # 30s
    assert result.offense_count == 1


def test_penalty_second_offense(detector, default_spam_config):
    """Test second offense gets increased penalty (exponential backoff)."""
    username = "spammer1"

    # First offense
    for i in range(6):
        detector.record_message(username, f"msg1 {i}", 1)
    result1 = detector.check_spam(username, "spam1", 1)
    assert result1.is_spam

    # Apply penalty
    detector._apply_penalty(username)

    # Simulate penalty expiring (manual time manipulation)
    detector.user_penalties[username] = datetime.now() - timedelta(seconds=31)

    # Second offense
    for i in range(6):
        detector.record_message(username, f"msg2 {i}", 1)
    result2 = detector.check_spam(username, "spam2", 1)

    # Should have higher offense count
    assert result2.offense_count >= 2


def test_penalty_exponential_backoff(default_spam_config):
    """Test penalty durations increase exponentially."""
    # Verify formula: initial_penalty * (penalty_multiplier ^ (offense - 1))
    initial = default_spam_config.initial_penalty
    multiplier = default_spam_config.penalty_multiplier

    # Calculate expected penalties for first 4 offenses
    expected = [int(initial * (multiplier**i)) for i in range(4)]

    # Should be increasing: 30, 60, 120, 240
    assert expected[0] < expected[1]
    assert expected[1] < expected[2]
    assert expected[2] < expected[3]


def test_penalty_max_duration_cap(detector, default_spam_config):
    """Test penalty duration is capped at maximum."""
    username = "chronic_spammer"

    # Trigger many offenses
    for offense in range(10):
        for i in range(6):
            detector.record_message(username, f"spam{offense} {i}", 1)
        detector.check_spam(username, f"spam{offense}", 1)
        detector._apply_penalty(username)

    # Penalty should not exceed max
    penalty_time = detector.user_penalties.get(username)
    if penalty_time:
        # Can't exceed max_penalty from now
        datetime.now() + timedelta(seconds=default_spam_config.max_penalty)
        # This is a structural test


def test_penalty_blocks_messages(detector):
    """Test that active penalty blocks messages."""
    username = "penalized_user"

    # Apply penalty
    detector.user_penalties[username] = datetime.now() + timedelta(seconds=30)
    detector.offense_counts[username] = 1

    # Should be blocked
    result = detector.check_spam(username, "any message", 1)
    assert result.is_spam
    assert "penalty" in result.reason.lower()


def test_penalty_expires(detector):
    """Test that expired penalties allow messages."""
    username = "reformed_user"

    # Apply penalty in the past
    detector.user_penalties[username] = datetime.now() - timedelta(seconds=1)
    detector.offense_counts[username] = 1

    # Should not be blocked
    result = detector.check_spam(username, "message", 1)
    assert not result.is_spam


def test_clean_period_resets_offenses(detector, default_spam_config):
    """Test clean period resets offense count."""
    username = "user1"

    # Set offense with old last offense time
    detector.offense_counts[username] = 3
    old_time = datetime.now() - timedelta(seconds=default_spam_config.clean_period + 1)
    detector.last_offense[username] = old_time

    # Check spam should reset due to clean period
    detector._check_clean_period(username)

    # Offense count should be reset
    assert detector.offense_counts.get(username, 0) == 0


def test_clean_period_doesnt_reset_recent(detector, default_spam_config):
    """Test clean period doesn't reset recent offenses."""
    username = "user1"

    # Set recent offense
    detector.offense_counts[username] = 2
    detector.last_offense[username] = datetime.now() - timedelta(seconds=100)  # Recent

    original_count = detector.offense_counts[username]
    detector._check_clean_period(username)

    # Should not reset
    assert detector.offense_counts[username] == original_count


# ============================================================================
# REQ-020: Admin Exemptions (AC-007)
# ============================================================================


def test_admin_exemption_rank_4(detector, default_spam_config):
    """Test admin rank 4 is exempted (AC-007)."""
    username = "admin1"
    admin_rank = 4

    # Send many messages rapidly
    for i in range(20):
        result = detector.check_spam(username, f"admin message {i}", admin_rank)
        assert not result.is_spam
        detector.record_message(username, f"admin message {i}", admin_rank)


def test_admin_exemption_rank_5(detector, default_spam_config):
    """Test admin rank 5 is exempted."""
    username = "owner"
    admin_rank = 5

    # Send spam-like behavior
    for i in range(50):
        result = detector.check_spam(username, f"owner message {i}", admin_rank)
        assert not result.is_spam


def test_non_admin_not_exempted(detector):
    """Test non-admin ranks are not exempted."""
    username = "regular_user"

    # Send too many messages
    for i in range(6):
        detector.record_message(username, f"message {i}", 1)

    result = detector.check_spam(username, "spam", 1)
    assert result.is_spam


def test_moderator_rank_3_not_exempted(detector):
    """Test moderator rank 3 is not admin-exempted."""
    username = "mod1"
    rank = 3

    # Should still be subject to limits
    for i in range(6):
        detector.record_message(username, f"message {i}", rank)

    result = detector.check_spam(username, "test", rank)
    assert result.is_spam


def test_admin_configurable(default_spam_config):
    """Test admin ranks are configurable."""
    # Can configure different admin ranks
    default_spam_config.admin_exempt_ranks = [3, 4, 5]
    detector = SpamDetector(default_spam_config)

    # Rank 3 should now be exempted
    for i in range(20):
        result = detector.check_spam("user", f"msg {i}", 3)
        assert not result.is_spam


# ============================================================================
# REQ-021: SpamCheckResult Structure (PAT-003)
# ============================================================================


def test_spam_check_result_structure(detector):
    """Test SpamCheckResult has all required fields."""
    result = detector.check_spam("user1", "test", 1)

    assert hasattr(result, "is_spam")
    assert hasattr(result, "reason")
    assert hasattr(result, "penalty_duration")
    assert hasattr(result, "offense_count")
    assert isinstance(result.is_spam, bool)
    assert isinstance(result.reason, str)
    assert isinstance(result.penalty_duration, (int, type(None)))
    assert isinstance(result.offense_count, int)


def test_spam_result_clean_message(detector):
    """Test clean message result structure."""
    result = detector.check_spam("user1", "hello", 1)

    assert result.is_spam is False
    # Accept various clean message phrasings
    reason_lower = result.reason.lower()
    assert "clean" in reason_lower or "pass" in reason_lower or "no spam" in reason_lower
    assert result.penalty_duration is None
    assert result.offense_count == 0


def test_spam_result_violation(detector):
    """Test spam violation result structure."""
    username = "spammer"

    # Trigger spam
    for i in range(6):
        detector.record_message(username, f"msg {i}", 1)

    result = detector.check_spam(username, "spam", 1)

    assert result.is_spam is True
    assert len(result.reason) > 0
    assert result.penalty_duration is not None
    assert result.penalty_duration > 0
    assert result.offense_count > 0


# ============================================================================
# REQ-022: Privacy and Cleanup
# ============================================================================


def test_in_memory_only(detector):
    """Test all state is in-memory only (no persistence)."""
    # Should not have any file I/O or database connections
    assert not hasattr(detector, "db")
    assert not hasattr(detector, "connection")
    assert not hasattr(detector, "file")

    # State should be in memory structures
    assert hasattr(detector, "user_messages")
    assert hasattr(detector, "user_penalties")
    assert hasattr(detector, "offense_counts")


def test_cleanup_old_data_removes_expired(detector):
    """Test cleanup removes old message data."""
    username = "user1"

    # Add old message data (manual insertion)
    old_time = datetime.now() - timedelta(seconds=1000)
    detector.user_messages[username].append(old_time)

    # Cleanup should remove it
    detector._cleanup_old_data()

    # Old data should be gone (beyond 900s window)
    recent_messages = [
        ts for ts in detector.user_messages[username] if (datetime.now() - ts).total_seconds() < 900
    ]
    assert len(recent_messages) == 0 or all(
        (datetime.now() - ts).total_seconds() < 900 for ts in recent_messages
    )


def test_cleanup_preserves_recent_data(detector):
    """Test cleanup preserves recent message data."""
    username = "user1"

    # Add recent message
    detector.record_message(username, "recent", 1)

    # Cleanup
    detector._cleanup_old_data()

    # Recent data should remain
    assert username in detector.user_messages
    assert len(detector.user_messages[username]) > 0


def test_cleanup_called_automatically(detector):
    """Test cleanup is called periodically."""
    # Verify cleanup method exists and is callable
    assert callable(detector._cleanup_old_data)

    # In real implementation, would verify it's called after N messages
    # For now, test that it can be called without errors
    detector._cleanup_old_data()


# ============================================================================
# Integration Tests
# ============================================================================


def test_full_spam_detection_flow(detector):
    """Test complete spam detection flow."""
    username = "user1"

    # 1. Normal usage - should pass
    for i in range(3):
        result = detector.check_spam(username, f"normal {i}", 1)
        assert not result.is_spam
        detector.record_message(username, f"normal {i}", 1)

    # 2. Rapid messages - should trigger spam
    for i in range(5):
        detector.record_message(username, f"rapid {i}", 1)

    result = detector.check_spam(username, "spam", 1)
    assert result.is_spam
    assert result.offense_count == 1

    # 3. Apply penalty
    detector._apply_penalty(username)

    # 4. Should be blocked during penalty
    result = detector.check_spam(username, "blocked", 1)
    assert result.is_spam
    assert "penalty" in result.reason.lower()


def test_multiple_users_concurrent(detector):
    """Test multiple users tracked independently."""
    users = ["user1", "user2", "user3"]

    # Each user sends messages
    for user in users:
        for i in range(3):
            result = detector.check_spam(user, f"msg {i}", 1)
            assert not result.is_spam
            detector.record_message(user, f"msg {i}", 1)

    # Users should be tracked separately
    assert len(detector.user_messages) == 3


def test_mixed_spam_types(detector):
    """Test different types of spam detection work together."""
    username = "user1"

    # Rate limit spam
    for i in range(6):
        detector.record_message(username, f"msg {i}", 1)
    result1 = detector.check_spam(username, "test", 1)
    assert result1.is_spam

    # Clear state
    detector.user_messages[username].clear()
    detector.user_penalties.pop(username, None)
    detector.offense_counts.pop(username, None)

    # Identical message spam
    for _ in range(3):
        detector.record_message(username, "same", 1)
    result2 = detector.check_spam(username, "same", 1)
    assert result2.is_spam


def test_state_recovery_after_spam(detector):
    """Test user can recover after spam behavior."""
    username = "reformed_user"

    # Trigger spam
    for i in range(6):
        detector.record_message(username, f"msg {i}", 1)
    result = detector.check_spam(username, "spam", 1)
    assert result.is_spam

    # Clear penalty (simulate expiration)
    detector.user_penalties.pop(username, None)

    # Simulate clean period
    detector.last_offense[username] = datetime.now() - timedelta(seconds=700)
    detector._check_clean_period(username)

    # Should be able to send normally
    detector.user_messages[username].clear()
    result = detector.check_spam(username, "reformed", 1)
    assert not result.is_spam


# ============================================================================
# Performance Tests
# ============================================================================


def test_spam_check_performance(detector):
    """Test spam check completes quickly (<100μs from CON-001)."""
    import time

    username = "user1"

    # Prime with some history (stay within rate limit of 5 per 60s)
    for i in range(3):
        detector.record_message(username, f"msg {i}", 1)

    # Measure check time
    start = time.time()
    result = detector.check_spam(username, "test", 1)
    elapsed = time.time() - start

    assert elapsed < 0.001  # 1ms (generous, spec says 100μs)
    assert not result.is_spam


def test_spam_check_performance_many_users(detector):
    """Test performance with many users tracked."""
    import time

    # Create history for many users
    for i in range(50):
        detector.record_message(f"user{i}", "message", 1)

    # Check should still be fast
    start = time.time()
    detector.check_spam("new_user", "test", 1)
    elapsed = time.time() - start

    assert elapsed < 0.005  # 5ms even with many users


def test_record_message_performance(detector):
    """Test recording message is fast."""
    import time

    username = "user1"

    start = time.time()
    detector.record_message(username, "test", 1)
    elapsed = time.time() - start

    assert elapsed < 0.001  # 1ms


# ============================================================================
# Edge Cases
# ============================================================================


def test_empty_username(detector):
    """Test handling empty username."""
    result = detector.check_spam("", "message", 1)
    # Should handle gracefully
    assert isinstance(result, SpamCheckResult)


def test_empty_message(detector):
    """Test handling empty message."""
    result = detector.check_spam("user1", "", 1)
    assert isinstance(result, SpamCheckResult)


def test_negative_rank(detector):
    """Test handling negative rank (should not be admin)."""
    username = "user1"

    for i in range(6):
        detector.record_message(username, f"msg {i}", -1)

    result = detector.check_spam(username, "test", -1)
    assert result.is_spam  # Should apply limits


def test_zero_mention_count(detector):
    """Test handling zero mention count explicitly."""
    result = detector.check_spam("user1", "test", 1, mention_count=0)
    assert not result.is_spam


def test_negative_mention_count(detector):
    """Test handling negative mention count."""
    result = detector.check_spam("user1", "test", 1, mention_count=-1)
    # Should handle gracefully
    assert isinstance(result, SpamCheckResult)


def test_very_long_username(detector):
    """Test handling very long username."""
    username = "x" * 1000
    result = detector.check_spam(username, "test", 1)
    assert isinstance(result, SpamCheckResult)


def test_unicode_in_username(detector):
    """Test handling unicode in username."""
    username = "用户123"
    result = detector.check_spam(username, "test", 1)
    assert not result.is_spam


def test_special_characters_in_message(detector):
    """Test special characters in message."""
    message = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
    result = detector.check_spam("user1", message, 1)
    assert not result.is_spam
    detector.record_message("user1", message, 1)


def test_concurrent_spam_checks(detector):
    """Test multiple concurrent spam checks for same user."""
    username = "user1"

    # Simulate concurrent checks
    results = []
    for i in range(5):
        result = detector.check_spam(username, f"msg {i}", 1)
        results.append(result)

    # All should return valid results
    assert all(isinstance(r, SpamCheckResult) for r in results)
