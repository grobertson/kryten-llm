---
title: Phase 4 - Intelligent Formatting & Validation
version: 1.0
date_created: 2025-12-11
last_updated: 2025-12-11
owner: kryten-llm development team
tags: [design, phase4, formatting, validation, quality, spam-detection]
---

# Introduction

This specification defines the requirements, constraints, and interfaces for Phase 4 of the kryten-llm implementation: Intelligent Formatting & Validation. This phase improves response quality and reliability through smart message formatting, response validation, spam detection, and enhanced error handling. The goal is to ensure bot responses are well-formatted, contextually appropriate, non-repetitive, and resilient to abuse.

## 1. Purpose & Scope

### Purpose
Enable the kryten-llm bot to:
1. Split long responses intelligently on sentence boundaries rather than mid-word
2. Add proper continuation indicators when messages must be split
3. Remove self-referential phrases and common LLM artifacts
4. Validate response relevance and quality before sending
5. Detect and prevent spam behavior from users
6. Handle errors gracefully with comprehensive logging and optional fallback responses

### Scope
This specification covers:
- Enhanced ResponseFormatter with intelligent splitting and artifact removal
- ResponseValidator for quality and relevance checking
- SpamDetector for user behavior analysis and rate limiting
- Enhanced error handling with graceful degradation
- Configuration schema for formatting rules, validation thresholds, and spam detection parameters
- Integration with existing Phase 1-3 components

### Assumptions
- Phase 1 (Basic Response), Phase 2 (Triggers & Rate Limiting), and Phase 3 (Multi-Provider & Context) are complete
- NATS connection is established and reliable
- Rate limiting from Phase 2 is operational
- Context management from Phase 3 is available
- CyTube enforces maximum message length of 255 characters per message

### Out of Scope
- Machine learning-based content moderation (future enhancement)
- User preference learning (future enhancement)
- Response quality feedback loops (future enhancement)
- Advanced sentiment analysis (future enhancement)

### Intended Audience
- Developers implementing Phase 4 features
- System architects reviewing design decisions
- QA engineers writing test plans
- Operations teams monitoring bot behavior

## 2. Definitions

| Term | Definition |
|------|------------|
| **Sentence Boundary** | End of a complete sentence, typically marked by `.`, `!`, or `?` followed by space or end of string |
| **Continuation Indicator** | Symbol or text showing a message continues in next message (e.g., `...`) |
| **Self-Referential Phrase** | Text where the bot refers to itself in third person or explains its role (e.g., "As Cynthia Rothbot, I...") |
| **LLM Artifact** | Common patterns in LLM output that should be removed (e.g., "Here's my response:", "I'll help you with that") |
| **Response Validation** | Process of checking if a response meets quality criteria before sending |
| **Relevance Check** | Verification that response relates to the input message and current context |
| **Repetition Detection** | Identifying when a response is identical or highly similar to recent responses |
| **Spam Pattern** | Repeated user behavior indicating attempt to abuse or flood the bot |
| **Exponential Backoff** | Increasing delay applied to repeat offenders (doubles on each spam violation) |
| **Graceful Degradation** | Ability to continue operating with reduced functionality when errors occur |
| **Fallback Response** | Pre-configured response used when LLM generation fails |

## 3. Requirements, Constraints & Guidelines

### Enhanced Response Formatter Requirements

**REQ-001**: ResponseFormatter MUST split messages at sentence boundaries
- Detect sentence endings: period, exclamation, question mark followed by space or end of text
- Never split mid-word or mid-sentence
- Respect maximum message length (255 characters)

**REQ-002**: ResponseFormatter MUST add continuation indicators for multi-part messages
- Append ` ...` to messages that continue (except the last part)
- Ensure continuation indicator fits within the 255 character limit
- Strip existing ellipsis from LLM before adding standardized continuation

**REQ-003**: ResponseFormatter MUST remove self-referential phrases
- Pattern: `^(As |I am |I'm )?{bot_name}[,:]?\s*` at start of message
- Pattern: `\b(speaking as|in the role of|playing)\s+{bot_name}\b` anywhere in message
- Case-insensitive matching
- Bot name from personality configuration

**REQ-004**: ResponseFormatter MUST remove common LLM artifacts
- Introductory phrases: "Here's", "I'll help", "Let me", "Sure!", "Certainly"
- Meta-commentary: "I think", "In my opinion", "As an AI"
- Hedging language: "I believe", "Perhaps", "Possibly" at sentence start
- Configurable list of patterns to remove

**REQ-005**: ResponseFormatter MUST handle emoji consistently
- Optional emoji limiting (configurable max per message, default: no limit)
- Preserve intentional emoji usage from LLM
- Count emoji correctly (some are multi-codepoint)

**REQ-006**: ResponseFormatter MUST normalize whitespace
- Remove leading/trailing whitespace from each message part
- Replace multiple spaces with single space
- Remove empty lines
- Preserve single line breaks where intentional

**REQ-007**: ResponseFormatter MUST remove code blocks from responses
- Detect triple-backtick code blocks (```language...```)
- Remove entire code block including backticks and content
- Code blocks are not suitable for chat display
- Preserve text before and after code blocks

**REQ-008**: ResponseFormatter output MUST be a list of strings
- Each string ≤ 255 characters (after continuation indicators)
- Strings are complete sentences or code blocks where possible
- Empty responses result in empty list (handled by caller)

