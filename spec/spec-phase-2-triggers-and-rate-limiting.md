---
title: Phase 2 - Trigger Words & Rate Limiting
version: 1.0
date_created: 2025-01-20
last_updated: 2025-01-20
owner: kryten-llm
tags: [phase-2, architecture, design, triggers, rate-limiting]
---

# Introduction

This specification defines Phase 2 of the kryten-llm implementation: Trigger Words & Rate Limiting. Building on Phase 1's mention-based response system, Phase 2 adds sophisticated trigger word patterns with probabilities and comprehensive rate limiting to prevent spam while allowing engaging interactions.

Phase 2 transforms the bot from responding only to direct mentions into an active chat participant that can respond to specific topics or keywords, while maintaining responsible behavior through multi-level rate limiting.

## 1. Purpose & Scope

### Purpose

Extend kryten-llm with advanced triggering and rate limiting capabilities:
- Support trigger word patterns with configurable probabilities
- Implement multi-level rate limiting (global, per-user, per-trigger)
- Add admin/moderator privilege support for reduced cooldowns
- Log all responses with trigger and rate limit context for analysis
- Provide tools for monitoring trigger effectiveness and rate limit behavior

### Scope

**In Scope:**
- Enhanced TriggerEngine with pattern matching and probability
- RateLimiter component with multiple limiting strategies
- CooldownTracker for per-trigger, per-user cooldown management
- ResponseLogger for JSONL logging of all responses
- Admin rank detection and privilege multipliers
- Log analysis tools for trigger statistics and rate limit insights
- Integration of rate limiting into message processing pipeline

**Out of Scope (Future Phases):**
- Multi-provider LLM support with fallback (Phase 3)
- Context awareness (video metadata, chat history) (Phase 3)
- Intelligent sentence-aware message splitting (Phase 4)
- Response validation and quality checking (Phase 4)
- Service discovery and health monitoring (Phase 5)

### Intended Audience

- AI agents implementing the system
- Developers reviewing/maintaining the code
- Bot administrators configuring triggers and rate limits
- Analysts reviewing bot interaction patterns

### Assumptions

- Phase 1 is complete (MessageListener, TriggerEngine with mentions, LLMManager, PromptBuilder, ResponseFormatter)
- Configuration includes `triggers` list and `rate_limits` settings
- CyTube rank system is available (rank ≥ 2 indicates admin/moderator)
- Bot operates in channels with multiple simultaneous users
- Trigger patterns are defined as plain strings or simple patterns (not full regex in Phase 2)

## 2. Definitions

- **Trigger Word**: A keyword or phrase that may cause the bot to respond (e.g., "toddy", "kung fu")
- **Trigger Pattern**: A string to match in messages (case-insensitive), Phase 2 uses substring matching
- **Trigger Probability**: Float 0.0-1.0 indicating chance of responding when trigger matches
- **Cooldown**: Time period before the same trigger/user can trigger another response
- **Rate Limit**: Maximum number of responses allowed in a time window (minute/hour)
- **Global Rate Limit**: Limit applying to all bot responses regardless of source
- **User Rate Limit**: Limit applying to responses to a specific user
- **Trigger Rate Limit**: Limit applying to a specific trigger's activations
- **Admin Multiplier**: Factor applied to cooldowns/limits for privileged users (rank ≥ 3)
- **Response Logger**: Component that writes response events to JSONL for analysis
- **Trigger Context**: Additional information injected into LLM prompt for specific triggers

## 3. Requirements, Constraints & Guidelines

### Requirements

#### Trigger System

- **REQ-001**: TriggerEngine MUST load triggers from `config.triggers` list
- **REQ-002**: TriggerEngine MUST support mention detection (Phase 1) AND trigger words (Phase 2)
- **REQ-003**: TriggerEngine MUST perform case-insensitive pattern matching
- **REQ-004**: TriggerEngine MUST check trigger probability and randomly decide to activate
- **REQ-005**: TriggerEngine MUST return trigger context for prompt injection
- **REQ-006**: TriggerEngine MUST return trigger priority for response ordering
- **REQ-007**: TriggerEngine MUST skip disabled triggers (enabled=False)
- **REQ-008**: TriggerEngine MUST check mentions FIRST (priority over trigger words)
- **REQ-009**: Trigger patterns MUST support substring matching (e.g., "toddy" matches "praise toddy!")
- **REQ-010**: Multiple trigger matches MUST be resolved by priority (highest priority wins)

#### Rate Limiting

- **REQ-011**: RateLimiter MUST enforce global rate limits (messages per minute/hour)
- **REQ-012**: RateLimiter MUST enforce per-user rate limits (messages per user per hour)
- **REQ-013**: RateLimiter MUST enforce per-trigger rate limits (max_responses_per_hour)
- **REQ-014**: RateLimiter MUST apply global cooldown between ANY responses
- **REQ-015**: RateLimiter MUST apply user cooldown between responses to SAME user
- **REQ-016**: RateLimiter MUST apply mention cooldown for direct mentions
- **REQ-017**: RateLimiter MUST apply per-trigger cooldown from trigger config
- **REQ-018**: RateLimiter MUST detect admin users (rank ≥ 3)
- **REQ-019**: RateLimiter MUST apply admin_cooldown_multiplier to admin users' cooldowns
- **REQ-020**: RateLimiter MUST apply admin_limit_multiplier to admin users' rate limits
- **REQ-021**: RateLimiter MUST return detailed decision (allowed: bool, reason: str, retry_after: int)
- **REQ-022**: RateLimiter MUST update state after responses are sent (not just attempted)
- **REQ-023**: Rate limit state MUST be stored in-memory (no persistence required in Phase 2)

#### Response Logging

