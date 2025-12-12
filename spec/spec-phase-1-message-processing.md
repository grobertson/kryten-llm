---
title: Phase 1 - Message Listening & Basic Response
version: 1.0
date_created: 2025-01-20
last_updated: 2025-01-20
owner: kryten-llm
tags: [phase-1, architecture, design, messaging, llm]
---

# Introduction

This specification defines Phase 1 of the kryten-llm implementation: Message Listening & Basic Response. The goal is to create a functional bot that listens to CyTube chat messages and responds to direct mentions using LLM-generated responses.

Phase 1 builds on Phase 0's configuration infrastructure and establishes the core message processing pipeline. The implementation should be simple, focusing on a working end-to-end flow rather than advanced features.

## 1. Purpose & Scope

### Purpose

Implement the core message processing pipeline for kryten-llm, enabling the bot to:
- Listen to CyTube chat messages via NATS
- Detect when users mention the bot's name
- Generate LLM responses using configured personality
- Send formatted responses back to chat
- Support dry-run mode for testing

### Scope

**In Scope:**
- MessageListener component for filtering chat messages
- TriggerEngine component for mention detection
- LLMManager component for single-provider LLM calls
- PromptBuilder component for basic prompt construction
- ResponseFormatter component for basic formatting
- Integration of all components in LLMService
- Dry-run mode testing
- Basic error handling

**Out of Scope (Future Phases):**
- Trigger word patterns and probabilities (Phase 2)
- Rate limiting (Phase 2)
- Multi-provider support with fallback (Phase 3)
- Context awareness (video, chat history) (Phase 3)
- Intelligent message splitting (Phase 4)
- Response validation (Phase 4)
- Service discovery integration (Phase 5)

### Intended Audience

- AI agents implementing the system
- Developers reviewing/maintaining the code
- Future maintainers understanding the architecture

### Assumptions

- Phase 0 is complete (configuration models, KrytenClient integration, CLI)
- NATS server is running and accessible
- CyTube bot is publishing chatMsg events to NATS
- At least one LLM provider is configured and accessible
- Configuration includes personality settings with name variations

## 2. Definitions

- **chatMsg**: NATS event published when a CyTube user sends a chat message
- **Mention**: A chat message containing one of the bot's name variations
- **Trigger**: A pattern or condition that causes the bot to respond (Phase 1: mentions only)
- **TriggerResult**: Data class indicating if a message triggered a response
- **Dry-run mode**: Testing mode where responses are logged but not sent to chat
- **Message pipeline**: The sequence of components processing a message (listener → trigger → LLM → formatter → sender)
- **System prompt**: LLM prompt containing personality/character instructions
- **User prompt**: LLM prompt containing the user's actual message

## 3. Requirements, Constraints & Guidelines

### Requirements

#### Core Functionality

- **REQ-001**: MessageListener MUST filter out spam messages (messages starting with `!`, `/`, or `.`)
- **REQ-002**: MessageListener MUST filter out messages from ignored users (bots, system users)
- **REQ-003**: MessageListener MUST validate messages have required fields (username, msg, time)
- **REQ-004**: TriggerEngine MUST detect mentions by checking for any configured name variation (case-insensitive)
- **REQ-005**: TriggerEngine MUST clean the message by removing the bot's name before LLM processing
- **REQ-006**: TriggerEngine MUST return TriggerResult with triggered=True for mentions
- **REQ-007**: LLMManager MUST support OpenAI-compatible API endpoints
- **REQ-008**: LLMManager MUST use the default_provider from configuration
- **REQ-009**: LLMManager MUST apply provider timeout settings
- **REQ-010**: LLMManager MUST handle API errors gracefully (log and return None)
- **REQ-011**: PromptBuilder MUST construct system prompts from PersonalityConfig
- **REQ-012**: PromptBuilder MUST include character name, description, traits, and response style
- **REQ-013**: PromptBuilder MUST construct user prompts with username and cleaned message
- **REQ-014**: ResponseFormatter MUST limit response length to max_message_length (default 240)
- **REQ-015**: ResponseFormatter MUST split long responses into multiple messages
- **REQ-016**: ResponseFormatter MUST respect split_delay_seconds between parts (default 2s)
- **REQ-017**: ResponseFormatter MUST remove common LLM artifacts (self-references like "As [character name],")
- **REQ-018**: LLMService MUST integrate all components in the message processing pipeline
- **REQ-019**: LLMService MUST send responses to chat when testing.dry_run=False
- **REQ-020**: LLMService MUST log responses but NOT send when testing.dry_run=True
- **REQ-021**: All components MUST log important events (mentions detected, LLM calls, responses sent)