### Response Validator Requirements

**REQ-009**: ResponseValidator MUST check minimum response length
- Minimum: 10 characters (configurable)
- Reject responses that are too short (likely errors or incomplete)

**REQ-010**: ResponseValidator MUST check maximum response length
- Maximum: 2000 characters before splitting (configurable)
- Reject excessively long responses (likely hallucination or error)

**REQ-011**: ResponseValidator MUST detect repetitive responses
- Track last N responses per bot instance (default: 10)
- Calculate similarity score (exact match or Levenshtein distance)
- Reject if similarity > threshold (default: 0.9 for exact, 0.7 for fuzzy)
- Prevent bot from getting stuck in loops

**REQ-012**: ResponseValidator MUST detect inappropriate content patterns
- Configurable regex patterns for inappropriate content
- Check for profanity (if enabled in config)
- Check for personal information leakage (emails, phone numbers, addresses)
- Configurable whitelist for allowed "inappropriate" words in personality

**REQ-013**: ResponseValidator MUST validate relevance to input (optional)
- Check if response contains keywords from user message
- Check if response mentions current video context (if video playing)
- Configurable relevance threshold
- Can be disabled for creative/random triggers

**REQ-014**: ResponseValidator MUST provide detailed rejection reasons
- Return ValidationResult with: valid (bool), reason (str), severity (enum)
- Severity: INFO, WARNING, ERROR
- Reasons logged for analysis and tuning

**REQ-015**: ResponseValidator MUST respect personality configuration
- Some personalities may allow more aggressive language
- Validation rules adjustable per personality
- Override defaults via personality config section

### Spam Detection Requirements

**REQ-016**: SpamDetector MUST track message frequency per user
- Track messages per user per time window (1 minute, 5 minutes, 15 minutes)
- Use sliding window algorithm (deque with timestamps)
- Configurable thresholds (default: 5 in 1min, 10 in 5min, 20 in 15min)

**REQ-017**: SpamDetector MUST detect identical message repetition
- Track last N messages per user (default: 20)
- Detect exact duplicates
- Threshold: 3+ identical messages in short time = spam
- Applies exponential backoff

**REQ-018**: SpamDetector MUST detect rapid bot mention spam
- Track bot mentions specifically (separate from general message count)
- Threshold: 3+ mentions within 30 seconds = spam
- Exponential cooldown: 30s → 60s → 120s → 300s
- Max cooldown: 10 minutes

**REQ-019**: SpamDetector MUST implement exponential backoff for repeat offenders
- Initial penalty: 30 seconds
- Multiplier: 2.0 on each violation within cooldown period
- Max penalty: 10 minutes (configurable)
- Decay: Reset to base penalty after clean period (10 minutes default)

**REQ-020**: SpamDetector MUST respect admin exemptions
- Admin users (rank ≥ configured threshold) exempt from spam detection
- Configurable admin ranks exempt list
- Moderators can override spam status

**REQ-021**: SpamDetector MUST provide clear feedback in logs
- Log spam detection events with reason and penalty duration
- Include user rank, message count, and detection window
- Severity: WARNING for first offense, ERROR for repeated

**REQ-022**: SpamDetector state MUST be in-memory only
- Use deques and dicts for tracking (same as Phase 2 rate limiter)
- Reset on service restart
- Do not persist user penalties to disk (privacy)

### Enhanced Error Handling Requirements

**REQ-023**: LLMService MUST handle all LLM provider failures gracefully
- Catch all exceptions from LLMManager
- Log full error context (provider, model, error message, stack trace)
- Optionally send fallback response or log dry-run message

**REQ-024**: LLMService MUST handle validation failures gracefully
- Log validation rejection with reason
- Do not send response to chat
- Optionally retry with modified prompt (future enhancement)

**REQ-025**: LLMService MUST handle formatting errors gracefully
- If ResponseFormatter raises exception, log error and send raw response
- Or skip sending and log failure
- Never crash on formatting error

**REQ-026**: Error logging MUST include correlation IDs
- Generate unique ID for each message processing attempt
- Include in all log messages for that attempt
- Format: `[msg-{uuid}]` or similar

**REQ-027**: Error logging MUST include full context
- User message, username, trigger type
- Current video (if any)
- Provider attempted, model used
- Response generated (if any)
- Validation/formatting errors

**REQ-028**: Service MUST implement fallback response system (optional)
- Configurable list of fallback messages for different error types
- Example: "I'm having trouble responding right now. Try again later!"
- Personality-appropriate fallback messages
- Can be disabled (default behavior: silent failure)

### Configuration Schema Requirements

**REQ-029**: Configuration MUST include formatting options
```json
{
  "formatting": {
    "max_message_length": 255,
    "continuation_indicator": " ...",
    "enable_emoji_limiting": false,
    "max_emoji_per_message": null,
    "remove_self_references": true,
    "remove_llm_artifacts": true,
    "artifact_patterns": [
      "^Here's ",
      "^Let me ",
      "^Sure!\\s*",
      "\\bAs an AI\\b",
      "\\bI think\\b",
      "\\bIn my opinion\\b"
    ]
  }
}
```

