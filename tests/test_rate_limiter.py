"""Unit tests for RateLimiter component.

Tests multi-level rate limiting:
- Global per-minute and per-hour limits
- Per-user per-hour limits and cooldowns
- Per-trigger per-hour limits and cooldowns
- Mention-specific cooldowns
- Admin privilege multipliers
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from kryten_llm.components import RateLimiter, RateLimitDecision
from kryten_llm.models.events import TriggerResult


@pytest.mark.asyncio
class TestRateLimiterGlobalLimits:
    """Test global rate limits (per-minute and per-hour)."""
    
    async def test_first_response_always_allowed(self, llm_config_with_triggers):
        """First response should always be allowed."""
        limiter = RateLimiter(llm_config_with_triggers)
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context=""
        )
        
        decision = await limiter.check_rate_limit("user1", trigger_result, rank=1)
        
        assert decision.allowed is True
        assert decision.retry_after == 0
        assert decision.reason == "allowed"
    
    async def test_global_per_minute_limit(self, llm_config_with_triggers):
        """Should block when global per-minute limit reached."""
        limiter = RateLimiter(llm_config_with_triggers)
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="trigger_word",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context=""
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        # Config has global_max_per_minute=2
        # Allow first 2 responses (need to respect global cooldown of 15s)
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.now.return_value = base_time
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            decision1 = await limiter.check_rate_limit("user1", trigger_result, rank=1)
            assert decision1.allowed is True
            await limiter.record_response("user1", trigger_result)
            
            # Wait for global cooldown (15s)
            mock_dt.now.return_value = base_time + timedelta(seconds=20)
            decision2 = await limiter.check_rate_limit("user2", trigger_result, rank=1)
            assert decision2.allowed is True
            await limiter.record_response("user2", trigger_result)
            
            # Third within minute should be blocked by per-minute limit
            mock_dt.now.return_value = base_time + timedelta(seconds=40)
            decision3 = await limiter.check_rate_limit("user3", trigger_result, rank=1)
            assert decision3.allowed is False
            assert "global per-minute limit" in decision3.reason.lower()
            assert decision3.retry_after > 0
    
    async def test_global_per_hour_limit(self, llm_config_with_triggers):
        """Should block when global per-hour limit reached."""
        limiter = RateLimiter(llm_config_with_triggers)
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="trigger_word",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context=""
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        # Config has global_max_per_hour=20
        # Simulate 20 responses
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            for i in range(20):
                mock_dt.now.return_value = base_time + timedelta(minutes=i*2)
                decision = await limiter.check_rate_limit(f"user{i}", trigger_result, rank=1)
                assert decision.allowed is True
                await limiter.record_response(f"user{i}", trigger_result)
            
            # 21st should be blocked
            mock_dt.now.return_value = base_time + timedelta(minutes=45)
            decision = await limiter.check_rate_limit("user21", trigger_result, rank=1)
            assert decision.allowed is False
            assert "global per-hour limit" in decision.reason.lower()
    
    async def test_global_cooldown(self, llm_config_with_triggers):
        """Should enforce global cooldown between responses."""
        limiter = RateLimiter(llm_config_with_triggers)
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="trigger_word",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context=""
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        # Config has global_cooldown_seconds=15
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.now.return_value = base_time
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            decision1 = await limiter.check_rate_limit("user1", trigger_result, rank=1)
            assert decision1.allowed is True
            await limiter.record_response("user1", trigger_result)
            
            # Too soon (10 seconds later)
            mock_dt.now.return_value = base_time + timedelta(seconds=10)
            decision2 = await limiter.check_rate_limit("user2", trigger_result, rank=1)
            assert decision2.allowed is False
            assert "global cooldown" in decision2.reason.lower()
            assert decision2.retry_after >= 5  # At least 5 seconds remaining
            
            # After cooldown (20 seconds later)
            mock_dt.now.return_value = base_time + timedelta(seconds=20)
            decision3 = await limiter.check_rate_limit("user2", trigger_result, rank=1)
            assert decision3.allowed is True


@pytest.mark.asyncio
class TestRateLimiterUserLimits:
    """Test per-user rate limits and cooldowns."""
    
    async def test_user_per_hour_limit(self, llm_config_with_triggers):
        """Should block when user per-hour limit reached."""
        limiter = RateLimiter(llm_config_with_triggers)
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context=""
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        # Config has user_max_per_hour=5
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            # First 5 responses allowed
            for i in range(5):
                mock_dt.now.return_value = base_time + timedelta(minutes=i*10)
                decision = await limiter.check_rate_limit("user1", trigger_result, rank=1)
                assert decision.allowed is True
                await limiter.record_response("user1", trigger_result)
            
            # 6th response blocked
            mock_dt.now.return_value = base_time + timedelta(minutes=55)
            decision = await limiter.check_rate_limit("user1", trigger_result, rank=1)
            assert decision.allowed is False
            assert "per-hour limit" in decision.reason.lower()
    
    async def test_user_cooldown(self, llm_config_with_triggers):
        """Should enforce per-user cooldown."""
        limiter = RateLimiter(llm_config_with_triggers)
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context=""
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        # Config has user_cooldown_seconds=60
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.now.return_value = base_time
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            decision1 = await limiter.check_rate_limit("user1", trigger_result, rank=1)
            assert decision1.allowed is True
            await limiter.record_response("user1", trigger_result)
            
            # Too soon (30 seconds later)
            mock_dt.now.return_value = base_time + timedelta(seconds=30)
            decision2 = await limiter.check_rate_limit("user1", trigger_result, rank=1)
            assert decision2.allowed is False
            assert "user cooldown" in decision2.reason.lower()
            assert decision2.retry_after >= 30  # At least 30 seconds
            
            # After cooldown (130 seconds later - past mention cooldown of 120s)
            mock_dt.now.return_value = base_time + timedelta(seconds=130)
            decision3 = await limiter.check_rate_limit("user1", trigger_result, rank=1)
            assert decision3.allowed is True
    
    async def test_different_users_independent(self, llm_config_with_triggers):
        """Different users should have independent rate limits."""
        limiter = RateLimiter(llm_config_with_triggers)
        # Use trigger word instead of mention to avoid mention cooldown
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="trigger_word",
            trigger_name="hello",
            priority=8,
            cleaned_message="praise!",
            context="Respond enthusiastically about Robert Z'Dar"
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.now.return_value = base_time
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            # User1 gets response
            decision1 = await limiter.check_rate_limit("user1", trigger_result, rank=1)
            assert decision1.allowed is True
            await limiter.record_response("user1", trigger_result)
            
            # User2 should be allowed after global cooldown (20 seconds)
            mock_dt.now.return_value = base_time + timedelta(seconds=20)
            decision2 = await limiter.check_rate_limit("user2", trigger_result, rank=1)
            assert decision2.allowed is True


@pytest.mark.asyncio
class TestRateLimiterTriggerLimits:
    """Test per-trigger rate limits and cooldowns."""
    
    async def test_trigger_per_hour_limit(self, llm_config_with_triggers):
        """Should block when trigger per-hour limit reached."""
        limiter = RateLimiter(llm_config_with_triggers)
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="trigger_word",
            trigger_name="toddy",
            priority=8,
            cleaned_message="praise !",
            context="Respond enthusiastically about Robert Z'Dar"
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        # toddy trigger has max_responses_per_hour=10
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            # First 10 responses allowed
            for i in range(10):
                mock_dt.now.return_value = base_time + timedelta(minutes=i*5)
                decision = await limiter.check_rate_limit(f"user{i}", trigger_result, rank=1)
                assert decision.allowed is True
                await limiter.record_response(f"user{i}", trigger_result)
            
            # 11th response blocked
            mock_dt.now.return_value = base_time + timedelta(minutes=55)
            decision = await limiter.check_rate_limit("user11", trigger_result, rank=1)
            assert decision.allowed is False
            assert "per-hour limit" in decision.reason.lower()
    
    async def test_trigger_cooldown(self, llm_config_with_triggers):
        """Should enforce per-trigger cooldown."""
        limiter = RateLimiter(llm_config_with_triggers)
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="trigger_word",
            trigger_name="toddy",
            priority=8,
            cleaned_message="praise !",
            context="Respond enthusiastically about Robert Z'Dar"
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        # toddy trigger has cooldown_seconds=300
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.now.return_value = base_time
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            decision1 = await limiter.check_rate_limit("user1", trigger_result, rank=1)
            assert decision1.allowed is True
            await limiter.record_response("user1", trigger_result)
            
            # Too soon (100 seconds later)
            mock_dt.now.return_value = base_time + timedelta(seconds=100)
            decision2 = await limiter.check_rate_limit("user2", trigger_result, rank=1)
            assert decision2.allowed is False
            assert "cooldown active" in decision2.reason.lower() and "toddy" in decision2.reason.lower()
            assert decision2.retry_after >= 200  # At least 200 seconds
            
            # After cooldown (350 seconds later)
            mock_dt.now.return_value = base_time + timedelta(seconds=350)
            decision3 = await limiter.check_rate_limit("user2", trigger_result, rank=1)
            assert decision3.allowed is True
    
    async def test_different_triggers_independent(self, llm_config_with_triggers):
        """Different triggers should have independent rate limits."""
        limiter = RateLimiter(llm_config_with_triggers)
        
        toddy_trigger = TriggerResult(
            triggered=True,
            trigger_type="trigger_word",
            trigger_name="toddy",
            priority=8,
            cleaned_message="praise !",
            context="Respond enthusiastically about Robert Z'Dar"
        )
        
        kung_fu_trigger = TriggerResult(
            triggered=True,
            trigger_type="trigger_word",
            trigger_name="kung_fu",
            priority=5,
            cleaned_message="love !",
            context="Discuss martial arts philosophy briefly"
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.now.return_value = base_time
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            # Toddy trigger gets response
            decision1 = await limiter.check_rate_limit("user1", toddy_trigger, rank=1)
            assert decision1.allowed is True
            await limiter.record_response("user1", toddy_trigger)
            
            # Kung fu trigger should still be allowed (not affected by toddy cooldown)
            mock_dt.now.return_value = base_time + timedelta(seconds=20)
            decision2 = await limiter.check_rate_limit("user2", kung_fu_trigger, rank=1)
            assert decision2.allowed is True


@pytest.mark.asyncio
class TestRateLimiterMentionCooldown:
    """Test mention-specific cooldown."""
    
    async def test_mention_cooldown(self, llm_config_with_triggers):
        """Should enforce mention-specific cooldown."""
        limiter = RateLimiter(llm_config_with_triggers)
        mention_trigger = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context=""
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        # Config has mention_cooldown_seconds=120
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.now.return_value = base_time
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            decision1 = await limiter.check_rate_limit("user1", mention_trigger, rank=1)
            assert decision1.allowed is True
            await limiter.record_response("user1", mention_trigger)
            
            # Too soon (60 seconds later)
            mock_dt.now.return_value = base_time + timedelta(seconds=60)
            decision2 = await limiter.check_rate_limit("user2", mention_trigger, rank=1)
            assert decision2.allowed is False
            assert "mention cooldown" in decision2.reason.lower()
            assert decision2.retry_after >= 60  # At least 60 seconds
            
            # After cooldown (130 seconds later)
            mock_dt.now.return_value = base_time + timedelta(seconds=130)
            decision3 = await limiter.check_rate_limit("user2", mention_trigger, rank=1)
            assert decision3.allowed is True
    
    async def test_mention_cooldown_separate_from_trigger_word(self, llm_config_with_triggers):
        """Mention cooldown should be separate from trigger word cooldowns."""
        limiter = RateLimiter(llm_config_with_triggers)
        
        mention_trigger = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context=""
        )
        
        toddy_trigger = TriggerResult(
            triggered=True,
            trigger_type="trigger_word",
            trigger_name="toddy",
            priority=8,
            cleaned_message="praise !",
            context="Respond enthusiastically about Robert Z'Dar"
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.now.return_value = base_time
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            # Mention gets response
            decision1 = await limiter.check_rate_limit("user1", mention_trigger, rank=1)
            assert decision1.allowed is True
            await limiter.record_response("user1", mention_trigger)
            
            # Trigger word should still be allowed after global cooldown (20 seconds later)
            mock_dt.now.return_value = base_time + timedelta(seconds=20)
            decision2 = await limiter.check_rate_limit("user2", toddy_trigger, rank=1)
            assert decision2.allowed is True


@pytest.mark.asyncio
class TestRateLimiterAdminPrivileges:
    """Test admin privilege multipliers."""
    
    async def test_admin_reduced_cooldown(self, llm_config_with_triggers):
        """Admins should have reduced cooldowns (multiplier 0.5)."""
        limiter = RateLimiter(llm_config_with_triggers)
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context=""
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        # Config has user_cooldown_seconds=60, admin_cooldown_multiplier=0.5
        # Admin cooldown should be 30 seconds
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.now.return_value = base_time
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            decision1 = await limiter.check_rate_limit("admin", trigger_result, rank=3)
            assert decision1.allowed is True
            await limiter.record_response("admin", trigger_result)
            
            # Too soon for regular user (70 seconds)
            mock_dt.now.return_value = base_time + timedelta(seconds=70)
            decision2 = await limiter.check_rate_limit("admin", trigger_result, rank=3)
            assert decision2.allowed is True  # Admin cooldown is only 60 seconds (mention cooldown 120*0.5)
    
    async def test_admin_increased_limits(self, llm_config_with_triggers):
        """Admins should have increased limits (multiplier 2.0)."""
        limiter = RateLimiter(llm_config_with_triggers)
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context=""
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        # Config has user_max_per_hour=5, admin_limit_multiplier=2.0
        # Admin limit should be 10 per hour
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            # First 10 responses allowed for admin
            for i in range(10):
                mock_dt.now.return_value = base_time + timedelta(minutes=i*5)
                decision = await limiter.check_rate_limit("admin", trigger_result, rank=3)
                assert decision.allowed is True
                await limiter.record_response("admin", trigger_result)
            
            # 11th response blocked
            mock_dt.now.return_value = base_time + timedelta(minutes=55)
            decision = await limiter.check_rate_limit("admin", trigger_result, rank=3)
            assert decision.allowed is False
    
    async def test_rank_threshold_for_admin(self, llm_config_with_triggers):
        """Only rank >= 3 should get admin privileges."""
        limiter = RateLimiter(llm_config_with_triggers)
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="mention",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context=""
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        # Config has user_cooldown_seconds=60
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.now.return_value = base_time
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            # Rank 2 user (not admin)
            decision1 = await limiter.check_rate_limit("user1", trigger_result, rank=2)
            assert decision1.allowed is True
            await limiter.record_response("user1", trigger_result)
            
            # Too soon (40 seconds later) - full cooldown applies
            mock_dt.now.return_value = base_time + timedelta(seconds=40)
            decision2 = await limiter.check_rate_limit("user1", trigger_result, rank=2)
            assert decision2.allowed is False
            
            # Rank 3 user (admin)
            mock_dt.now.return_value = base_time + timedelta(seconds=70)
            decision3 = await limiter.check_rate_limit("admin", trigger_result, rank=3)
            assert decision3.allowed is True
            await limiter.record_response("admin", trigger_result)
            
            # After admin mention cooldown (130 seconds total - past 120*0.5=60s admin cooldown)
            mock_dt.now.return_value = base_time + timedelta(seconds=130)
            decision4 = await limiter.check_rate_limit("admin", trigger_result, rank=3)
            assert decision4.allowed is True


@pytest.mark.asyncio
class TestRateLimiterEdgeCases:
    """Test edge cases and special scenarios."""
    
    async def test_zero_cooldown_config(self, llm_config_with_triggers):
        """Should handle zero cooldown configuration."""
        # Modify config to have zero global cooldown but keep per-minute limit
        llm_config_with_triggers.rate_limits.global_cooldown_seconds = 0
        llm_config_with_triggers.rate_limits.global_max_per_minute = 10  # High enough to not interfere
        
        limiter = RateLimiter(llm_config_with_triggers)
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="trigger_word",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context=""
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.now.return_value = base_time
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            decision1 = await limiter.check_rate_limit("user1", trigger_result, rank=1)
            assert decision1.allowed is True
            await limiter.record_response("user1", trigger_result)
            
            # Immediate second response should be allowed (no global cooldown, different user)
            decision2 = await limiter.check_rate_limit("user2", trigger_result, rank=1)
            assert decision2.allowed is True
    
    async def test_rate_limit_decision_details(self, llm_config_with_triggers):
        """Should include detailed information in RateLimitDecision."""
        limiter = RateLimiter(llm_config_with_triggers)
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="trigger_word",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context=""
        )
        
        decision = await limiter.check_rate_limit("user1", trigger_result, rank=1)
        
        assert isinstance(decision, RateLimitDecision)
        assert hasattr(decision, 'allowed')
        assert hasattr(decision, 'reason')
        assert hasattr(decision, 'retry_after')
        assert hasattr(decision, 'details')
        assert isinstance(decision.details, dict)
    
    async def test_record_response_without_check(self, llm_config_with_triggers):
        """Should handle record_response called without prior check."""
        limiter = RateLimiter(llm_config_with_triggers)
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="trigger_word",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context=""
        )
        
        # Should not crash when recording without check
        await limiter.record_response("user1", trigger_result)
        
        # Subsequent check should reflect recorded response
        decision = await limiter.check_rate_limit("user1", trigger_result, rank=1)
        # Could be blocked by user cooldown depending on implementation
        assert isinstance(decision, RateLimitDecision)
    
    async def test_cleanup_old_timestamps(self, llm_config_with_triggers):
        """Should clean up timestamps older than tracking window."""
        limiter = RateLimiter(llm_config_with_triggers)
        trigger_result = TriggerResult(
            triggered=True,
            trigger_type="trigger_word",
            trigger_name="mention",
            priority=10,
            cleaned_message="hello",
            context=""
        )
        
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        
        with patch('kryten_llm.components.rate_limiter.datetime') as mock_dt:
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            # Add response
            mock_dt.now.return_value = base_time
            decision1 = await limiter.check_rate_limit("user1", trigger_result, rank=1)
            assert decision1.allowed is True
            await limiter.record_response("user1", trigger_result)
            
            # More than 1 hour later - old timestamp should be cleaned
            mock_dt.now.return_value = base_time + timedelta(hours=2)
            decision2 = await limiter.check_rate_limit("user1", trigger_result, rank=1)
            assert decision2.allowed is True  # Should be treated as first response