#### Error Handling

- **REQ-022**: LLM API failures MUST be logged with full context (provider, model, error)
- **REQ-023**: LLM API timeouts MUST be handled gracefully (no service crash)
- **REQ-024**: Invalid message formats MUST be logged and skipped (no processing)
- **REQ-025**: Missing configuration MUST be caught at service start (fail fast)

#### Testing

- **REQ-026**: Dry-run mode MUST be verifiable through log output
- **REQ-027**: All components MUST be testable independently (unit tests)
- **REQ-028**: Message processing pipeline MUST be testable end-to-end

### Constraints

- **CON-001**: Phase 1 MUST use only the default LLM provider (no fallback)
- **CON-002**: Phase 1 MUST NOT implement rate limiting (deferred to Phase 2)
- **CON-003**: Phase 1 MUST NOT include context awareness (deferred to Phase 3)
- **CON-004**: Phase 1 MUST NOT implement trigger word patterns (only mentions)
- **CON-005**: Phase 1 MUST NOT validate response quality (deferred to Phase 4)
- **CON-006**: Message length limit MUST NOT exceed 240 characters (CyTube constraint)
- **CON-007**: Components MUST use asyncio for all I/O operations
- **CON-008**: Components MUST NOT block the event loop

### Guidelines

- **GUD-001**: Log all LLM interactions with sufficient detail for debugging
- **GUD-002**: Use descriptive error messages that include context
- **GUD-003**: Keep components focused and single-purpose
- **GUD-004**: Use type hints for all function parameters and returns
- **GUD-005**: Document all public methods with docstrings
- **GUD-006**: Handle edge cases gracefully (empty messages, missing fields)
- **GUD-007**: Make components easily extensible for future phases
- **GUD-008**: Follow existing code style from Phase 0

### Patterns

- **PAT-001**: Use dataclasses for internal data structures (TriggerResult already exists)
- **PAT-002**: Use Pydantic models for configuration (inherited from Phase 0)
- **PAT-003**: Use dependency injection (pass config/dependencies to __init__)
- **PAT-004**: Use async/await throughout the pipeline
- **PAT-005**: Use explicit return types (Optional[str], TriggerResult, etc.)
- **PAT-006**: Use early returns to avoid deep nesting
- **PAT-007**: Log before and after significant operations

## 4. Interfaces & Data Contracts

### MessageListener Interface

```python
class MessageListener:
    """Filters and validates incoming chat messages."""
    
    def __init__(self, config: LLMConfig):
        """Initialize with configuration."""
        pass
    
    async def filter_message(self, data: dict) -> dict | None:
        """Filter and validate a chatMsg event.
        
        Args:
            data: Raw chatMsg event data from NATS
            
        Returns:
            Filtered message dict or None if message should be ignored
            
        Message dict structure:
            {
                "username": str,      # Username of sender
                "msg": str,          # Message text
                "time": int,         # Timestamp
                "meta": dict,        # Metadata (rank, etc.)
            }
        """
        pass
```

**Filtering Rules:**
- Ignore if `msg` starts with `!`, `/`, or `.` (commands)
- Ignore if `username` in `["[server]", "[bot]", "[system]"]` (system messages)
- Ignore if required fields missing (`username`, `msg`, `time`)
- Return None for filtered messages, dict for valid messages

### TriggerEngine Interface

```python
class TriggerEngine:
    """Detects trigger conditions in chat messages."""
    
    def __init__(self, config: LLMConfig):
        """Initialize with configuration.
        
        Phase 1: Only mention detection
        Phase 2: Add trigger word patterns
        """
        pass
    
    async def check_triggers(self, message: dict) -> TriggerResult:
        """Check if message triggers a response.
        
        Args:
            message: Filtered message dict from MessageListener
            
        Returns:
            TriggerResult indicating if triggered and details
        """
        pass
```

**TriggerResult Structure (from Phase 0):**
```python
@dataclass
class TriggerResult:
    triggered: bool           # True if should respond
    trigger_type: str         # "mention" (Phase 1 only)
    trigger_name: str | None  # Bot name variation matched
    cleaned_message: str      # Message with bot name removed
    context: str | None       # Additional context (None in Phase 1)
    priority: int             # Priority level (10 for mentions)
    
    def __bool__(self) -> bool:
        return self.triggered
```

**Mention Detection Logic:**
- Check if any `personality.name_variations` appears in `message["msg"]` (case-insensitive)
- If found: `TriggerResult(triggered=True, trigger_type="mention", trigger_name=<matched_name>, cleaned_message=<msg_without_name>, context=None, priority=10)`
- If not found: `TriggerResult(triggered=False, ...)`