**REQ-030**: Configuration MUST include validation options
```json
{
  "validation": {
    "min_length": 10,
    "max_length": 2000,
    "check_repetition": true,
    "repetition_history_size": 10,
    "repetition_threshold": 0.9,
    "check_relevance": false,
    "relevance_threshold": 0.5,
    "inappropriate_patterns": [],
    "check_inappropriate": false
  }
}
```

**REQ-031**: Configuration MUST include spam detection options
```json
{
  "spam_detection": {
    "enabled": true,
    "message_windows": [
      {"seconds": 60, "max_messages": 5},
      {"seconds": 300, "max_messages": 10},
      {"seconds": 900, "max_messages": 20}
    ],
    "identical_message_threshold": 3,
    "mention_spam_threshold": 3,
    "mention_spam_window": 30,
    "initial_penalty": 30,
    "penalty_multiplier": 2.0,
    "max_penalty": 600,
    "clean_period": 600,
    "admin_exempt_ranks": [3, 4, 5]
  }
}
```

**REQ-032**: Configuration MUST include error handling options
```json
{
  "error_handling": {
    "enable_fallback_responses": false,
    "fallback_messages": [
      "I'm having trouble thinking right now. Try again later!",
      "My circuits are a bit scrambled. Give me a moment!",
      "ERROR: Brain.exe has stopped responding."
    ],
    "log_full_context": true,
    "generate_correlation_ids": true
  }
}
```

### Constraint Requirements

**CON-001**: All formatting operations MUST complete in <100ms
- Splitting, artifact removal, validation should be fast
- Avoid expensive operations (heavy regex, API calls)

**CON-002**: Spam detection MUST NOT require external storage
- All state in memory (deques, dicts)
- Fast lookups (O(1) or O(log n))

**CON-003**: Validation MUST NOT make external API calls
- All checks are local operations
- Future: optional external content moderation API

**CON-004**: Error handling MUST NOT leak sensitive data
- API keys, tokens never in error messages
- Truncate long error messages
- Sanitize stack traces in production logs

### Guideline Requirements

**GUD-001**: Prefer conservative defaults for validation
- Start with loose constraints, tighten based on observed behavior
- Example: repetition threshold 0.9 (near-exact) rather than 0.7 (fuzzy)

**GUD-002**: Make all thresholds configurable
- Avoid hardcoding magic numbers
- Document expected ranges for each threshold
- Provide recommended values in config.example.json

**GUD-003**: Log all validation failures for analysis
- Helps tune thresholds and identify false positives
- Include full context for debugging

**GUD-004**: Prioritize user experience over perfect validation
- False negatives (bad response sent) better than false positives (good response blocked)
- Err on the side of allowing responses

**GUD-005**: Use personality configuration to customize behavior
- Some personalities more strict, others more lenient
- Formatting rules may vary (emoji usage, language style)

### Pattern Requirements

**PAT-001**: ResponseFormatter should follow pipeline pattern
1. Remove code blocks
2. Remove artifacts
3. Remove self-references
4. Normalize whitespace
5. Split on sentences
6. Add continuation indicators
7. Return list of strings

**PAT-002**: ResponseValidator should return structured results
```python
@dataclass
class ValidationResult:
    valid: bool
    reason: str
    severity: Literal["INFO", "WARNING", "ERROR"]
```

**PAT-003**: SpamDetector should return actionable information
```python
@dataclass
class SpamCheckResult:
    is_spam: bool
    reason: str
    penalty_until: Optional[datetime]
    offense_count: int
```

## 4. Interfaces & Data Contracts

### ResponseFormatter Interface

```python
class ResponseFormatter:
    """Formats LLM responses for CyTube chat."""
    
    def __init__(self, config: FormattingConfig, personality_config: PersonalityConfig):
        """Initialize formatter with configuration."""
        pass
    
    def format_response(self, raw_response: str) -> list[str]:
        """
        Format raw LLM response into list of chat messages.
        
        Args:
            raw_response: Raw text from LLM
            
        Returns:
            List of formatted message strings, each ≤255 chars
            Empty list if response is invalid/empty
            
        Raises:
            FormattingError: If critical formatting error occurs
        """
        pass
    
    def _remove_artifacts(self, text: str) -> str:
        """Remove common LLM artifacts and preambles."""
        pass
    
    def _remove_self_references(self, text: str) -> str:
        """Remove self-referential phrases."""
        pass
    
    def _normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace and line breaks."""
        pass
    
    def _split_on_sentences(self, text: str, max_length: int) -> list[str]:
        """Split text into chunks at sentence boundaries."""
        pass
    
    def _add_continuation_indicators(self, parts: list[str]) -> list[str]:
        """Add ... to all but last part."""
        pass
    
    def _limit_emoji(self, text: str, max_emoji: int) -> str:
        """Limit emoji count if enabled."""
        pass
    
    def _remove_code_blocks(self, text: str) -> str:
        """Remove triple-backtick code blocks."""
        pass
```

### ResponseValidator Interface