- **REQ-024**: ResponseLogger MUST log ALL responses to JSONL file
- **REQ-025**: ResponseLogger MUST include timestamp, trigger info, username, messages, rate limit status
- **REQ-026**: ResponseLogger MUST handle file I/O errors gracefully (log error, don't crash)
- **REQ-027**: ResponseLogger MUST create log directory if missing
- **REQ-028**: ResponseLogger MUST append to existing log file (don't overwrite)
- **REQ-029**: Log entries MUST be valid JSON objects (one per line)

#### Integration

- **REQ-030**: Message pipeline MUST check rate limits BEFORE calling LLM
- **REQ-031**: Message pipeline MUST record response AFTER sending to chat
- **REQ-032**: Message pipeline MUST log rate limit rejections (INFO level)
- **REQ-033**: Dry-run mode MUST still check rate limits (but not update state)
- **REQ-034**: Trigger context MUST be injected into user prompt
- **REQ-035**: All trigger and rate limit decisions MUST be logged (DEBUG level)

#### Configuration

- **REQ-036**: Config MUST support multiple triggers with individual settings
- **REQ-037**: Config MUST validate trigger patterns are non-empty
- **REQ-038**: Config MUST validate probabilities are 0.0-1.0
- **REQ-039**: Config MUST validate cooldowns are non-negative integers
- **REQ-040**: Config MUST support disabling triggers without removing them

### Constraints

- **CON-001**: Phase 2 MUST NOT implement regex patterns (simple substring matching only)
- **CON-002**: Phase 2 MUST NOT persist rate limit state (in-memory only)
- **CON-003**: Phase 2 MUST NOT implement context awareness (video, chat history - Phase 3)
- **CON-004**: Phase 2 MUST NOT implement multi-provider LLM (Phase 3)
- **CON-005**: Phase 2 MUST NOT implement response quality validation (Phase 4)
- **CON-006**: Rate limit state MUST use deques and dicts (no external storage)
- **CON-007**: Probability check MUST use random.random() for simplicity
- **CON-008**: Trigger patterns MUST be matched using case-insensitive substring search (not regex)
- **CON-009**: Admin detection MUST use rank from message metadata (no external lookups)

### Guidelines

- **GUD-001**: Log all rate limit decisions with clear reasoning
- **GUD-002**: Use descriptive variable names for rate limit windows and counts
- **GUD-003**: Keep rate limiter state management simple and auditable
- **GUD-004**: Make cooldown/limit multipliers configurable for easy tuning
- **GUD-005**: Use dataclasses for rate limit decisions (structured data)
- **GUD-006**: Keep trigger matching efficient (O(n) for n triggers)
- **GUD-007**: Document probability behavior clearly (users may not understand randomness)
- **GUD-008**: Provide helpful rate limit rejection messages for debugging
- **GUD-009**: Make log analysis scripts user-friendly with clear output
- **GUD-010**: Test edge cases (probability=0, probability=1, zero cooldowns)

### Patterns

- **PAT-001**: Use dataclasses for RateLimitDecision (allowed, reason, retry_after, details)
- **PAT-002**: Use collections.deque for time-windowed rate limiting
- **PAT-003**: Use dict[str, datetime] for cooldown tracking
- **PAT-004**: Use random.random() < probability for probability checks
- **PAT-005**: Use time.time() or datetime.now() for timestamps
- **PAT-006**: Use early returns to avoid deep nesting in rate limit checks
- **PAT-007**: Use pathlib.Path for file operations in ResponseLogger
- **PAT-008**: Use json.dumps() for JSONL serialization

## 4. Interfaces & Data Contracts

### Enhanced TriggerEngine Interface

```python
class TriggerEngine:
    """Detects trigger conditions in chat messages.
    
    Phase 1: Mention detection
    Phase 2: Mention detection + trigger word patterns with probabilities
    """
    
    def __init__(self, config: LLMConfig):
        """Initialize with configuration.
        
        Loads:
        - personality.name_variations (for mentions)
        - triggers list (for trigger words)
        """
        self.config = config
        self.name_variations = [n.lower() for n in config.personality.name_variations]
        # Sort by length (longest first) to prevent substring matching issues
        self.name_variations.sort(key=len, reverse=True)
        self.triggers = [t for t in config.triggers if t.enabled]
        # Sort triggers by priority (highest first)
        self.triggers.sort(key=lambda t: t.priority, reverse=True)
    
    async def check_triggers(self, message: dict) -> TriggerResult:
        """Check if message triggers a response.
        
        Processing order:
        1. Check mentions (highest priority)
        2. Check trigger words (by configured priority)
        3. Apply probability check if trigger matches
        
        Args:
            message: Filtered message dict from MessageListener
            
        Returns:
            TriggerResult with triggered=True/False and details
        """
        pass
    
    def _check_mention(self, message_text: str) -> TriggerResult | None:
        """Check for bot name mentions.
        
        Returns TriggerResult with trigger_type="mention" if found, else None.
        """
        pass
    
    def _check_trigger_words(self, message_text: str) -> TriggerResult | None:
        """Check for trigger word patterns.
        
        Returns TriggerResult with trigger_type="trigger_word" if found, else None.
        Applies probability check before returning triggered=True.
        """
        pass
    
    def _match_pattern(self, pattern: str, text: str) -> bool:
        """Check if pattern matches text (case-insensitive substring).
        
        Phase 2: Simple substring matching
        Phase 3+: Could add regex support
        """
        pass
    
    def _clean_message(self, message: str, trigger_name: str) -> str:
        """Remove trigger phrase from message for LLM processing."""
        pass
```

**TriggerResult Structure** (updated for Phase 2):
```python
@dataclass
class TriggerResult:
    triggered: bool              # True if should respond
    trigger_type: str | None     # "mention" or "trigger_word"
    trigger_name: str | None     # Name variation matched or trigger.name
    cleaned_message: str | None  # Message with trigger removed
    context: str | None          # Trigger-specific context for prompt (NEW in Phase 2)
    priority: int                # Priority level (10 for mentions, trigger.priority for words)
    
    def __bool__(self) -> bool:
        return self.triggered
```

**Trigger Matching Logic**:
1. Check mentions first (always priority 10)
2. If no mention, check triggers by priority order
3. For each trigger, check if ANY pattern matches (OR logic)
4. If match found, check probability: `random.random() < trigger.probability`
5. Return TriggerResult with trigger context

### RateLimiter Interface

```python
from dataclasses import dataclass
from datetime import datetime
from collections import deque


@dataclass
class RateLimitDecision:
    """Result of rate limit check."""
    
    allowed: bool                  # True if response allowed
    reason: str                    # Human-readable reason
    retry_after: int               # Seconds until next allowed (0 if allowed)
    details: dict                  # Additional context (limits, counts, cooldowns)


class RateLimiter:
    """Manages rate limiting for bot responses."""
    
    def __init__(self, config: LLMConfig):
        """Initialize rate limiter with configuration.
        
        Initializes in-memory state:
        - Global response timestamps (deque)
        - Per-user response timestamps (dict[username, deque])
        - Per-trigger response timestamps (dict[trigger_name, deque])
        - Last response time (datetime)
        - Last response per user (dict[username, datetime])
        - Last mention response time (datetime)
        - Last response per trigger (dict[trigger_name, datetime])
        """
        self.config = config
        self.rate_limits = config.rate_limits
        
        # Global rate tracking
        self.global_responses_minute: deque[datetime] = deque()  # maxlen set dynamically
        self.global_responses_hour: deque[datetime] = deque()
        self.last_response_time: datetime | None = None
        
        # Per-user rate tracking
        self.user_responses_hour: dict[str, deque[datetime]] = {}
        self.user_last_response: dict[str, datetime] = {}
        
        # Per-trigger rate tracking
        self.trigger_responses_hour: dict[str, deque[datetime]] = {}
        self.trigger_last_response: dict[str, datetime] = {}
        
        # Mention-specific tracking
        self.last_mention_response: datetime | None = None
    
    async def check_rate_limit(
        self,
        username: str,
        trigger_result: TriggerResult,
        rank: int = 1
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
        
        Applies admin multipliers if rank >= 3.
        
        Args:
            username: Username triggering response
            trigger_result: TriggerResult from TriggerEngine
            rank: User rank (default 1, admin >= 3)
            
        Returns:
            RateLimitDecision with allowed=True/False and details
        """
        pass
    
    async def record_response(
        self,
        username: str,
        trigger_result: TriggerResult
    ) -> None:
        """Record that a response was sent (update state).
        
        Updates:
        - Global response timestamps
        - User response timestamp
        - Trigger response timestamp
        - Cooldown timestamps
        """
        pass
    
    def _is_admin(self, rank: int) -> bool:
        """Check if user is admin/moderator."""
        return rank >= 2
    
    def _apply_admin_multiplier(
        self,
        value: int | float,
        multiplier: float,
        is_admin: bool
    ) -> int | float:
        """Apply admin multiplier to cooldown or limit."""
        if is_admin:
            return int(value * multiplier) if isinstance(value, int) else value * multiplier
        return value
    
    def _clean_old_timestamps(self, timestamps: deque[datetime], window_seconds: int) -> None:
        """Remove timestamps older than window from deque."""
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
    
    def _check_global_limits(self, is_admin: bool) -> RateLimitDecision | None:
        """Check global rate limits. Returns decision if blocked, None if allowed."""
        pass
    
    def _check_user_limits(self, username: str, is_admin: bool) -> RateLimitDecision | None:
        """Check per-user rate limits. Returns decision if blocked, None if allowed."""
        pass
    
    def _check_trigger_limits(
        self,
        trigger_result: TriggerResult,
        is_admin: bool
    ) -> RateLimitDecision | None:
        """Check per-trigger rate limits. Returns decision if blocked, None if allowed."""
        pass
```

**Rate Limit Check Order**:
```
1. Clean old timestamps from all deques
2. Determine if user is admin (rank >= 3)
3. Check global per-minute limit
4. Check global per-hour limit
5. Check global cooldown (seconds since last response)
6. Check user per-hour limit
7. Check user cooldown (seconds since last response to this user)
8. If mention: check mention cooldown
9. Check trigger per-hour limit (trigger.max_responses_per_hour)
10. Check trigger cooldown (trigger.cooldown_seconds)
11. All checks passed → RateLimitDecision(allowed=True)
```

**Admin Multipliers**:
- Cooldowns: multiplied by `admin_cooldown_multiplier` (default 0.5 = half cooldown)
- Limits: multiplied by `admin_limit_multiplier` (default 2.0 = double capacity)

### ResponseLogger Interface

```python
import json
from datetime import datetime
from pathlib import Path


class ResponseLogger:
    """Logs bot responses to JSONL file for analysis."""
    
    def __init__(self, config: LLMConfig):
        """Initialize logger with configuration.
        
        Creates log directory if missing.
        """
        self.config = config
        self.log_path = Path(config.testing.log_file)
        self.enabled = config.testing.log_responses
        
        # Create directory
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
    
    async def log_response(
        self,
        username: str,
        trigger_result: TriggerResult,
        input_message: str,
        llm_response: str,
        formatted_parts: list[str],
        rate_limit_decision: RateLimitDecision,
        sent: bool
    ) -> None:
        """Log a response event to JSONL file.
        
        Args:
            username: User who triggered response
            trigger_result: TriggerResult from trigger check
            input_message: Original user message
            llm_response: Raw LLM response
            formatted_parts: List of formatted message parts
            rate_limit_decision: Rate limit decision details
            sent: Whether response was actually sent (False if dry-run)
        """
        if not self.enabled:
            return
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "trigger_type": trigger_result.trigger_type,
            "trigger_name": trigger_result.trigger_name,
            "trigger_priority": trigger_result.priority,
            "username": username,
            "input_message": input_message,
            "cleaned_message": trigger_result.cleaned_message,
            "llm_response": llm_response,
            "formatted_parts": formatted_parts,
            "response_sent": sent,
            "rate_limit": {
                "allowed": rate_limit_decision.allowed,
                "reason": rate_limit_decision.reason,
                "retry_after": rate_limit_decision.retry_after,
                "details": rate_limit_decision.details
            }
        }
        
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error(f"Failed to write response log: {e}")
```

**JSONL Format Example**:
```json
{"timestamp": "2025-01-20T14:30:00.123456", "trigger_type": "trigger_word", "trigger_name": "toddy", "trigger_priority": 8, "username": "moviefan", "input_message": "praise toddy!", "cleaned_message": "praise!", "llm_response": "The divine energy flows through all of us!", "formatted_parts": ["The divine energy flows through all of us!"], "response_sent": true, "rate_limit": {"allowed": true, "reason": "allowed", "retry_after": 0, "details": {"global_count_minute": 1, "global_count_hour": 5, "user_count_hour": 2, "trigger_count_hour": 1}}}
{"timestamp": "2025-01-20T14:30:10.234567", "trigger_type": "mention", "trigger_name": "cynthia", "trigger_priority": 10, "username": "moviefan", "input_message": "hey cynthia what's up", "cleaned_message": "what's up", "llm_response": "Just staying sharp, you know how it is!", "formatted_parts": ["Just staying sharp, you know how it is!"], "response_sent": false, "rate_limit": {"allowed": false, "reason": "user cooldown", "retry_after": 50, "details": {"user_last_response": "2025-01-20T14:30:00", "user_cooldown_seconds": 60}}}
```

### Enhanced PromptBuilder Interface

```python
class PromptBuilder:
    """Constructs prompts for LLM generation.
    
    Phase 1: Basic system and user prompts
    Phase 2: Add trigger context injection
    Phase 3: Add video and chat history context
    """
    
    def __init__(self, config: LLMConfig):
        """Initialize with configuration."""
        self.config = config
    
    def build_system_prompt(self) -> str:
        """Build system prompt from personality configuration.
        
        Same as Phase 1.
        """
        pass
    
    def build_user_prompt(
        self,
        username: str,
        message: str,
        trigger_context: str | None = None
    ) -> str:
        """Build user prompt from message.
        
        Phase 2 enhancement: Optionally inject trigger context.
        
        Args:
            username: Username of message sender
            message: Cleaned message text
            trigger_context: Optional context from trigger (NEW)
            
        Returns:
            User prompt text
        """
        # Phase 1 format: "{username} says: {message}"
        # Phase 2 format with context: "{username} says: {message}\n\nContext: {trigger_context}"
        pass
```

**User Prompt Template (Phase 2)**:
```
Without context:
{username} says: {message}

With context:
{username} says: {message}

Context: {trigger_context}
```

**Example with Trigger Context**:
```
moviefan says: praise toddy!

Context: Respond enthusiastically about Robert Z'Dar and his iconic chin. Keep it brief and energetic.
```

### Integration in LLMService

```python
async def _handle_chat_message(self, subject: str, data: dict) -> None:
    """Handle chatMsg events (Phase 2 enhanced).
    
    Processing pipeline:
    1. Filter message (MessageListener)
    2. Check triggers (TriggerEngine - ENHANCED)
    3. Check rate limits (RateLimiter - NEW)
    4. Build prompts (PromptBuilder - ENHANCED with context)
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
    
    # 2. Check triggers (mentions + trigger words)
    trigger_result = await self.trigger_engine.check_triggers(filtered)
    if not trigger_result:
        return
    
    logger.info(
        f"Triggered by {trigger_result.trigger_type} '{trigger_result.trigger_name}': "
        f"{filtered['username']}"
    )
    
    # 3. Check rate limits (NEW)
    rank = filtered.get("meta", {}).get("rank", 1)
    rate_limit_decision = await self.rate_limiter.check_rate_limit(
        filtered["username"],
        trigger_result,
        rank
    )
    
    if not rate_limit_decision.allowed:
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
    
    # 4. Build prompts (with trigger context)
    system_prompt = self.prompt_builder.build_system_prompt()
    user_prompt = self.prompt_builder.build_user_prompt(
        filtered["username"],
        trigger_result.cleaned_message,
        trigger_result.context  # NEW
    )
    
    # 5. Generate response
    llm_response = await self.llm_manager.generate_response(
        system_prompt,
        user_prompt
    )
    
    if not llm_response:
        logger.error("LLM failed to generate response")
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
    
    # 8. Record response (update rate limit state) (NEW)
    if sent or not self.config.testing.dry_run:
        await self.rate_limiter.record_response(
            filtered["username"],
            trigger_result
        )
    
    # 9. Log response (NEW)
    await self.response_logger.log_response(
        filtered["username"],
        trigger_result,
        filtered["msg"],
        llm_response,
        formatted_parts,
        rate_limit_decision,
        sent
    )
```

## 5. Acceptance Criteria

### Component Creation

- **AC-001**: Given Phase 1 is complete, When I enhance `trigger_engine.py`, Then it loads triggers from config and supports pattern matching
- **AC-002**: Given Phase 1 is complete, When I create `rate_limiter.py`, Then it contains RateLimiter class with check_rate_limit and record_response methods
- **AC-003**: Given Phase 1 is complete, When I create `response_logger.py`, Then it contains ResponseLogger class with log_response method
- **AC-004**: Given Phase 1 is complete, When I update `prompt_builder.py`, Then build_user_prompt accepts optional trigger_context parameter
- **AC-005**: Given all components are created, When I import them in service.py, Then all imports work without errors

### Trigger System

- **AC-006**: Given TriggerEngine is initialized with triggers, When message contains trigger pattern, Then check_triggers returns TriggerResult with trigger_type="trigger_word"
- **AC-007**: Given TriggerEngine has trigger with probability=1.0, When pattern matches, Then always returns triggered=True
- **AC-008**: Given TriggerEngine has trigger with probability=0.0, When pattern matches, Then always returns triggered=False
- **AC-009**: Given TriggerEngine has trigger with probability=0.5, When pattern matches 100 times, Then ~50 return triggered=True
- **AC-010**: Given TriggerEngine has multiple triggers, When message matches multiple patterns, Then highest priority trigger wins
- **AC-011**: Given TriggerEngine checks mention and trigger word, When message has mention, Then mention takes priority (trigger_type="mention")
- **AC-012**: Given trigger has context configured, When trigger matches, Then TriggerResult.context contains trigger context
- **AC-013**: Given trigger is disabled (enabled=False), When pattern matches, Then trigger is skipped
- **AC-014**: Given trigger pattern is "kung fu", When message is "I love KUNG FU movies", Then pattern matches (case-insensitive)
- **AC-015**: Given trigger pattern matches, When message is cleaned, Then trigger phrase is removed

### Rate Limiting

- **AC-016**: Given RateLimiter is initialized, When global per-minute limit is reached, Then check_rate_limit returns allowed=False
- **AC-017**: Given RateLimiter is initialized, When global per-hour limit is reached, Then check_rate_limit returns allowed=False
- **AC-018**: Given RateLimiter recorded response, When check within global cooldown, Then returns allowed=False with retry_after
- **AC-019**: Given RateLimiter has user response history, When user per-hour limit reached, Then returns allowed=False for that user
- **AC-020**: Given RateLimiter recorded user response, When check within user cooldown, Then returns allowed=False for that user
- **AC-021**: Given RateLimiter recorded mention response, When check within mention cooldown, Then returns allowed=False
- **AC-022**: Given RateLimiter tracks trigger, When trigger per-hour limit reached, Then returns allowed=False for that trigger
- **AC-023**: Given RateLimiter recorded trigger response, When check within trigger cooldown, Then returns allowed=False
- **AC-024**: Given user has rank=3 (admin), When check_rate_limit is called, Then cooldowns are reduced by admin_cooldown_multiplier
- **AC-025**: Given user has rank=3 (admin), When check_rate_limit is called, Then limits are increased by admin_limit_multiplier
- **AC-026**: Given rate limit check passes, When check_rate_limit is called, Then returns RateLimitDecision with allowed=True
- **AC-027**: Given rate limit check fails, When check_rate_limit is called, Then reason explains which limit was hit
- **AC-028**: Given response was sent, When record_response is called, Then all relevant state is updated

### Response Logging

- **AC-029**: Given ResponseLogger is initialized, When log_response is called, Then entry is appended to JSONL file
- **AC-030**: Given ResponseLogger writes entry, When entry is written, Then it contains all required fields (timestamp, trigger, message, response, rate_limit)
- **AC-031**: Given log file doesn't exist, When first log_response is called, Then file is created with correct structure
- **AC-032**: Given log directory doesn't exist, When ResponseLogger initializes, Then directory is created
- **AC-033**: Given log_responses=False in config, When log_response is called, Then nothing is written
- **AC-034**: Given file write fails, When log_response is called, Then error is logged but service doesn't crash

### Integration

- **AC-035**: Given service is running, When message triggers response, Then rate limits are checked before LLM call
- **AC-036**: Given service is running, When rate limit blocks response, Then decision is logged and no LLM call is made
- **AC-037**: Given service is running, When response is sent, Then rate limit state is updated
- **AC-038**: Given service is running, When response is sent, Then event is logged to JSONL
- **AC-039**: Given service is running with dry_run=True, When trigger matches, Then rate limits are checked but not updated
- **AC-040**: Given trigger has context, When response is generated, Then context is included in user prompt
- **AC-041**: Given admin user triggers response, When rate limits are checked, Then admin multipliers are applied
- **AC-042**: Given multiple users trigger responses, When rate limits are checked, Then per-user state is tracked independently

### Testing

- **AC-043**: Given test suite exists, When I run `pytest tests/test_trigger_engine.py`, Then all enhanced trigger tests pass
- **AC-044**: Given test suite exists, When I run `pytest tests/test_rate_limiter.py`, Then all rate limiter tests pass
- **AC-045**: Given test suite exists, When I run `pytest tests/test_response_logger.py`, Then all response logger tests pass
- **AC-046**: Given service is running in test environment, When I send trigger word message, Then end-to-end flow completes successfully

## 6. Test Automation Strategy

### Test Levels

**Unit Tests** (Priority: High)
- Test TriggerEngine with various patterns and probabilities
- Test RateLimiter with all limit types and cooldowns
- Test ResponseLogger file operations
- Mock external dependencies (time, random, file I/O)
- Focus on edge cases (zero cooldowns, probability boundaries)

**Integration Tests** (Priority: High)
- Test message pipeline with rate limiting
- Test trigger + rate limit + logging flow
- Test admin privilege application
- Use test configuration with short cooldowns

**End-to-End Tests** (Priority: Medium for Phase 2)
- Manual testing in CyTube channel
- Test trigger word activation
- Test rate limit enforcement
- Test admin user behavior

### Test Frameworks

- **Unit Testing**: pytest
- **Async Testing**: pytest-asyncio
- **Mocking**: pytest-mock, unittest.mock
- **Time Mocking**: freezegun or manual mocking
- **Assertions**: Standard assertions, pytest raises

### Test Organization

```
tests/
├── conftest.py                      # Shared fixtures (enhanced)
├── test_config.py                   # Config tests (from Phase 0)
├── test_listener.py                 # MessageListener tests (Phase 1)
├── test_trigger_engine.py           # Enhanced trigger tests
├── test_llm_manager.py              # LLMManager tests (Phase 1)
├── test_prompt_builder.py           # Enhanced prompt tests
├── test_formatter.py                # ResponseFormatter tests (Phase 1)
├── test_rate_limiter.py             # NEW: RateLimiter tests
├── test_response_logger.py          # NEW: ResponseLogger tests
└── test_service_integration.py      # Enhanced integration tests
```

### Test Data Management

**Enhanced Fixtures** (in conftest.py):
```python
@pytest.fixture
def trigger_word_message():
    """Message with trigger word for testing."""
    return {
        "username": "testuser",
        "msg": "praise toddy!",
        "time": 1640000000,
        "meta": {"rank": 1}
    }

@pytest.fixture
def admin_message():
    """Message from admin user."""
    return {
        "username": "admin",
        "msg": "hey cynthia",
        "time": 1640000000,
        "meta": {"rank": 3}
    }

@pytest.fixture
def sample_triggers():
    """Sample trigger configurations."""
    return [
        Trigger(
            name="toddy",
            patterns=["toddy", "robert z'dar"],
            probability=1.0,
            cooldown_seconds=300,
            context="Respond enthusiastically about Robert Z'Dar",
            max_responses_per_hour=10,
            priority=8
        ),
        Trigger(
            name="kung_fu",
            patterns=["kung fu", "martial arts"],
            probability=0.3,
            cooldown_seconds=600,
            context="",
            max_responses_per_hour=5,
            priority=5
        )
    ]

@pytest.fixture
def rate_limiter_config():
    """Rate limiter configuration for testing."""
    return RateLimits(
        global_max_per_minute=2,
        global_max_per_hour=20,
        global_cooldown_seconds=15,
        user_max_per_hour=5,
        user_cooldown_seconds=60,
        mention_cooldown_seconds=120,
        admin_cooldown_multiplier=0.5,
        admin_limit_multiplier=2.0
    )
```

### Coverage Requirements

- **Minimum Coverage**: 75% overall (up from 70% in Phase 1)
- **Critical Components**: 90% coverage
  - TriggerEngine (pattern matching, probability)
  - RateLimiter (all limit types, cooldowns, admin handling)
  - ResponseLogger (file operations, error handling)
- **Integration Tests**: At least 10 end-to-end scenarios

### CI/CD Integration

**GitHub Actions Pipeline** (enhanced from Phase 1):
```yaml
name: Test Phase 2

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: poetry install
      - name: Run unit tests
        run: poetry run pytest tests/ -v --cov=kryten_llm --cov-report=xml
      - name: Check coverage
        run: poetry run pytest --cov=kryten_llm --cov-fail-under=75
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

## 7. Rationale & Context

### Design Decisions

**Decision 1: Substring Matching vs. Regex for Trigger Patterns**
- **Rationale**: Substring matching is simpler, safer (no regex injection), and sufficient for most use cases. Regex can be added in Phase 3+ if needed.
- **Alternative**: Implement full regex support immediately
- **Trade-off**: Less flexibility in pattern matching, but simpler configuration and lower complexity

**Decision 2: In-Memory Rate Limit State vs. Persistent Storage**
- **Rationale**: In-memory state is sufficient for Phase 2. Service restarts reset state, which is acceptable for a chat bot. Persistence adds complexity for minimal benefit.
- **Alternative**: Store state in Redis or SQLite
- **Trade-off**: State lost on restart, but much simpler implementation

**Decision 3: Multiple Rate Limit Checks vs. Single Unified Check**
- **Rationale**: Separate checks for global, user, and trigger limits provide clear audit trail and fine-grained control. Each check has specific parameters and multipliers.
- **Alternative**: Combine all checks into one complex function
- **Trade-off**: More code, but clearer logic and easier to debug

**Decision 4: Priority-Based Trigger Resolution**
- **Rationale**: When multiple triggers match, highest priority wins. This allows admins to control which triggers take precedence (e.g., mentions always win with priority=10).
- **Alternative**: First match wins, or return all matches
- **Trade-off**: Requires priority configuration, but provides clear control over behavior

**Decision 5: Probability Check After Pattern Match**
- **Rationale**: Check pattern first (fast), then roll dice (also fast). This keeps trigger logic simple and predictable.
- **Alternative**: Complex weighted selection across all matching triggers
- **Trade-off**: Only one trigger can activate per message, but implementation is straightforward

**Decision 6: Admin Detection via Rank Metadata**
- **Rationale**: CyTube provides rank in message metadata. Using this is simple and requires no external lookups. Rank ≥ 3 is standard for admin/moderator.
- **Alternative**: Maintain separate admin list in config
- **Trade-off**: Tied to CyTube's rank system, but no configuration needed

**Decision 7: JSONL Format for Response Logging**
- **Rationale**: JSONL (one JSON object per line) is simple, append-friendly, and easily parsed by standard tools (jq, Python json module). No database setup required.
- **Alternative**: SQLite database, CSV file, or structured logging
- **Trade-off**: No query capabilities, but extremely simple and portable

**Decision 8: Separate ResponseLogger Component**
- **Rationale**: Logging is a cross-cutting concern that should be separate from core logic. Makes it easy to disable, redirect, or enhance logging without touching pipeline code.
- **Alternative**: Inline logging in service.py
- **Trade-off**: Extra component, but better separation of concerns

### Architecture Context

**Enhanced Message Flow**:
```
NATS chatMsg Event
    ↓
MessageListener.filter_message() → dict | None
    ↓
TriggerEngine.check_triggers() → TriggerResult (mentions + trigger words + probability)
    ↓
RateLimiter.check_rate_limit() → RateLimitDecision
    ↓ (if allowed)
PromptBuilder.build_*_prompt() → str, str (with trigger context)
    ↓
LLMManager.generate_response() → str | None
    ↓
ResponseFormatter.format_response() → list[str]
    ↓
client.send_chat_message() or log (dry-run)
    ↓
RateLimiter.record_response() (update state)
    ↓
ResponseLogger.log_response() (write to JSONL)
```

**Component Dependencies**:
- MessageListener: Depends on LLMConfig (unchanged)
- TriggerEngine: Depends on LLMConfig (personality, triggers) **ENHANCED**
- RateLimiter: Depends on LLMConfig (rate_limits) **NEW**
- ResponseLogger: Depends on LLMConfig (testing.log_file, testing.log_responses) **NEW**
- LLMManager: Depends on LLMConfig (unchanged)
- PromptBuilder: Depends on LLMConfig (personality) **ENHANCED**
- ResponseFormatter: Depends on LLMConfig (unchanged)
- LLMService: Depends on all components + KrytenClient **ENHANCED**

**State Management**:
- RateLimiter maintains in-memory state (deques and dicts)
- State is lost on service restart (acceptable for Phase 2)
- No persistence layer required
- All state is time-based (self-cleaning with deques)

**Extension Points for Future Phases**:
- TriggerEngine: Add regex support (Phase 3), add context from video/history (Phase 3)
- RateLimiter: Add persistent state (optional Phase 5), add burst allowances (optional)
- ResponseLogger: Add structured logging backend (optional Phase 5)
- PromptBuilder: Add video metadata (Phase 3), add chat history (Phase 3)

## 8. Dependencies & External Integrations

### External Systems

- **EXT-001**: NATS message broker - Required for receiving chatMsg events
  - Integration Type: Message bus subscription
  - No changes from Phase 1

- **EXT-002**: CyTube chat server - Source of rank metadata for admin detection
  - Integration Type: Indirect via message metadata
  - New Requirement: Rank field in message metadata (meta.rank)

### Third-Party Services

- **SVC-001**: LLM API Provider (OpenAI-compatible) - Required for response generation
  - No changes from Phase 1

### Infrastructure Dependencies

- **INF-001**: Python 3.11+ runtime - Required for union types and async
  - No changes from Phase 1

- **INF-002**: Filesystem access - Required for JSONL logging
  - Requirements: Write access to logs directory
  - New Requirement: logs/ directory must be writable

- **INF-003**: System time - Required for rate limiting timestamps
  - Requirements: Monotonic time source (time.time() or datetime.now())
  - Constraint: System clock should be reasonably accurate

### Data Dependencies

- **DAT-001**: Configuration file (config.json) - Required at service startup
  - Format: Enhanced with triggers and rate_limits sections
  - New Fields: triggers list, rate_limits settings

### Technology Platform Dependencies

- **PLT-001**: kryten-py ^0.6.0 - Required for NATS client
  - No changes from Phase 1

- **PLT-002**: aiohttp ^3.13.2 - Required for async HTTP
  - No changes from Phase 1

- **PLT-003**: pydantic ^2.12.5 - Required for configuration validation
  - No changes from Phase 1

### Compliance Dependencies

- **COM-001**: Rate limiting best practices - Prevent abuse and spam
  - Rationale: Responsible bot behavior in shared chat environments

- **COM-002**: Logging privacy - Response logs may contain user data
  - Rationale: Consider data retention and privacy policies
  - Note: Logs should be secured and rotated appropriately

## 9. Examples & Edge Cases

### Example 1: Trigger Word with Probability

**Config:**
```json
{
  "name": "kung_fu",
  "patterns": ["kung fu", "martial arts"],
  "probability": 0.3,
  "cooldown_seconds": 600,
  "context": "Discuss martial arts philosophy briefly.",
  "max_responses_per_hour": 5,
  "priority": 5,
  "enabled": true
}
```

**Input:**
```json
{
  "username": "moviefan",
  "msg": "I love kung fu movies!",
  "time": 1640000000,
  "meta": {"rank": 1}
}
```

**Processing:**
1. MessageListener: Valid → Pass
2. TriggerEngine: 
   - Check mentions: No match
   - Check triggers: "kung fu" matches pattern
   - Roll probability: random.random() = 0.25 < 0.3 → triggered=True
   - Return TriggerResult(triggered=True, trigger_type="trigger_word", trigger_name="kung_fu", cleaned_message="I love movies!", context="Discuss martial arts philosophy briefly.", priority=5)
3. RateLimiter: Check all limits → allowed=True
4. PromptBuilder: Include context in user prompt
5-7. Continue normal flow
8. Record response (update trigger cooldown, rate counts)
9. Log to JSONL

**Note**: If random.random() = 0.35 > 0.3, triggered=False and pipeline stops at step 2.

### Example 2: Rate Limit - Global Per-Minute

**Scenario**: Bot has responded 2 times in last 60 seconds (limit=2)

**Input**: Valid mention message

**Processing:**
1-2. Message filtered and trigger detected
3. RateLimiter.check_rate_limit():
   - Clean old timestamps (keep only last 60 seconds)
   - Check global_max_per_minute: Count = 2, Limit = 2 → BLOCKED
   - Return RateLimitDecision(allowed=False, reason="global per-minute limit reached", retry_after=15, details={...})
4. Pipeline: Log rate limit block, skip LLM call
5. ResponseLogger: Log blocked attempt with rate_limit.allowed=False

**Output**: No response sent, rate limit logged

### Example 3: Rate Limit - User Cooldown

**Scenario**: Bot responded to "alice" 30 seconds ago (cooldown=60s)

**Input**: alice mentions bot again

**Processing:**
1-2. Message filtered and trigger detected (mention)
3. RateLimiter.check_rate_limit(username="alice", rank=1):
   - Check global limits: Pass
   - Check user cooldown: Last response 30s ago, cooldown 60s → BLOCKED
   - Return RateLimitDecision(allowed=False, reason="user cooldown active", retry_after=30, details={...})
4. Pipeline stops, no LLM call
5. ResponseLogger logs blocked attempt

**Output**: No response, alice must wait 30 more seconds

### Example 4: Admin User Reduced Cooldown

**Scenario**: Admin user (rank=3) mentions bot

**Config:** user_cooldown_seconds=60, admin_cooldown_multiplier=0.5

**Input:**
```json
{
  "username": "admin",
  "msg": "hey cynthia help",
  "time": 1640000000,
  "meta": {"rank": 3}
}
```

**Processing:**
1-2. Message filtered and mention detected
3. RateLimiter.check_rate_limit(username="admin", rank=3):
   - Detect admin: rank >= 3 → is_admin=True
   - Apply multiplier to user_cooldown: 60 * 0.5 = 30 seconds
   - Check user cooldown with 30s instead of 60s
   - If last response was 35s ago: 35 > 30 → ALLOWED
4-9. Continue normal flow

**Result**: Admin only waits 30 seconds between responses (half the normal cooldown)

### Example 5: Trigger Cooldown

**Scenario**: "toddy" trigger activated 4 minutes ago (cooldown=300s)

**Input**: Message contains "praise toddy"

**Processing:**
1-2. Message filtered, "toddy" pattern matches
3. RateLimiter.check_rate_limit():
   - Check global limits: Pass
   - Check user limits: Pass
   - Check trigger cooldown: Last "toddy" response 240s ago, cooldown 300s → BLOCKED
   - Return RateLimitDecision(allowed=False, reason="trigger cooldown active", retry_after=60, details={...})
4. Pipeline stops

**Output**: No response, trigger still cooling down (60 seconds remaining)

### Example 6: Multiple Trigger Matches - Priority Resolution

**Config:**
- Trigger A: patterns=["movie"], priority=5
- Trigger B: patterns=["kung fu"], priority=8

**Input**: "I love kung fu movies!"

**Processing:**
1. MessageListener: Valid → Pass
2. TriggerEngine:
   - Check mentions: No match
   - Check triggers (sorted by priority):
     - Trigger B (priority=8): "kung fu" matches → Check probability → triggered=True
     - Return immediately (don't check Trigger A)
   - Return TriggerResult with trigger_name="kung_fu" (Trigger B)

**Result**: Higher priority trigger wins, lower priority trigger ignored

### Example 7: Mention Takes Priority Over Trigger Word

**Input**: "hey cynthia, kung fu is awesome!"

**Config:**
- Mention: name_variations=["cynthia"], priority=10
- Trigger: patterns=["kung fu"], priority=8

**Processing:**
1. MessageListener: Valid → Pass
2. TriggerEngine:
   - Check mentions: "cynthia" found → Return TriggerResult(trigger_type="mention", trigger_name="cynthia", priority=10)
   - Skip trigger word checks (mention found)

**Result**: Mention wins, trigger word ignored

### Example 8: Probability=0 (Never Trigger)

**Config:**
```json
{
  "name": "disabled_trigger",
  "patterns": ["test"],
  "probability": 0.0,
  "enabled": true
}
```

**Input**: "test message"

**Processing:**
1-2. Pattern matches, but probability check: random.random() always >= 0.0
3. Return TriggerResult(triggered=False)

**Result**: Never triggers (effectively disabled via probability)

### Example 9: Response Logging - Complete Flow

**Input**: Successful response sent

**Log Entry:**
```json
{
  "timestamp": "2025-01-20T15:45:30.123456",
  "trigger_type": "trigger_word",
  "trigger_name": "toddy",
  "trigger_priority": 8,
  "username": "moviefan",
  "input_message": "praise toddy!",
  "cleaned_message": "praise!",
  "llm_response": "The divine energy flows through all of us!",
  "formatted_parts": ["The divine energy flows through all of us!"],
  "response_sent": true,
  "rate_limit": {
    "allowed": true,
    "reason": "allowed",
    "retry_after": 0,
    "details": {
      "global_count_minute": 1,
      "global_count_hour": 5,
      "user_count_hour": 2,
      "trigger_count_hour": 1,
      "global_cooldown_remaining": 0,
      "user_cooldown_remaining": 0,
      "trigger_cooldown_remaining": 0
    }
  }
}
```

### Example 10: Dry-Run Mode with Rate Limiting

**Config:** testing.dry_run=True

**Input**: Valid trigger message

**Processing:**
1-3. Filter, trigger, rate limit check (all pass)
4-6. Build prompts, generate response, format
7. Dry-run check: Log instead of send
8. **Skip record_response** (don't update rate limit state in dry-run)
9. Log to JSONL with response_sent=false

**Result**: Response logged but not sent, rate limit state NOT updated (can test repeatedly)

## 10. Validation Criteria

### Enhanced TriggerEngine Validation

- [ ] Loads triggers from config.triggers list
- [ ] Checks mentions before trigger words
- [ ] Matches trigger patterns (case-insensitive substring)
- [ ] Applies probability check correctly
- [ ] Resolves multiple matches by priority
- [ ] Returns trigger context in TriggerResult
- [ ] Cleans message by removing trigger phrase
- [ ] Skips disabled triggers (enabled=False)
- [ ] Handles edge cases (probability=0, probability=1)

### RateLimiter Validation

- [ ] Enforces global per-minute limit
- [ ] Enforces global per-hour limit
- [ ] Enforces global cooldown between responses
- [ ] Enforces per-user per-hour limit
- [ ] Enforces per-user cooldown
- [ ] Enforces mention cooldown
- [ ] Enforces per-trigger per-hour limit
- [ ] Enforces per-trigger cooldown
- [ ] Detects admin users (rank >= 3)
- [ ] Applies admin_cooldown_multiplier to cooldowns
- [ ] Applies admin_limit_multiplier to limits
- [ ] Returns detailed RateLimitDecision
- [ ] Cleans old timestamps from deques
- [ ] Updates state correctly after responses
- [ ] Handles edge cases (zero cooldowns, first response)

### ResponseLogger Validation

- [ ] Creates log directory if missing
- [ ] Appends entries to JSONL file
- [ ] Writes all required fields
- [ ] Handles file I/O errors gracefully
- [ ] Respects log_responses config flag
- [ ] Produces valid JSON (one object per line)
- [ ] Logs both sent and blocked responses

### Enhanced PromptBuilder Validation

- [ ] Includes trigger context when provided
- [ ] Formats context correctly in user prompt
- [ ] Handles None context gracefully
- [ ] Preserves Phase 1 behavior when context=None

### Integration Validation

- [ ] Rate limit checked before LLM call
- [ ] Rate limit blocks prevent LLM calls
- [ ] Rate limit state updated after responses
- [ ] Response logged to JSONL after sending
- [ ] Dry-run mode checks but doesn't update rate limits
- [ ] Admin users get privilege multipliers
- [ ] Trigger context included in prompts
- [ ] Multiple triggers resolved correctly
- [ ] All rate limit types enforced correctly

### Configuration Validation

- [ ] Triggers validated on load
- [ ] Probabilities validated (0.0-1.0)
- [ ] Cooldowns validated (non-negative)
- [ ] Priorities validated (1-10)
- [ ] Patterns validated (non-empty)
- [ ] Rate limits validated (non-negative)
- [ ] Config errors provide helpful messages

### Test Validation

- [ ] Enhanced trigger engine tests pass
- [ ] New rate limiter tests pass (all limit types)
- [ ] New response logger tests pass
- [ ] Enhanced prompt builder tests pass
- [ ] Enhanced integration tests pass
- [ ] Test coverage ≥75% overall
- [ ] Critical components ≥90% coverage
- [ ] Edge cases covered (probability, cooldowns, limits)

### Manual Testing

- [ ] Trigger words activate correctly
- [ ] Probabilities work as expected (~% match)
- [ ] Rate limits prevent spam
- [ ] Admin users get reduced cooldowns
- [ ] Response logs contain all events
- [ ] Dry-run mode works with rate limiting
- [ ] Multiple triggers resolved by priority
- [ ] Mentions take priority over trigger words

## 11. Related Specifications / Further Reading

### Internal Specifications

- [Phase 0 Corrected Specification](./spec-phase-0-corrected.md) - Foundation configuration
- [Phase 1 Specification](./spec-phase-1-message-processing.md) - Message listening and basic response
- [Implementation Plan](../docs/IMPLEMENTATION_PLAN.md) - Overall project roadmap
- [Configuration Models](../kryten_llm/models/config.py) - Trigger and RateLimits models
- [Event Models](../kryten_llm/models/events.py) - TriggerResult structure

### External Documentation

- [kryten-py Documentation](../kryten-py/README.md) - KrytenClient usage
- [Python deque](https://docs.python.org/3/library/collections.html#collections.deque) - Time-windowed rate limiting
- [Python random](https://docs.python.org/3/library/random.html) - Probability checks
- [JSONL Format](http://jsonlines.org/) - JSON Lines logging format

### Future Phase Specifications

- Phase 3 Specification (To Be Created) - Multi-provider LLM and context awareness
- Phase 4 Specification (To Be Created) - Intelligent formatting and validation
- Phase 5 Specification (To Be Created) - Service discovery and monitoring
- Phase 6 Specification (To Be Created) - Refinement and optimization

### Analysis Tools

**Log Analysis Script** (to be created in Phase 2):
```python
# scripts/analyze_responses.py
"""Analyze response logs for trigger effectiveness and rate limit behavior."""

def load_logs(log_file: str) -> list[dict]:
    """Load JSONL log file."""
    pass

def trigger_statistics(logs: list[dict]) -> dict:
    """Calculate trigger activation rates, success rates, probability accuracy."""
    pass

def rate_limit_statistics(logs: list[dict]) -> dict:
    """Calculate rate limit block rates, reasons, user patterns."""
    pass

def user_statistics(logs: list[dict]) -> dict:
    """Calculate per-user interaction counts, response times."""
    pass

# Usage:
# poetry run python scripts/analyze_responses.py --log logs/llm-responses.jsonl
```

---

**End of Specification**

This specification provides all necessary details for implementing Phase 2 of kryten-llm. It defines clear requirements, interfaces, acceptance criteria, and examples for trigger words, rate limiting, and response logging while maintaining extensibility for future phases.