### LLMManager Interface

```python
class LLMManager:
    """Manages LLM API interactions."""
    
    def __init__(self, config: LLMConfig):
        """Initialize with configuration.
        
        Phase 1: Single provider support
        Phase 3: Multi-provider with fallback
        """
        pass
    
    async def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        provider_name: str | None = None
    ) -> str | None:
        """Generate LLM response.
        
        Args:
            system_prompt: System/personality prompt
            user_prompt: User message prompt
            provider_name: Provider to use (None = default)
            
        Returns:
            Generated response text or None on error
        """
        pass
```

**LLM API Request Format (OpenAI-compatible):**
```python
# POST to {provider.base_url}/chat/completions
{
    "model": provider.model,
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ],
    "max_tokens": provider.max_tokens,
    "temperature": provider.temperature
}

# Headers
{
    "Authorization": f"Bearer {provider.api_key}",
    "Content-Type": "application/json"
}
```

**LLM API Response Format:**
```python
{
    "choices": [
        {
            "message": {
                "content": "Generated response text"
            }
        }
    ]
}
```

### PromptBuilder Interface

```python
class PromptBuilder:
    """Constructs prompts for LLM generation."""
    
    def __init__(self, config: LLMConfig):
        """Initialize with configuration."""
        pass
    
    def build_system_prompt(self) -> str:
        """Build system prompt from personality configuration.
        
        Returns:
            System prompt text
        """
        pass
    
    def build_user_prompt(self, username: str, message: str) -> str:
        """Build user prompt from message.
        
        Args:
            username: Username of message sender
            message: Cleaned message text
            
        Returns:
            User prompt text
        """
        pass
```

**System Prompt Template:**
```
You are {character_name}, {character_description}.

Personality traits: {comma_separated_traits}
Areas of expertise: {comma_separated_expertise}

Response style: {response_style}

Important rules:
- Keep responses under 240 characters
- Stay in character
- Be natural and conversational
- Do not use markdown formatting
- Do not start responses with your character name
```

**User Prompt Template:**
```
{username} says: {message}
```

### ResponseFormatter Interface

```python
class ResponseFormatter:
    """Formats LLM responses for chat output."""
    
    def __init__(self, config: LLMConfig):
        """Initialize with configuration."""
        pass
    
    async def format_response(self, response: str) -> list[str]:
        """Format LLM response for chat.
        
        Args:
            response: Raw LLM response text
            
        Returns:
            List of formatted message parts (split if needed)
        """
        pass
```

**Formatting Rules:**
1. Remove leading/trailing whitespace
2. Remove self-references: `"As {character_name}, "` → `""`
3. If length ≤ max_message_length: return `[response]`
4. If length > max_message_length: split into parts
   - Split at `max_message_length` boundary
   - Add `"..."` to end of non-final parts
   - Add `"..."` to start of non-first parts
   - Return list of parts

**Example:**
```python
# Input (280 chars, max_length=240):
"The path of the warrior is not about seeking glory or recognition. It's about discipline, dedication, and the pursuit of excellence in every movement. True mastery comes from within, through countless hours of practice and self-reflection."

# Output:
[
    "The path of the warrior is not about seeking glory or recognition. It's about discipline, dedication, and the pursuit of excellence in every movement. True mastery comes from within, through countless hours of...",
    "...practice and self-reflection."
]
```

### LLMService Integration

```python
async def _handle_chat_message(self, subject: str, data: dict) -> None:
    """Handle chatMsg events (replaces Phase 0 placeholder).
    
    Processing pipeline:
    1. Filter message (MessageListener)
    2. Check triggers (TriggerEngine)
    3. Build prompts (PromptBuilder)
    4. Generate response (LLMManager)
    5. Format response (ResponseFormatter)
    6. Send to chat or log (based on dry_run)
    """
    # 1. Filter message
    filtered = await self.listener.filter_message(data)
    if not filtered:
        return
    
    # 2. Check triggers
    trigger_result = await self.trigger_engine.check_triggers(filtered)
    if not trigger_result:
        return
    
    logger.info(f"Triggered by {trigger_result.trigger_type}: {filtered['username']}")
    
    # 3. Build prompts
    system_prompt = self.prompt_builder.build_system_prompt()
    user_prompt = self.prompt_builder.build_user_prompt(
        filtered["username"],
        trigger_result.cleaned_message
    )
    
    # 4. Generate response
    llm_response = await self.llm_manager.generate_response(
        system_prompt,
        user_prompt
    )
    
    if not llm_response:
        logger.error("LLM failed to generate response")
        return
    
    # 5. Format response
    formatted_parts = await self.response_formatter.format_response(llm_response)
    
    # 6. Send to chat or log
    for i, part in enumerate(formatted_parts):
        if self.config.testing.dry_run:
            logger.info(f"[DRY RUN] Would send: {part}")
        else:
            await self.client.send_chat_message(part)
            logger.info(f"Sent response part {i+1}/{len(formatted_parts)}")
        
        # Delay between parts
        if i < len(formatted_parts) - 1:
            await asyncio.sleep(self.config.message_processing.split_delay_seconds)
```