```python
@dataclass
class ValidationResult:
    valid: bool
    reason: str
    severity: Literal["INFO", "WARNING", "ERROR"]

class ResponseValidator:
    """Validates LLM responses before sending."""
    
    def __init__(self, config: ValidationConfig):
        """Initialize validator with configuration."""
        self._recent_responses: deque[str] = deque(maxlen=config.repetition_history_size)
    
    def validate(
        self, 
        response: str, 
        user_message: str, 
        context: dict[str, Any]
    ) -> ValidationResult:
        """
        Validate response against quality criteria.
        
        Args:
            response: Formatted response to validate
            user_message: Original user message
            context: Context dict from ContextManager
            
        Returns:
            ValidationResult with valid flag and reason
        """
        pass
    
    def _check_length(self, response: str) -> ValidationResult:
        """Check if response length is acceptable."""
        pass
    
    def _check_repetition(self, response: str) -> ValidationResult:
        """Check if response is repetitive."""
        pass
    
    def _check_relevance(
        self, 
        response: str, 
        user_message: str, 
        context: dict
    ) -> ValidationResult:
        """Check if response is relevant to input."""
        pass
    
    def _check_inappropriate(self, response: str) -> ValidationResult:
        """Check for inappropriate content patterns."""
        pass
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity score between texts (0.0-1.0)."""
        pass
```

### SpamDetector Interface

```python
@dataclass
class SpamCheckResult:
    is_spam: bool
    reason: str
    penalty_until: Optional[datetime]
    offense_count: int

class SpamDetector:
    """Detects and prevents user spam behavior."""
    
    def __init__(self, config: SpamDetectionConfig):
        """Initialize spam detector with configuration."""
        self._user_messages: dict[str, deque[datetime]] = {}
        self._user_penalties: dict[str, datetime] = {}
        self._offense_counts: dict[str, int] = {}
        self._last_messages: dict[str, deque[str]] = {}
    
    def check_spam(
        self, 
        username: str, 
        message: str, 
        is_bot_mention: bool, 
        user_rank: int
    ) -> SpamCheckResult:
        """
        Check if user is spamming.
        
        Args:
            username: User sending message
            message: Message text
            is_bot_mention: Whether message mentions bot
            user_rank: User's rank (for admin exemption)
            
        Returns:
            SpamCheckResult indicating spam status and penalty
        """
        pass
    
    def record_message(self, username: str, message: str):
        """Record message for spam tracking."""
        pass
    
    def _check_rate_limits(self, username: str) -> Optional[str]:
        """Check if user exceeds rate limits."""
        pass
    
    def _check_identical_messages(self, username: str, message: str) -> bool:
        """Check for identical message repetition."""
        pass
    
    def _apply_penalty(self, username: str):
        """Apply exponential backoff penalty."""
        pass
    
    def _is_under_penalty(self, username: str) -> bool:
        """Check if user currently under penalty."""
        pass
    
    def _cleanup_old_data(self):
        """Clean up old tracking data (periodic)."""
        pass
```

### Enhanced LLMService Integration

```python
class LLMService:
    """Main service orchestrating all components."""
    
    def __init__(self, config: Config):
        self.formatter = ResponseFormatter(config.formatting, config.personality)
        self.validator = ResponseValidator(config.validation)
        self.spam_detector = SpamDetector(config.spam_detection)
        # ... existing components ...
    
    async def process_message(self, msg: dict):
        """Process incoming chat message (enhanced for Phase 4)."""
        username = msg["username"]
        message = msg["message"]
        user_rank = msg.get("rank", 0)
        correlation_id = self._generate_correlation_id()
        
        try:
            # Check trigger (Phase 2)
            trigger_result = self.trigger_engine.check_triggers(username, message)
            if not trigger_result.should_respond:
                return
            
            # Check spam BEFORE rate limiting
            spam_check = self.spam_detector.check_spam(
                username, 
                message, 
                is_bot_mention=trigger_result.is_direct_mention,
                user_rank=user_rank
            )
            
            if spam_check.is_spam:
                self._log_spam_detection(spam_check, correlation_id)
                return
            
            # Check rate limits (Phase 2)
            rate_check = self.rate_limiter.check_rate_limit(
                username, 
                trigger_result.trigger_name, 
                user_rank
            )
            if not rate_check.allowed:
                return
            
            # Get context (Phase 3)
            context = self.context_manager.get_context()
            
            # Build prompt (Phase 3)
            prompt = self.prompt_builder.build_user_prompt(
                message, 
                username, 
                trigger_result, 
                context
            )
            
            # Generate response (Phase 3)
            raw_response = await self.llm_manager.generate_response(
                prompt, 
                trigger_result.preferred_provider
            )
            
            # Validate response (Phase 4 NEW)
            validation = self.validator.validate(raw_response, message, context)
            if not validation.valid:
                self._log_validation_failure(validation, correlation_id)
                return
            
            # Format response (Phase 4 ENHANCED)
            formatted_messages = self.formatter.format_response(raw_response)
            if not formatted_messages:
                logger.warning(f"[{correlation_id}] Formatting produced empty response")
                return
            
            # Send response(s)
            for msg_part in formatted_messages:
                if self.dry_run:
                    logger.info(f"[DRY-RUN] Would send: {msg_part}")
                else:
                    await self.nats_client.publish(
                        f"kryten.commands.cytube.{self.channel}.chat",
                        json.dumps({"message": msg_part}).encode()
                    )
                    await asyncio.sleep(0.5)  # Delay between parts
            
            # Record response (Phase 2)
            self.rate_limiter.record_response(username, trigger_result.trigger_name)
            self.spam_detector.record_message(username, message)
            
            # Log response (Phase 2)
            self._log_response(
                trigger_result, 
                username, 
                message, 
                formatted_messages, 
                correlation_id
            )
            
        except Exception as e:
            self._handle_error(e, username, message, correlation_id)
    
    def _generate_correlation_id(self) -> str:
        """Generate unique correlation ID for request tracking."""
        return f"msg-{uuid.uuid4().hex[:12]}"
    
    def _handle_error(self, error: Exception, username: str, message: str, correlation_id: str):
        """Handle errors with comprehensive logging and optional fallback."""
        logger.error(
            f"[{correlation_id}] Error processing message from {username}: {message}",
            exc_info=True,
            extra={
                "username": username,
                "message": message,
                "error_type": type(error).__name__,
                "correlation_id": correlation_id
            }
        )
        
        # Optional: Send fallback response
        if self.config.error_handling.enable_fallback_responses:
            fallback = random.choice(self.config.error_handling.fallback_messages)
            # Send fallback...
```