## 5. Acceptance Criteria

### Component Creation

- **AC-001**: Given Phase 0 is complete, When I create `kryten_llm/components/listener.py`, Then it contains MessageListener class with filter_message method
- **AC-002**: Given Phase 0 is complete, When I create `kryten_llm/components/trigger_engine.py`, Then it contains TriggerEngine class with check_triggers method
- **AC-003**: Given Phase 0 is complete, When I create `kryten_llm/components/llm_manager.py`, Then it contains LLMManager class with generate_response method
- **AC-004**: Given Phase 0 is complete, When I create `kryten_llm/components/prompt_builder.py`, Then it contains PromptBuilder class with build_system_prompt and build_user_prompt methods
- **AC-005**: Given Phase 0 is complete, When I create `kryten_llm/components/formatter.py`, Then it contains ResponseFormatter class with format_response method
- **AC-006**: Given all components are created, When I import them in `kryten_llm/components/__init__.py`, Then all imports work without errors

### Functionality

- **AC-007**: Given MessageListener is initialized, When I pass a spam message (starting with `!`), Then filter_message returns None
- **AC-008**: Given MessageListener is initialized, When I pass a valid message, Then filter_message returns the message dict
- **AC-009**: Given TriggerEngine is initialized, When I pass a message with bot name mention, Then check_triggers returns TriggerResult with triggered=True
- **AC-010**: Given TriggerEngine is initialized, When I pass a message without bot name, Then check_triggers returns TriggerResult with triggered=False
- **AC-011**: Given TriggerEngine detects mention, When message is "hey cynthia what's up?", Then cleaned_message is "what's up?" (name removed)
- **AC-012**: Given LLMManager is initialized, When I call generate_response with valid prompts, Then it returns a non-empty string
- **AC-013**: Given LLM API is unavailable, When I call generate_response, Then it returns None and logs error
- **AC-014**: Given PromptBuilder is initialized, When I call build_system_prompt, Then it includes character_name, personality_traits, and response_style
- **AC-015**: Given PromptBuilder is initialized, When I call build_user_prompt("john", "hello"), Then it returns "john says: hello"
- **AC-016**: Given ResponseFormatter is initialized, When I format a short response (≤240 chars), Then it returns a list with one item
- **AC-017**: Given ResponseFormatter is initialized, When I format a long response (>240 chars), Then it returns a list with multiple items
- **AC-018**: Given ResponseFormatter processes response, When response starts with "As Cynthia, ", Then formatted response has prefix removed

### Integration

- **AC-019**: Given all components are initialized in LLMService, When service starts, Then all components are ready
- **AC-020**: Given service is running with dry_run=True, When user mentions bot in chat, Then response is logged but NOT sent
- **AC-021**: Given service is running with dry_run=False, When user mentions bot in chat, Then response is sent to chat
- **AC-022**: Given service is running, When LLM generates long response, Then multiple messages are sent with delay between them
- **AC-023**: Given service is running, When LLM API fails, Then error is logged and no response is sent (no crash)

### Testing

- **AC-024**: Given test suite exists, When I run `pytest tests/test_listener.py`, Then all MessageListener tests pass
- **AC-025**: Given test suite exists, When I run `pytest tests/test_trigger_engine.py`, Then all TriggerEngine tests pass
- **AC-026**: Given test suite exists, When I run `pytest tests/test_llm_manager.py`, Then all LLMManager tests pass (with mocked API)
- **AC-027**: Given test suite exists, When I run `pytest tests/test_prompt_builder.py`, Then all PromptBuilder tests pass
- **AC-028**: Given test suite exists, When I run `pytest tests/test_formatter.py`, Then all ResponseFormatter tests pass
- **AC-029**: Given service is running in test environment, When I send test mention, Then end-to-end flow completes successfully

## 6. Test Automation Strategy

### Test Levels

**Unit Tests** (Priority: High)
- Test each component in isolation
- Mock external dependencies (LLM API, NATS)
- Focus on business logic and edge cases