### Configuration Data Classes

```python
@dataclass
class FormattingConfig:
    max_message_length: int = 255
    continuation_indicator: str = " ..."
    enable_emoji_limiting: bool = False
    max_emoji_per_message: Optional[int] = None
    remove_self_references: bool = True
    remove_llm_artifacts: bool = True
    artifact_patterns: list[str] = field(default_factory=list)

@dataclass
class ValidationConfig:
    min_length: int = 10
    max_length: int = 2000
    check_repetition: bool = True
    repetition_history_size: int = 10
    repetition_threshold: float = 0.9
    check_relevance: bool = False
    relevance_threshold: float = 0.5
    inappropriate_patterns: list[str] = field(default_factory=list)
    check_inappropriate: bool = False

@dataclass
class MessageWindow:
    seconds: int
    max_messages: int

@dataclass
class SpamDetectionConfig:
    enabled: bool = True
    message_windows: list[MessageWindow] = field(default_factory=list)
    identical_message_threshold: int = 3
    mention_spam_threshold: int = 3
    mention_spam_window: int = 30
    initial_penalty: int = 30
    penalty_multiplier: float = 2.0
    max_penalty: int = 600
    clean_period: int = 600
    admin_exempt_ranks: list[int] = field(default_factory=list)

@dataclass
class ErrorHandlingConfig:
    enable_fallback_responses: bool = False
    fallback_messages: list[str] = field(default_factory=list)
    log_full_context: bool = True
    generate_correlation_ids: bool = True
```

## 5. Acceptance Criteria

**AC-001**: Given a response longer than 255 characters, When ResponseFormatter formats it, Then it splits on sentence boundaries and adds continuation indicators
```python
# Test
response = "This is sentence one. This is sentence two. This is sentence three that is very long and exceeds the character limit."
formatted = formatter.format_response(response)
assert len(formatted) >= 2
assert all(len(msg) <= 255 for msg in formatted)
assert formatted[0].endswith(" ...")
assert "." in formatted[0]  # Contains complete sentence
```

**AC-002**: Given a response with self-referential phrases, When ResponseFormatter formats it, Then self-references are removed
```python
# Test
response = "As CynthiaRothbot, I think martial arts are awesome!"
formatted = formatter.format_response(response)
assert "CynthiaRothbot" not in formatted[0]
assert formatted[0].startswith("I think") or formatted[0].startswith("martial arts")
```

**AC-003**: Given a response with common LLM artifacts, When ResponseFormatter formats it, Then artifacts are removed
```python
# Test
response = "Here's my response: The answer is 42."
formatted = formatter.format_response(response)
assert not formatted[0].startswith("Here's")
assert formatted[0].startswith("The answer")
```

**AC-004**: Given a very short response, When ResponseValidator validates it, Then it is rejected with reason "too_short"
```python
# Test
result = validator.validate("Ok", "Tell me a story", {})
assert not result.valid
assert "too_short" in result.reason.lower() or "short" in result.reason.lower()
```

**AC-005**: Given a response identical to a recent response, When ResponseValidator validates it, Then it is rejected with reason "repetitive"
```python
# Test
validator.validate("The sky is blue.", "What color?", {})
result = validator.validate("The sky is blue.", "What color?", {})
assert not result.valid
assert "repetit" in result.reason.lower()
```

**AC-006**: Given a user sending 5 messages in 30 seconds, When SpamDetector checks spam, Then user is marked as spam with penalty
```python
# Test
for i in range(5):
    spam_detector.record_message("user1", f"message {i}")
result = spam_detector.check_spam("user1", "message 5", True, rank=0)
assert result.is_spam
assert result.penalty_until is not None
assert result.offense_count >= 1
```

**AC-007**: Given an admin user (rank ≥ 3), When SpamDetector checks spam, Then admin is exempt regardless of message frequency
```python
# Test
for i in range(10):
    spam_detector.record_message("admin", f"message {i}")
result = spam_detector.check_spam("admin", "message 10", True, rank=3)
assert not result.is_spam
```

**AC-008**: Given an LLM error, When LLMService handles error, Then error is logged with correlation ID and full context
```python
# Test (check logs)
# Error log should contain:
# - correlation_id
# - username
# - message
# - error_type
# - stack trace (if log_full_context=True)
```

**AC-009**: Given fallback responses enabled, When all LLM providers fail, Then a fallback response is sent
```python
# Test
config.error_handling.enable_fallback_responses = True
# Mock all providers to fail
# Process message
# Check that one of fallback_messages was sent
```