**Integration Tests** (Priority: Medium)
- Test component interactions
- Test message pipeline flow
- Use test configuration

**End-to-End Tests** (Priority: Low for Phase 1, High for Phase 6)
- Manual testing in CyTube channel
- Automated E2E tests deferred to Phase 6

### Test Frameworks

- **Unit Testing**: pytest
- **Async Testing**: pytest-asyncio
- **Mocking**: pytest-mock, unittest.mock
- **Assertions**: Standard assertions, pytest raises

### Test Organization

```
tests/
├── conftest.py                 # Shared fixtures (from Phase 0)
├── test_config.py             # Config tests (from Phase 0)
├── test_listener.py           # MessageListener tests
├── test_trigger_engine.py     # TriggerEngine tests
├── test_llm_manager.py        # LLMManager tests (mocked API)
├── test_prompt_builder.py     # PromptBuilder tests
├── test_formatter.py          # ResponseFormatter tests
└── test_service_integration.py # Integration tests
```

### Test Data Management

**Fixtures** (in conftest.py):
```python
@pytest.fixture
def sample_chat_message():
    """Valid chat message for testing."""
    return {
        "username": "testuser",
        "msg": "hey cynthia, how are you?",
        "time": 1640000000,
        "meta": {"rank": 1}
    }

@pytest.fixture
def spam_message():
    """Spam message for filtering tests."""
    return {
        "username": "testuser",
        "msg": "!skip",
        "time": 1640000000,
        "meta": {"rank": 1}
    }

@pytest.fixture
def llm_manager_mock(mocker):
    """Mocked LLM API response."""
    mock_response = mocker.MagicMock()
    mock_response.status = 200
    mock_response.json = mocker.AsyncMock(return_value={
        "choices": [{"message": {"content": "Great to hear from you!"}}]
    })
    return mock_response
```

### Coverage Requirements

- **Minimum Coverage**: 70% overall
- **Critical Components**: 90% coverage
  - MessageListener (filtering logic)
  - TriggerEngine (mention detection)
  - ResponseFormatter (splitting logic)
- **Integration Tests**: At least 5 end-to-end scenarios

### CI/CD Integration

**GitHub Actions Pipeline** (deferred to Phase 6, but designed now):
```yaml
name: Test Phase 1

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
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

## 7. Rationale & Context

### Design Decisions

**Decision 1: Separate Components vs. Monolithic Handler**
- **Rationale**: Separate components (MessageListener, TriggerEngine, etc.) provide better testability, maintainability, and extensibility. Each component has a single responsibility and can be tested in isolation.
- **Alternative**: Implement all logic in `_handle_chat_message` method
- **Trade-off**: More files and initial complexity, but much easier to extend in future phases

**Decision 2: Synchronous Prompt Building vs. Async**
- **Rationale**: PromptBuilder operations are pure string manipulation with no I/O. Making them sync keeps the code simpler and more intuitive.
- **Alternative**: Make all methods async for consistency
- **Trade-off**: Slight inconsistency in API, but better performance (no unnecessary async overhead)

**Decision 3: Basic String Splitting vs. Sentence Boundary Detection**
- **Rationale**: Phase 1 focuses on working end-to-end flow. Simple length-based splitting is sufficient for MVP. Intelligent splitting deferred to Phase 4.
- **Alternative**: Implement sentence detection immediately
- **Trade-off**: Occasionally split mid-sentence, but reduces Phase 1 complexity

**Decision 4: Single Provider Only in Phase 1**
- **Rationale**: Multi-provider support with fallback adds significant complexity. Phase 1 should establish the pipeline first, then add resilience in Phase 3.
- **Alternative**: Implement fallback immediately
- **Trade-off**: Less resilient initially, but faster to working prototype

**Decision 5: No Rate Limiting in Phase 1**
- **Rationale**: Rate limiting is important but orthogonal to core message processing. Implementing it now would complicate testing. Phase 2 adds rate limiting after pipeline is validated.
- **Alternative**: Implement basic rate limiting immediately
- **Trade-off**: Bot could be spammy during Phase 1 testing (mitigated by dry-run mode)

**Decision 6: Mention Detection Only (No Trigger Words)**
- **Rationale**: Mentions are simpler and ensure users intentionally interact with bot. Trigger words with probabilities add complexity better suited for Phase 2.
- **Alternative**: Implement trigger words immediately
- **Trade-off**: Less engaging initially, but clearer scope for Phase 1

### Architecture Context

**Message Flow:**
```
NATS chatMsg Event
    ↓
MessageListener.filter_message() → dict | None
    ↓
TriggerEngine.check_triggers() → TriggerResult
    ↓
PromptBuilder.build_*_prompt() → str, str
    ↓
LLMManager.generate_response() → str | None
    ↓
ResponseFormatter.format_response() → list[str]
    ↓
client.send_chat_message() or log (dry-run)
```

**Component Dependencies:**
- MessageListener: Depends on LLMConfig
- TriggerEngine: Depends on LLMConfig (personality.name_variations)
- LLMManager: Depends on LLMConfig (llm_providers, default_provider)
- PromptBuilder: Depends on LLMConfig (personality)
- ResponseFormatter: Depends on LLMConfig (message_processing)
- LLMService: Depends on all components + KrytenClient

**Extension Points for Future Phases:**
- TriggerEngine: Add trigger word matching (Phase 2)
- LLMManager: Add multi-provider fallback (Phase 3)
- PromptBuilder: Add context injection (Phase 3)
- ResponseFormatter: Add sentence-aware splitting (Phase 4)

## 8. Dependencies & External Integrations

### External Systems

- **EXT-001**: NATS message broker - Required for receiving chatMsg events and sending responses
  - Integration Type: Message bus subscription and publishing
  - Provided by: kryten-robot ecosystem
  - Subject Pattern: `kryten.events.cytube.{channel}.chatmsg`

- **EXT-002**: CyTube chat server - Ultimate source of messages and destination for responses
  - Integration Type: Indirect via kryten-robot's CyTube bridge
  - Provided by: kryten-robot
  - Constraint: Message length ≤ 255 characters

### Third-Party Services

- **SVC-001**: LLM API Provider (OpenAI-compatible) - Required for response generation
  - Required Capabilities: Chat completions API, streaming not required
  - SLA Requirements: <10 second response time (configurable)
  - Examples: OpenAI API, OpenRouter, local LM Studio, Ollama with OpenAI compat layer
  - Constraint: Must support OpenAI chat completions format

### Infrastructure Dependencies

- **INF-001**: Python 3.11+ runtime - Required for async/await syntax and type hints
  - Version Constraints: ≥3.11 for improved asyncio and union types
  - Rationale: Modern Python features improve code quality

- **INF-002**: Network connectivity - Required for NATS and LLM API access
  - Requirements: Low latency to NATS (<50ms), variable latency to LLM API
  - Constraint: Must handle transient network failures gracefully

### Data Dependencies

- **DAT-001**: Configuration file (config.json) - Required at service startup
  - Format: JSON conforming to LLMConfig schema
  - Frequency: Read once at startup (hot-reload in Phase 6)
  - Access: Local filesystem or environment variables

### Technology Platform Dependencies

- **PLT-001**: kryten-py ^0.6.0 - Required for NATS client and configuration base classes
  - Version Constraints: Compatible with KrytenConfig, KrytenClient, LifecycleEventPublisher
  - Rationale: Ecosystem integration and shared infrastructure

- **PLT-002**: aiohttp ^3.13.2 - Required for async HTTP requests to LLM API
  - Version Constraints: Must support async context managers and timeout handling
  - Rationale: De facto standard for async HTTP in Python

- **PLT-003**: pydantic ^2.12.5 - Required for configuration validation
  - Version Constraints: Pydantic v2 for improved performance and validation
  - Rationale: Inherited from Phase 0, provides robust config validation

### Compliance Dependencies

None for Phase 1. Future considerations:
- **COM-001**: Rate limiting requirements (Phase 2) - Prevent abuse
- **COM-002**: Content filtering requirements (Phase 4) - Prevent inappropriate responses
- **COM-003**: Data retention policies (Phase 4) - Response logging compliance

## 9. Examples & Edge Cases

### Example 1: Normal Mention Flow

**Input:**
```json
{
  "username": "moviefan",
  "msg": "Hey Cynthia, what's your favorite martial arts movie?",
  "time": 1640000000,
  "meta": {"rank": 1}
}
```

**Processing:**
1. MessageListener: Valid message (not spam, has required fields) → Pass
2. TriggerEngine: "cynthia" found in name_variations → triggered=True, cleaned="what's your favorite martial arts movie?"
3. PromptBuilder:
   - System: "You are CynthiaRothbot, legendary martial artist... [personality]"
   - User: "moviefan says: what's your favorite martial arts movie?"
4. LLMManager: API call → "Enter the Dragon changed my life. Bruce Lee's precision and philosophy transcended cinema."
5. ResponseFormatter: 101 chars ≤ 240 → Single message
6. Output: Send "Enter the Dragon changed my life. Bruce Lee's precision and philosophy transcended cinema."

### Example 2: Spam Message Filtering

**Input:**
```json
{
  "username": "user123",
  "msg": "!skip",
  "time": 1640000000,
  "meta": {"rank": 1}
}
```

**Processing:**
1. MessageListener: Starts with `!` → Return None
2. Pipeline stops: No further processing

### Example 3: Long Response Splitting

**Input:** (Message triggers response)

**LLM Response:** (320 characters)
```
"The path of the warrior is not about seeking glory or recognition. It's about discipline, dedication, and the pursuit of excellence in every movement. True mastery comes from within, through countless hours of practice and self-reflection. Every technique must be executed with intention and precision."
```

**Processing:**
1. ResponseFormatter: 320 chars > 240 → Split needed
2. Split at 237 chars (leave room for "..."):
   - Part 1 (240 chars): "The path of the warrior is not about seeking glory or recognition. It's about discipline, dedication, and the pursuit of excellence in every movement. True mastery comes from within, through countless hours of..."
   - Part 2 (83 chars): "...practice and self-reflection. Every technique must be executed with intention and precision."
3. Output: Send part 1, wait 2 seconds, send part 2

### Example 4: Self-Reference Removal

**LLM Response:**
```
"As Cynthia Rothrock, I believe that true strength comes from discipline."
```

**Processing:**
1. ResponseFormatter: Detect "As Cynthia Rothrock, " prefix
2. Remove prefix: "I believe that true strength comes from discipline."
3. Output: Send cleaned response

### Example 5: LLM API Failure

**Scenario:** LLM API is down or times out

**Processing:**
1. MessageListener: Valid message → Pass
2. TriggerEngine: Mention detected → triggered=True
3. PromptBuilder: Prompts built
4. LLMManager: API call fails (timeout after 10 seconds)
   - Log error: "LLM API request failed: Timeout after 10s"
   - Return None
5. Pipeline: Check `if not llm_response` → Log error and return
6. Output: No message sent, error logged

### Example 6: Missing Required Fields

**Input:**
```json
{
  "username": "user123",
  "time": 1640000000
  // Missing "msg" field
}
```

**Processing:**
1. MessageListener: Missing "msg" field → Return None
2. Log: "Invalid message format: missing required field 'msg'"
3. Pipeline stops

### Example 7: Dry-Run Mode

**Config:** `testing.dry_run = true`

**Input:** Valid mention message

**Processing:**
1-5. Same as Example 1 (normal flow through all components)
6. Check dry_run flag: true → Log instead of send
   - Log: "[DRY RUN] Would send: Enter the Dragon changed my life..."
7. Output: Nothing sent to chat, response logged

### Example 8: Case-Insensitive Mention

**Input:**
```json
{
  "username": "user456",
  "msg": "CYNTHIA can you help?",
  "time": 1640000000,
  "meta": {"rank": 1}
}
```

**Processing:**
1. MessageListener: Valid → Pass
2. TriggerEngine: "CYNTHIA" matches "cynthia" (case-insensitive) → triggered=True
3. Cleaned message: "can you help?"
4-6. Continue normal flow

### Example 9: Multiple Name Variations

**Config:** `name_variations = ["cynthia", "rothrock", "cynthiarothbot"]`

**Input:**
```json
{
  "username": "fan",
  "msg": "yo rothrock, thoughts on the new movie?",
  "time": 1640000000,
  "meta": {"rank": 1}
}
```

**Processing:**
1. MessageListener: Valid → Pass
2. TriggerEngine: "rothrock" found in name_variations → triggered=True
3. Cleaned message: "thoughts on the new movie?"
4-6. Continue normal flow

### Example 10: No Mention (Ignored)

**Input:**
```json
{
  "username": "chatuser",
  "msg": "I love martial arts movies",
  "time": 1640000000,
  "meta": {"rank": 1}
}
```

**Processing:**
1. MessageListener: Valid → Pass
2. TriggerEngine: No name variations found → triggered=False
3. Pipeline: Check `if not trigger_result` → Return
4. Output: No response (trigger words not implemented in Phase 1)

## 10. Validation Criteria

### Component Validation

**MessageListener:**
- [ ] Filters spam messages (starting with `!`, `/`, `.`)
- [ ] Filters system users ([server], [bot], [system])
- [ ] Validates required fields (username, msg, time)
- [ ] Returns None for invalid messages
- [ ] Returns dict for valid messages
- [ ] Logs filtering decisions at DEBUG level

**TriggerEngine:**
- [ ] Detects mentions using name_variations (case-insensitive)
- [ ] Returns TriggerResult with triggered=True for mentions
- [ ] Returns TriggerResult with triggered=False for non-mentions
- [ ] Cleans message by removing bot name
- [ ] Sets trigger_type="mention" and priority=10
- [ ] Handles multiple name variations correctly

**LLMManager:**
- [ ] Makes HTTP requests to configured provider
- [ ] Includes Authorization header with API key
- [ ] Sends correct request body (model, messages, max_tokens, temperature)
- [ ] Parses response and extracts content
- [ ] Applies timeout from configuration
- [ ] Returns None on API errors (logs error)
- [ ] Returns None on timeout (logs timeout)
- [ ] Handles network errors gracefully

**PromptBuilder:**
- [ ] System prompt includes character_name
- [ ] System prompt includes character_description
- [ ] System prompt includes personality_traits (comma-separated)
- [ ] System prompt includes expertise (comma-separated)
- [ ] System prompt includes response_style
- [ ] System prompt includes 240-character limit instruction
- [ ] User prompt includes username and message
- [ ] Prompts are well-formatted and readable

**ResponseFormatter:**
- [ ] Short responses (≤240 chars) returned as single-item list
- [ ] Long responses (>240 chars) split into multiple parts
- [ ] Split parts include "..." continuation indicators
- [ ] Removes "As {character_name}," prefixes
- [ ] Removes leading/trailing whitespace
- [ ] Handles empty responses gracefully
- [ ] All parts respect max_message_length

### Integration Validation

**Service Initialization:**
- [ ] All components initialized in __init__
- [ ] Components receive correct configuration
- [ ] Service starts without errors
- [ ] Dry-run mode logged if enabled
- [ ] Bot name logged at startup
- [ ] Default provider logged at startup

**Message Pipeline:**
- [ ] chatMsg events received from NATS
- [ ] Messages flow through all components
- [ ] Responses generated for mentions
- [ ] Responses sent to chat (or logged in dry-run)
- [ ] Multiple response parts sent with delays
- [ ] Errors logged without crashing service

**Error Handling:**
- [ ] Invalid messages logged and skipped
- [ ] LLM API failures logged (no crash)
- [ ] Network errors handled gracefully
- [ ] Missing configuration caught at startup
- [ ] All errors include sufficient context

### Test Validation

**Unit Tests:**
- [ ] All component tests pass
- [ ] Test coverage ≥70% overall
- [ ] Critical components ≥90% coverage
- [ ] Edge cases covered (empty strings, None values, etc.)
- [ ] Async tests use pytest-asyncio correctly

**Integration Tests:**
- [ ] End-to-end flow test passes
- [ ] Dry-run mode test passes
- [ ] Error handling test passes
- [ ] Long response splitting test passes
- [ ] Multiple mention test passes

**Manual Testing:**
- [ ] Bot responds to mentions in test channel
- [ ] Dry-run mode prevents sending messages
- [ ] Long responses split correctly in chat
- [ ] Errors logged but service stays running
- [ ] Bot ignores spam messages
- [ ] Bot ignores messages without mentions

## 11. Related Specifications / Further Reading

### Internal Specifications

- [Phase 0 Corrected Specification](./spec-phase-0-corrected.md) - Foundation configuration and service structure
- [Implementation Plan](../docs/IMPLEMENTATION_PLAN.md) - Overall project roadmap and phase breakdown
- [Configuration Models](../kryten_llm/models/config.py) - Pydantic configuration classes
- [Event Models](../kryten_llm/models/events.py) - TriggerResult and event structures

### External Documentation

- [kryten-py Documentation](../kryten-py/README.md) - KrytenClient and LifecycleEventPublisher usage
- [OpenAI Chat Completions API](https://platform.openai.com/docs/api-reference/chat/create) - API format reference
- [OpenRouter API Docs](https://openrouter.ai/docs) - Alternative provider documentation
- [NATS.io Documentation](https://docs.nats.io/) - NATS messaging patterns
- [Pydantic V2 Documentation](https://docs.pydantic.dev/latest/) - Configuration validation
- [pytest-asyncio Documentation](https://pytest-asyncio.readthedocs.io/) - Async testing patterns

### Future Phase Specifications

- Phase 2 Specification (To Be Created) - Trigger words and rate limiting
- Phase 3 Specification (To Be Created) - Multi-provider LLM and context
- Phase 4 Specification (To Be Created) - Intelligent formatting and validation
- Phase 5 Specification (To Be Created) - Service discovery and monitoring
- Phase 6 Specification (To Be Created) - Refinement and optimization

---

**End of Specification**

This specification provides all necessary details for implementing Phase 1 of kryten-llm. It defines clear requirements, interfaces, acceptance criteria, and examples to guide implementation while maintaining extensibility for future phases.