**AC-010**: Given a response with code blocks, When ResponseFormatter formats it, Then code blocks are completely removed
```python
# Test
response = "Here's the code:\n```python\ndef hello():\n    print('hello')\n```\nThat's how you do it!"
formatted = formatter.format_response(response)
assert len(formatted) >= 1
assert "```" not in formatted[0]
assert "python" not in formatted[0] or "That's how you do it" in formatted[0]
assert "Here's the code" in formatted[0] or len(formatted[0]) > 0
```

## 6. Test Automation Strategy

### Test Levels

**Unit Tests**:
- ResponseFormatter: Each formatting function independently
- ResponseValidator: Each validation check independently
- SpamDetector: Rate limiting, penalty calculation, admin exemption

**Integration Tests**:
- Full message processing pipeline with formatting + validation + spam detection
- Error handling with mocked LLM failures
- Multi-part message sending with delays

**Performance Tests**:
- Format 1000 responses <100ms total (10ms per response)
- Validate 1000 responses <50ms total (5ms per response)
- Spam check 10000 operations <100ms total (10μs per check)

### Test Frameworks

- **pytest**: Main test framework
- **pytest-asyncio**: For async tests
- **pytest-mock**: For mocking components
- **Moq/unittest.mock**: For mocking NATS, LLM calls

### Test Data Management

- **Fixtures**: Create test configurations with various thresholds
- **Parametrized tests**: Test multiple input/output scenarios
- **Test data files**: Sample responses, spam patterns, validation cases

### CI/CD Integration

- Run tests on every commit (GitHub Actions)
- Enforce test coverage >80% for Phase 4 code
- Fail build on any test failure
- Generate coverage reports

### Coverage Requirements

- Minimum 80% line coverage for Phase 4 components
- 100% coverage for critical paths (error handling, spam detection)
- Edge case coverage: empty responses, very long responses, special characters

## 7. Rationale & Context

### Why Sentence-Boundary Splitting?

**Problem**: Splitting messages mid-word or mid-sentence creates poor user experience and readability issues.

**Solution**: Detect sentence boundaries (`.`, `!`, `?`) and split at those points. If a sentence exceeds the limit, split at last sentence boundary before the limit.

**Alternatives Considered**:
- Word boundary splitting: Better than mid-word but still breaks thought flow
- Fixed-length chunks: Simple but poor UX
- No splitting: Can't send long responses

**Decision**: Sentence boundary with fallback to word boundary if sentence too long.

### Why Self-Reference Removal?

**Problem**: LLMs often generate responses like "As CynthiaRothbot, I believe..." which breaks immersion and sounds unnatural.

**Solution**: Strip these patterns at formatting time. The bot speaks *as* the character, not *about* the character.

**Implementation**: Regex patterns matching common self-referential phrases.

### Why Repetition Detection?

**Problem**: LLMs can get stuck generating the same response repeatedly, especially if context doesn't change.

**Solution**: Track recent responses and reject if new response is too similar.

**Tradeoff**: May reject legitimate repeated responses to different questions. Threshold tuned to minimize false positives (0.9 = near-exact match required).

### Why Spam Detection Separate from Rate Limiting?

**Problem**: Phase 2 rate limiting prevents *excessive* bot responses. Phase 4 spam detection prevents *abusive* user behavior.

**Difference**:
- Rate limiting: "Bot shouldn't respond more than X times per minute"
- Spam detection: "User is flooding the bot with mentions or identical messages"

**Integration**: Spam check happens *before* rate limit check. Spammers get penalized, normal users get rate limited.

### Why In-Memory Only for Spam State?

**Problem**: Persisting spam penalties to disk raises privacy concerns and adds complexity.

**Solution**: Keep all tracking state in memory. Resets on service restart, which is acceptable (gives users a fresh start).

**Tradeoff**: Sophisticated spammers could restart the bot to clear penalties. Mitigated by admin monitoring and manual moderation.

### Why Optional Fallback Responses?

**Problem**: When all LLM providers fail, bot goes silent, which may confuse users.

**Solution**: Optionally send a pre-configured fallback message explaining the issue.

**Tradeoff**: Fallback messages aren't contextual and may seem robotic. Made optional (disabled by default) to allow silent failure.

### Why Correlation IDs?

**Problem**: When errors occur, hard to trace which log messages belong to the same request.

**Solution**: Generate a unique ID for each message processing attempt and include in all related logs.

**Benefit**: Simplifies debugging, log analysis, and error tracking.

## 8. Dependencies & External Integrations

### External Systems

**EXT-001**: NATS Messaging System
- Purpose: Receive chat messages, send formatted responses
- Integration type: Pub/Sub
- Reliability: Critical path

### Internal Dependencies

**INF-001**: Phase 1 Components (MessageListener, ResponseSender)
- Dependency: ResponseFormatter integrates into existing response path
- Version: Phase 1 complete

**INF-002**: Phase 2 Components (TriggerEngine, RateLimiter)
- Dependency: SpamDetector runs before RateLimiter
- Version: Phase 2 complete

**INF-003**: Phase 3 Components (ContextManager, LLMManager, PromptBuilder)
- Dependency: Validation uses context, formatting uses LLM output
- Version: Phase 3 complete

### Technology Platform Dependencies

**PLT-001**: Python 3.10+
- Requirement: Type hints, dataclasses, asyncio
- Constraint: Must use Python 3.10 or newer for match/case and other features

**PLT-002**: Regular Expression Engine (re module)
- Requirement: Pattern matching for artifacts, self-references, inappropriate content
- Performance: Compiled regex for hot paths

**PLT-003**: String Similarity Library (optional)
- Requirement: For fuzzy repetition detection (Levenshtein distance)
- Options: `python-Levenshtein`, `difflib` (stdlib), `rapidfuzz`
- Recommendation: Start with `difflib.SequenceMatcher` (no external dep), upgrade if needed

### Data Dependencies

**DAT-001**: Configuration File (config.json)
- Format: JSON with Phase 4 sections (formatting, validation, spam_detection, error_handling)
- Validation: Pydantic models enforce schema

**DAT-002**: Response Logs (JSONL from Phase 2)
- Purpose: Analysis of rejected responses, spam patterns
- Format: One JSON object per line, append-only

### Compliance Dependencies

**COM-001**: Privacy Compliance
- Requirement: Do not persist user messages or spam tracking beyond service runtime
- Impact: All spam state in-memory only, cleared on restart
- Justification: Avoids data retention issues

## 9. Examples & Edge Cases

### Example 1: Long Response Split on Sentence Boundary

**Input**:
```
"Martial arts training requires discipline and dedication. You must practice every day, rain or shine, to master the techniques. I've spent decades perfecting my skills and I still learn something new every day."
```

**Expected Output** (assuming 255 char limit):
```python
[
    "Martial arts training requires discipline and dedication. You must practice every day, rain or shine, to master the techniques. I've spent decades perfecting my skills and I still learn something new every day."
]
# If longer:
[
    "Martial arts training requires discipline and dedication. You must practice every day, rain or shine, to master the techniques. ...",
    "I've spent decades perfecting my skills and I still learn something new every day."
]
```

### Example 2: Self-Reference Removal

**Input**:
```
"As CynthiaRothbot, I must say that martial arts have shaped my entire life. I believe discipline is the key to success."
```

**After Artifact Removal**:
```
"I must say that martial arts have shaped my entire life. I believe discipline is the key to success."
```

### Example 3: LLM Artifact Removal

**Input**:
```
"Here's my response: Sure! Let me help you with that. I think the best martial arts movie is Enter the Dragon."
```

**After Artifact Removal**:
```
"The best martial arts movie is Enter the Dragon."
```

### Example 4: Repetition Detection

**Previous Response**: "The sky is blue because of Rayleigh scattering."

**Current Response**: "The sky is blue because of Rayleigh scattering."

**Validation Result**:
```python
ValidationResult(
    valid=False,
    reason="Response is identical to recent response (exact match)",
    severity="WARNING"
)
```

### Example 5: Spam Detection - Rapid Mentions

**User**: "user123"

**Messages** (within 30 seconds):
```
1. "@CynthiaRothbot hello"
2. "@CynthiaRothbot are you there?"
3. "@CynthiaRothbot please respond"
4. "@CynthiaRothbot hey"
```

**Spam Check Result** (after 4th message):
```python
SpamCheckResult(
    is_spam=True,
    reason="Exceeded mention spam threshold: 4 mentions in 30 seconds (limit: 3)",
    penalty_until=datetime(2025, 12, 11, 15, 30, 30),  # 30 seconds from now
    offense_count=1
)
```

### Example 6: Spam Detection - Exponential Backoff

**User**: "spammer"

**Violation 1**: 30 second penalty (until 15:00:30)

**Violation 2** (at 15:00:20, during penalty): 60 second penalty (until 15:01:20)

**Violation 3** (at 15:00:50, during penalty): 120 second penalty (until 15:02:50)

**Clean Period** (no violations for 10 minutes): Reset to 30 second base penalty

### Example 7: Admin Exemption

**User**: "admin_user" (rank=3)

**Messages**: 10 rapid mentions within 10 seconds

**Spam Check Result**:
```python
SpamCheckResult(
    is_spam=False,
    reason="User exempt from spam detection (admin rank 3)",
    penalty_until=None,
    offense_count=0
)
```

### Example 8: Code Block Removal

**Input**:
```
"Here's how to implement a kick in Python:\n```python\ndef roundhouse_kick(target):\n    target.health -= 50\n    print('BOOM!')\n```\nThis demonstrates the power of martial arts in code!"
```

**Expected Output**:
```python
[
    "Here's how to implement a kick in Python: This demonstrates the power of martial arts in code!"
]
# Code block completely removed, text before and after preserved
```

### Edge Case 1: Empty Response from LLM

**Input**: `""`

**Formatter Output**: `[]`

**Service Behavior**: Logs warning, does not send message, does not crash

### Edge Case 2: Response is Only Whitespace

**Input**: `"   \n\n   \t  "`

**After Normalization**: `""`

**Formatter Output**: `[]`

### Edge Case 3: Response with Only Artifacts

**Input**: `"Here's my response: Sure! Let me help you with that."`

**After Artifact Removal**: `""`

**Formatter Output**: `[]`

### Edge Case 4: Sentence Longer Than Max Length

**Input** (single sentence >255 chars):
```
"This is an extremely long sentence that just keeps going and going without any punctuation and exceeds the maximum character limit of 255 characters which means we need to split it at a word boundary even though there are no sentence boundaries available in this particular case."
```

**Expected Behavior**: Split at last word boundary before 255 chars, add `...`

### Edge Case 5: User with No Previous Messages

**Spam Check**: First message from user → No spam (no history to compare)

### Edge Case 6: All Validators Pass But Response is Empty After Formatting

**Scenario**: Response passes validation (length OK, not repetitive), but after artifact removal, nothing remains.

**Behavior**: Formatter returns `[]`, service logs warning, does not send.

### Edge Case 7: Response is Only Code Blocks

**Input**: "```python\nprint('hello')\n```"

**After Code Block Removal**: `""`

**Formatter Output**: `[]`

**Behavior**: Service logs warning, does not send message

## 10. Validation Criteria

### Functional Validation

**FUNC-001**: ResponseFormatter correctly splits all test responses at sentence boundaries
- Test with 50 sample long responses
- Verify: No mid-sentence splits, continuation indicators present

**FUNC-002**: ResponseFormatter removes all configured artifact patterns
- Test with 20 responses containing artifacts
- Verify: All matches removed, message still coherent

**FUNC-003**: ResponseValidator correctly identifies repetitive responses
- Test with 10 identical response pairs
- Verify: All flagged as repetitive with correct reason

**FUNC-004**: SpamDetector correctly applies exponential backoff
- Test with simulated spam violations
- Verify: Penalty doubles each time, max penalty respected

**FUNC-005**: SpamDetector exempts admin users
- Test with admin users (ranks 3, 4, 5) spamming
- Verify: No spam flags, no penalties

### Performance Validation

**PERF-001**: ResponseFormatter processes responses in <10ms each
- Test: Format 1000 responses, measure total time
- Pass if: Total time <10 seconds (10ms average)

**PERF-002**: ResponseValidator validates responses in <5ms each
- Test: Validate 1000 responses, measure total time
- Pass if: Total time <5 seconds (5ms average)

**PERF-003**: SpamDetector checks spam in <100μs per check
- Test: Perform 10000 spam checks, measure total time
- Pass if: Total time <1 second (100μs average)

### Integration Validation

**INT-001**: Full message processing pipeline completes successfully
- Test: Send message → trigger → rate limit → context → LLM → validate → format → send
- Verify: All phases complete, formatted response sent

**INT-002**: Error handling works with all LLM provider failures
- Test: Mock all providers to fail, process message
- Verify: Error logged with correlation ID, fallback sent (if enabled), no crash

**INT-003**: Spam detection integrates with existing rate limiting
- Test: Spam user → blocked by spam detector before rate limiter
- Verify: Spam penalty applied, rate limiter not invoked

### Edge Case Validation

**EDGE-001**: Empty response handling
- Input: Empty string, whitespace-only, artifacts-only
- Expected: Empty list from formatter, warning logged, no message sent

**EDGE-002**: Very long sentence (no boundaries within limit)
- Input: Single 500-char sentence
- Expected: Split at word boundary, continuation indicator added

**EDGE-003**: Response containing only code blocks
- Input: Response with only code blocks, no other text
- Expected: Code blocks removed, empty result, warning logged, no message sent

**EDGE-004**: User sends first message ever
- Expected: No spam flag (no history to compare)

**EDGE-005**: Multiple users spam simultaneously
- Expected: Each tracked independently, penalties applied separately

## 11. Related Specifications / Further Reading

### Related Specifications

- [Phase 1 - Message Processing Specification](spec-phase-1-message-processing.md)
- [Phase 2 - Triggers & Rate Limiting Specification](spec-phase-2-triggers-and-rate-limiting.md)
- [Phase 3 - Multi-Provider & Context Management Specification](spec-design-phase3-multi-provider-context.md)
- [Phase 5 - Service Discovery & Monitoring Specification](spec-design-phase5-service-discovery.md) (future)

### External Documentation

- [CyTube Chat Message Limits](https://github.com/calzoneman/sync/wiki/CyTube-API)
- [NATS Pub/Sub Documentation](https://docs.nats.io/nats-concepts/core-nats/pubsub)
- [Python Regex Documentation](https://docs.python.org/3/library/re.html)
- [Levenshtein Distance (Wikipedia)](https://en.wikipedia.org/wiki/Levenshtein_distance)
- [Exponential Backoff Pattern](https://en.wikipedia.org/wiki/Exponential_backoff)

### Best Practices

- [Python Logging Best Practices](https://docs.python.org/3/howto/logging.html)
- [Error Handling in Async Python](https://docs.python.org/3/library/asyncio-exceptions.html)
- [Text Processing Performance Optimization](https://wiki.python.org/moin/PythonSpeed/PerformanceTips)

---

**Document Status**: Ready for implementation

**Next Steps**:
1. Review specification with team
2. Create implementation tasks (10 tasks mirroring Phase 3 approach)
3. Begin implementation of ResponseFormatter
4. Create unit tests for each component
5. Create integration tests for full pipeline
6. Update config.example.json with Phase 4 sections
7. Deploy to test environment
8. Monitor and tune thresholds based on real behavior

**Questions/Clarifications**:
- Should emoji limiting be enabled by default? (Recommendation: No, personality-dependent)
- Should fallback responses be enabled by default? (Recommendation: No, prefer silent failure)
- Should relevance checking be enabled by default? (Recommendation: No, optional feature)
- What should be the default spam detection thresholds? (Use conservative values from REQ-031)
