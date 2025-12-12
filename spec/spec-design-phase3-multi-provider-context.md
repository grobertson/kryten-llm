---
title: Phase 3 - Multi-Provider LLM & Context Management
version: 1.0
date_created: 2025-12-11
last_updated: 2025-12-11
owner: kryten-llm development team
tags: [design, phase3, llm, context, multi-provider]
---

# Introduction

This specification defines the requirements, constraints, and interfaces for Phase 3 of the kryten-llm implementation: Multi-Provider LLM & Context Management. This phase enhances the bot's intelligence by supporting multiple LLM providers with automatic fallback, and providing rich context awareness through video tracking and chat history.

## 1. Purpose & Scope

### Purpose
Enable the kryten-llm bot to:
1. Support multiple LLM providers (OpenRouter, local models, OpenAI-compatible endpoints) with automatic fallback
2. Maintain awareness of the current video playing in CyTube
3. Track recent chat history for contextual responses
4. Inject relevant context into prompts based on trigger type
5. Implement retry logic with exponential backoff for resilience

### Scope
This specification covers:
- Enhanced LLMManager with multi-provider support
- ContextManager for video and chat history tracking
- Enhanced PromptBuilder with context injection
- Configuration schema for providers and context settings
- Integration with existing Phase 1 and Phase 2 components

### Assumptions
- Phase 1 (Basic Response) and Phase 2 (Triggers & Rate Limiting) are complete
- NATS connection is established and reliable
- CyTube publishes `changemedia` events on video changes
- Chat messages flow through `kryten.events.cytube.{channel}.chatmsg`

### Intended Audience
- Developers implementing Phase 3 features
- System architects reviewing design decisions
- QA engineers writing test plans
- Operations teams deploying the service

## 2. Definitions

| Term | Definition |
|------|------------|
| **LLM Provider** | A service that provides Large Language Model inference capabilities (e.g., OpenRouter, local Ollama, OpenAI) |
| **Provider Priority** | Ordered list determining which provider to try first, second, etc. |
| **Fallback** | Automatic switching to an alternate provider when the primary fails |
| **Context Window** | The maximum number of tokens an LLM can process in a single request |
| **Context Manager** | Component tracking current video and chat history |
| **Video Metadata** | Information about the current video (title, duration, media type) |
| **Chat History Buffer** | Rolling window of recent chat messages (20-50 messages) |
| **Trigger Context** | Additional context string associated with a specific trigger |
| **Exponential Backoff** | Retry strategy where wait time doubles after each failure |
| **Provider Selector** | Logic determining which provider to use for a given request |

## 3. Requirements, Constraints & Guidelines

### Enhanced LLM Manager Requirements

**REQ-001**: LLMManager MUST support multiple provider configurations simultaneously
- Each provider has: name, type, base_url, api_key, model, timeout, max_retries

**REQ-002**: LLMManager MUST attempt providers in priority order
- Try primary provider first
- On failure, try next provider in list
- Continue until success or all providers exhausted

**REQ-003**: LLMManager MUST implement exponential backoff for retries
- Initial delay: 1 second
- Multiplier: 2.0
- Max delay: 30 seconds
- Max retries: configurable per provider (default 3)

**REQ-004**: LLMManager MUST support provider selection by trigger
- Triggers can specify preferred provider/model
- Falls back to default provider list if preferred fails

**REQ-005**: LLMManager MUST handle provider-specific errors gracefully
- HTTP timeouts (408, 504)
- Rate limits (429)
- Authentication errors (401, 403)
- Server errors (500, 502, 503)
- Network errors (connection refused, DNS failure)

**REQ-006**: LLMManager MUST log provider selection and fallback decisions
- Which provider was selected and why
- Which providers failed and with what error
- Final successful provider used
- Total time spent across all attempts

**REQ-007**: LLMManager MUST support different provider types
- OpenAI-compatible (OpenAI, OpenRouter, local endpoints)
- Anthropic-compatible (optional for Phase 3)
- Provider-specific authentication headers

### Context Manager Requirements

**REQ-008**: ContextManager MUST subscribe to CyTube video change events
- Subject: `kryten.events.cytube.{channel}.changemedia`
- Extract: title, duration, type, queueby (user who queued)

**REQ-009**: ContextManager MUST maintain current video state
- Store most recent video metadata
- Update atomically on each `changemedia` event
- Provide thread-safe access to current video

**REQ-010**: ContextManager MUST maintain rolling chat history buffer
- Store last N messages (configurable, default 20-50)
- Include: username, message text, timestamp
- Exclude: spam messages, system messages, bot's own messages
- Implement as efficient ring buffer or deque

**REQ-011**: ContextManager MUST provide context dict for prompt building
- `current_video`: dict with video metadata or None
- `recent_messages`: list of recent chat messages
- `chat_summary`: optional summary of recent conversation

**REQ-012**: ContextManager MUST handle video metadata edge cases
- No video playing (None state)
- Very long video titles (truncate to 200 chars)
- Special characters in metadata
- Missing metadata fields

**REQ-013**: ContextManager MUST respect privacy constraints
- Only store configured number of messages
- Do not persist chat history to disk
- Clear buffer on service restart

### Enhanced Prompt Builder Requirements

**REQ-014**: PromptBuilder MUST accept context dict parameter
- Add to `build_user_prompt()` signature
- Default to empty dict if not provided

**REQ-015**: PromptBuilder MUST inject current video into prompts when available
- Format: "Currently playing: [video title]"
- Position: After user message, before trigger context
- Skip if current_video is None

**REQ-016**: PromptBuilder MUST inject recent chat history when available
- Format: "Recent conversation:\n- user1: message1\n- user2: message2"
- Limit: Last 5-10 messages to avoid token bloat
- Position: After current video, before trigger context
- Skip if chat history empty

**REQ-017**: PromptBuilder MUST inject trigger-specific context
- Use trigger's configured context string
- Position: End of user prompt
- Format: "\n\nContext: {trigger_context}"

**REQ-018**: PromptBuilder MUST manage prompt length
- Estimate token count (rough: chars / 4)
- Truncate chat history if approaching context limit
- Prioritize: trigger context > current video > chat history
- Target: Stay under 75% of provider's context window

**REQ-019**: PromptBuilder MUST support different prompt templates
- Default template (current implementation)
- Trigger-specific templates (optional, future enhancement)
- Template variables: {username}, {message}, {video}, {history}, {context}

### Configuration Requirements

**REQ-020**: Configuration MUST support multiple LLM provider definitions
- Array of provider objects
- Each with: name, type, base_url, api_key, model, timeout, max_retries, priority

**REQ-021**: Configuration MUST define default provider priority order
- List of provider names in order of preference
- Used when trigger doesn't specify provider

**REQ-022**: Configuration MUST allow triggers to specify preferred provider
- Optional `preferred_provider` field on trigger config
- Falls back to default priority if not specified

**REQ-023**: Configuration MUST define context settings
- `chat_history_size`: Number of messages to buffer (default 30)
- `context_window_chars`: Approximate context limit (default 12000)
- `include_video_context`: Boolean to enable/disable video context
- `include_chat_history`: Boolean to enable/disable chat history

**REQ-024**: Configuration MUST support provider-specific headers
- Custom headers dict per provider
- Support for API keys in custom header names

### Security Requirements

**SEC-001**: API keys MUST be stored securely
- Support environment variable references: `${OPENAI_API_KEY}`
- Never log API keys in plaintext
- Redact in error messages and logs

**SEC-002**: Chat history MUST respect privacy
- No persistent storage of chat messages
- Clear buffer on service restart
- Configurable maximum retention size

### Integration Requirements

**REQ-025**: Multi-provider support MUST integrate with existing RateLimiter
- Rate limit checks occur before provider selection
- Provider failures do not count as rate-limited responses
- Successful responses recorded regardless of which provider used

**REQ-026**: Context injection MUST integrate with existing TriggerEngine
- Trigger results include context string
- PromptBuilder receives both trigger result and context dict

**REQ-027**: Provider fallback MUST not exceed rate limits
- All provider attempts count as single request to rate limiter
- Total time across providers counted for performance metrics

### Performance Requirements

**REQ-028**: Context lookup MUST be fast (<10ms)
- In-memory storage only
- No database queries
- Thread-safe concurrent access

**REQ-029**: Provider selection MUST add minimal overhead (<50ms)
- Quick priority evaluation
- Cached provider configurations
- No network calls during selection

**REQ-030**: Total LLM response time SHOULD remain under 10 seconds
- Including all retry attempts and fallbacks
- Timeout poorly performing providers
- Log slow responses for tuning

### Error Handling Requirements

**REQ-031**: Provider failures MUST be logged with context
- Provider name and type
- Error type and message
- Request details (model, approximate prompt length)
- Whether fallback succeeded

**REQ-032**: All providers failing MUST result in graceful degradation
- Log comprehensive error with all provider failures
- Do not send response to chat
- Rate limiter aware of failure (don't record response)

**REQ-033**: Context unavailable MUST not block responses
- Missing video context: proceed without it
- Empty chat history: proceed without it
- Context errors: log warning and proceed

## 4. Interfaces & Data Contracts

### Configuration Schema

```json
{
  "llm": {
    "providers": [
      {
        "name": "openrouter-primary",
        "type": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "${OPENROUTER_API_KEY}",
        "model": "anthropic/claude-3.5-sonnet",
        "timeout": 30,
        "max_retries": 3,
        "priority": 1,
        "custom_headers": {
          "HTTP-Referer": "https://github.com/yourusername/kryten-llm",
          "X-Title": "Kryten LLM Bot"
        }
      },
      {
        "name": "local-ollama",
        "type": "openai",
        "base_url": "http://localhost:11434/v1",
        "api_key": "not-needed",
        "model": "llama3.2:3b",
        "timeout": 60,
        "max_retries": 2,
        "priority": 2
      }
    ],
    "default_provider_priority": ["openrouter-primary", "local-ollama"],
    "retry_strategy": {
      "initial_delay": 1.0,
      "multiplier": 2.0,
      "max_delay": 30.0
    }
  },
  "context": {
    "chat_history_size": 30,
    "context_window_chars": 12000,
    "include_video_context": true,
    "include_chat_history": true,
    "max_video_title_length": 200,
    "max_chat_history_in_prompt": 10
  },
  "triggers": [
    {
      "type": "trigger_word",
      "name": "toddy",
      "patterns": ["toddy", "robert z'dar"],
      "probability": 0.8,
      "priority": 2,
      "context": "Respond enthusiastically about Robert Z'Dar and the divine energy of Tango & Cash",
      "preferred_provider": "openrouter-primary"
    }
  ]
}
```

### ContextManager Interface

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any

@dataclass
class VideoMetadata:
    """Current video information from CyTube."""
    title: str
    duration: int  # seconds
    type: str  # "yt", "vm", "dm", etc.
    queued_by: str
    timestamp: datetime

@dataclass
class ChatMessage:
    """A chat message for history buffer."""
    username: str
    message: str
    timestamp: datetime
    
class ContextManager:
    """Manages video and chat context for LLM prompts."""
    
    def __init__(self, config: LLMConfig):
        """Initialize with configuration."""
        self.config = config
        self.current_video: Optional[VideoMetadata] = None
        self.chat_history: deque[ChatMessage] = deque(
            maxlen=config.context.chat_history_size
        )
    
    async def start(self, nats_client: NatsClient) -> None:
        """Start subscribing to context events."""
        await nats_client.subscribe(
            f"kryten.events.cytube.{self.config.cytube.channel}.changemedia",
            self._handle_video_change
        )
    
    async def _handle_video_change(self, msg: Dict[str, Any]) -> None:
        """Handle video change event."""
        self.current_video = VideoMetadata(
            title=msg.get("title", "Unknown")[:200],
            duration=msg.get("seconds", 0),
            type=msg.get("type", "unknown"),
            queued_by=msg.get("queueby", "unknown"),
            timestamp=datetime.now()
        )
    
    def add_chat_message(self, username: str, message: str) -> None:
        """Add a message to chat history buffer."""
        if username == self.config.personality.character_name:
            return  # Don't store bot's own messages
        self.chat_history.append(ChatMessage(
            username=username,
            message=message,
            timestamp=datetime.now()
        ))
    
    def get_context(self) -> Dict[str, Any]:
        """Get current context for prompt building."""
        return {
            "current_video": {
                "title": self.current_video.title,
                "duration": self.current_video.duration,
                "queued_by": self.current_video.queued_by
            } if self.current_video else None,
            "recent_messages": [
                {"username": msg.username, "message": msg.message}
                for msg in list(self.chat_history)[-10:]  # Last 10 messages
            ]
        }
```

### Enhanced LLMManager Interface

```python
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import asyncio
import aiohttp

@dataclass
class LLMProvider:
    """Configuration for a single LLM provider."""
    name: str
    type: str  # "openai", "anthropic"
    base_url: str
    api_key: str
    model: str
    timeout: float
    max_retries: int
    priority: int
    custom_headers: Optional[Dict[str, str]] = None

@dataclass
class LLMRequest:
    """Request to LLM provider."""
    system_prompt: str
    user_prompt: str
    temperature: float = 0.7
    max_tokens: int = 500
    preferred_provider: Optional[str] = None

@dataclass
class LLMResponse:
    """Response from LLM provider."""
    content: str
    provider_used: str
    model_used: str
    tokens_used: Optional[int] = None
    response_time: float = 0.0
    
class LLMManager:
    """Enhanced LLM manager with multi-provider support."""
    
    def __init__(self, config: LLMConfig):
        """Initialize with provider configurations."""
        self.config = config
        self.providers: Dict[str, LLMProvider] = {}
        self._load_providers()
    
    def _load_providers(self) -> None:
        """Load and validate provider configurations."""
        for provider_config in self.config.llm.providers:
            provider = LLMProvider(
                name=provider_config["name"],
                type=provider_config["type"],
                base_url=provider_config["base_url"],
                api_key=self._resolve_api_key(provider_config["api_key"]),
                model=provider_config["model"],
                timeout=provider_config.get("timeout", 30),
                max_retries=provider_config.get("max_retries", 3),
                priority=provider_config.get("priority", 99),
                custom_headers=provider_config.get("custom_headers")
            )
            self.providers[provider.name] = provider
    
    def _resolve_api_key(self, api_key: str) -> str:
        """Resolve environment variable references in API key."""
        if api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            return os.getenv(env_var, "")
        return api_key
    
    def _get_provider_priority(self, preferred_provider: Optional[str]) -> List[str]:
        """Get ordered list of providers to try."""
        if preferred_provider and preferred_provider in self.providers:
            # Preferred first, then others by priority
            others = [
                name for name, p in 
                sorted(self.providers.items(), key=lambda x: x[1].priority)
                if name != preferred_provider
            ]
            return [preferred_provider] + others
        else:
            # Use default priority order
            return self.config.llm.default_provider_priority
    
    async def generate_response(self, request: LLMRequest) -> LLMResponse:
        """Generate response with automatic provider fallback."""
        provider_order = self._get_provider_priority(request.preferred_provider)
        errors = []
        
        for provider_name in provider_order:
            if provider_name not in self.providers:
                continue
                
            provider = self.providers[provider_name]
            
            try:
                response = await self._try_provider(provider, request)
                logger.info(f"LLM response generated using provider: {provider_name}")
                return response
                
            except Exception as e:
                error_msg = f"Provider {provider_name} failed: {str(e)}"
                logger.warning(error_msg)
                errors.append(error_msg)
                continue
        
        # All providers failed
        raise RuntimeError(
            f"All LLM providers failed. Errors: {'; '.join(errors)}"
        )
    
    async def _try_provider(
        self, 
        provider: LLMProvider, 
        request: LLMRequest
    ) -> LLMResponse:
        """Attempt to get response from a single provider with retries."""
        retry_delay = self.config.llm.retry_strategy["initial_delay"]
        
        for attempt in range(provider.max_retries):
            try:
                start_time = time.time()
                
                # Build request based on provider type
                if provider.type == "openai":
                    response = await self._call_openai_provider(provider, request)
                else:
                    raise ValueError(f"Unsupported provider type: {provider.type}")
                
                response_time = time.time() - start_time
                response.response_time = response_time
                
                return response
                
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < provider.max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(
                        retry_delay * self.config.llm.retry_strategy["multiplier"],
                        self.config.llm.retry_strategy["max_delay"]
                    )
                else:
                    raise
    
    async def _call_openai_provider(
        self, 
        provider: LLMProvider, 
        request: LLMRequest
    ) -> LLMResponse:
        """Call OpenAI-compatible provider API."""
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json"
        }
        if provider.custom_headers:
            headers.update(provider.custom_headers)
        
        payload = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt}
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{provider.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=provider.timeout)
            ) as response:
                response.raise_for_status()
                data = await response.json()
                
                return LLMResponse(
                    content=data["choices"][0]["message"]["content"],
                    provider_used=provider.name,
                    model_used=provider.model,
                    tokens_used=data.get("usage", {}).get("total_tokens")
                )
```

### Enhanced PromptBuilder Interface

```python
from typing import Dict, Any, Optional

class PromptBuilder:
    """Enhanced prompt builder with context injection."""
    
    def __init__(self, config: LLMConfig):
        """Initialize with configuration."""
        self.config = config
    
    def build_user_prompt(
        self,
        username: str,
        message: str,
        trigger_context: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Build user prompt with context injection.
        
        Args:
            username: User who sent the message
            message: The message content
            trigger_context: Trigger-specific context string
            context: Context dict from ContextManager
            
        Returns:
            Formatted user prompt string
        """
        parts = [f"{username} says: {message}"]
        
        # Add current video context
        if context and context.get("current_video"):
            video = context["current_video"]
            parts.append(
                f"\n\nCurrently playing: {video['title']} "
                f"(queued by {video['queued_by']})"
            )
        
        # Add chat history context
        if context and context.get("recent_messages"):
            messages = context["recent_messages"]
            if messages:
                history_lines = [
                    f"- {msg['username']}: {msg['message']}"
                    for msg in messages[-5:]  # Last 5 messages
                ]
                parts.append(
                    f"\n\nRecent conversation:\n" + "\n".join(history_lines)
                )
        
        # Add trigger context
        if trigger_context:
            parts.append(f"\n\nContext: {trigger_context}")
        
        prompt = "".join(parts)
        
        # Ensure we don't exceed context window
        max_chars = self.config.context.context_window_chars
        if len(prompt) > max_chars:
            # Truncate chat history first
            prompt = self._truncate_prompt(prompt, max_chars)
        
        return prompt
    
    def _truncate_prompt(self, prompt: str, max_chars: int) -> str:
        """Truncate prompt intelligently to fit context window."""
        # Simple truncation for Phase 3
        # Priority: keep username/message and trigger context
        # Cut chat history if needed
        return prompt[:max_chars]
```

## 5. Acceptance Criteria

**AC-001**: Given multiple providers configured, When primary provider succeeds, Then response uses primary provider and no fallback occurs

**AC-002**: Given multiple providers configured, When primary provider fails with 500 error, Then fallback to secondary provider occurs and response succeeds

**AC-003**: Given all providers fail, When generate_response called, Then RuntimeError raised with all provider error messages

**AC-004**: Given video playing in CyTube, When changemedia event received, Then ContextManager updates current_video state

**AC-005**: Given chat messages flowing, When messages received, Then ContextManager maintains last N messages in history buffer

**AC-006**: Given current video and chat history available, When prompt built, Then prompt includes video title and recent messages

**AC-007**: Given trigger with context configured, When response generated, Then prompt includes trigger context string

**AC-008**: Given trigger with preferred_provider, When response requested, Then preferred provider tried first before fallback

**AC-009**: Given provider timeout of 30 seconds, When provider doesn't respond in time, Then request times out and fallback occurs

**AC-010**: Given exponential backoff configured, When provider fails, Then retry delays are: 1s, 2s, 4s (up to max_delay)

## 6. Test Automation Strategy

### Test Levels

**Unit Tests**:
- LLMManager provider selection logic
- LLMManager retry and backoff calculation
- ContextManager video metadata parsing
- ContextManager chat history buffer management
- PromptBuilder context injection
- PromptBuilder prompt truncation
- Configuration loading and validation

**Integration Tests**:
- LLMManager with mock HTTP responses (success, failure, timeout)
- ContextManager with mock NATS events
- Full pipeline: message → context → prompt → LLM → response
- Provider fallback scenarios
- Context injection in real prompts

**End-to-End Tests** (Manual):
- Real LLM providers (OpenRouter, local Ollama)
- Real CyTube video changes
- Real chat messages and responses
- Performance under load

### Test Frameworks
- pytest for unit and integration tests
- pytest-asyncio for async test support
- pytest-mock for mocking
- aioresponses for mocking aiohttp calls
- Coverage target: >80% for Phase 3 code

### Test Data Management
- Mock provider configurations for tests
- Mock video metadata for context tests
- Mock chat messages for history tests
- Environment variables for API keys in CI/CD

### CI/CD Integration
- Run tests on every commit
- Fail build if coverage drops below threshold
- Integration tests run against mock services
- End-to-end tests run nightly against real services

## 7. Rationale & Context

### Multi-Provider Design

**Why multiple providers?**
- Resilience: Single provider outages don't break the bot
- Cost optimization: Use cheaper local models when possible
- Feature access: Different models have different capabilities
- Rate limit mitigation: Spread load across providers

**Why priority-based fallback?**
- Simple to configure and understand
- Predictable behavior for debugging
- Allows cost/quality tradeoffs (expensive accurate model first, cheap fallback)

**Why exponential backoff?**
- Prevents hammering failing services
- Gives transient issues time to resolve
- Standard pattern in distributed systems

### Context Management Design

**Why in-memory only?**
- Fast access (<10ms)
- No persistence complexity
- Privacy-friendly (no stored chat logs)
- Sufficient for use case (recent context only)

**Why rolling buffer?**
- Fixed memory usage
- Automatic old message expiration
- Simple implementation with deque

**Why separate video and chat context?**
- Video changes infrequently (different update pattern)
- Video context higher priority (always include if available)
- Chat history can be truncated if prompt too long

### Prompt Building Strategy

**Why priority order: trigger context > video > chat history?**
- Trigger context most specific to request
- Video context provides immediate situation awareness
- Chat history nice-to-have for continuity

**Why truncate chat history first?**
- Preserves most important context
- User's direct message always included
- Trigger context always included
- Recent video always included

**Why estimate tokens instead of exact count?**
- Tokenization expensive (requires model-specific tokenizer)
- Rough estimate (chars / 4) good enough for 75% target
- Overestimate slightly to stay safe

## 8. Dependencies & External Integrations

### External Systems

**EXT-001**: CyTube Server - Publishes `changemedia` events when video changes
- Required capabilities: Event publishing to NATS
- SLA requirements: Real-time event delivery (<1s latency)
- Failure mode: Video context unavailable, bot continues without it

**EXT-002**: NATS Message Bus - Routes all events and messages
- Required capabilities: Pub/sub messaging, subject filtering
- SLA requirements: >99.9% uptime, <100ms message delivery
- Failure mode: Service cannot function, graceful shutdown

### Third-Party Services

**SVC-001**: OpenRouter API - Primary LLM provider
- Required capabilities: OpenAI-compatible chat completions API
- SLA requirements: <30s response time, >95% uptime
- Failure mode: Fallback to secondary provider

**SVC-002**: Local Ollama - Secondary LLM provider
- Required capabilities: OpenAI-compatible API, local model inference
- SLA requirements: <60s response time, >99% uptime (local)
- Failure mode: Fallback to tertiary provider or failure

### Infrastructure Dependencies

**INF-001**: Python 3.11+ runtime - Required for asyncio and type hints
- Version constraints: >=3.11
- Rationale: Modern async features, improved performance

**INF-002**: Network connectivity - Required for API calls
- Requirements: Outbound HTTPS (443), low latency (<200ms)
- Failure mode: Provider fallback, eventual failure if all providers unreachable

### Data Dependencies

**DAT-001**: CyTube video metadata - JSON messages on `changemedia` subject
- Format: `{"title": str, "seconds": int, "type": str, "queueby": str}`
- Frequency: On video change (varies, typically every 3-30 minutes)
- Access: NATS subscription

**DAT-002**: Chat messages - JSON messages on `chatmsg` subject
- Format: `{"username": str, "msg": str, "time": int, "meta": {...}}`
- Frequency: Real-time as users chat
- Access: Existing MessageListener subscription

### Technology Platform Dependencies

**PLT-001**: aiohttp library - HTTP client for LLM API calls
- Version constraints: >=3.9.0
- Rationale: Mature async HTTP client, widely used

**PLT-002**: asyncio - Async/await runtime
- Version constraints: Python 3.11+ stdlib
- Rationale: Required for concurrent operations

### Compliance Dependencies

**COM-001**: No persistent chat storage - Privacy requirement
- Impact: Must use in-memory buffer only, clear on restart
- Validation: Code review, no database/file writes of chat content

## 9. Examples & Edge Cases

### Example 1: Successful Primary Provider

```python
# Configuration
providers = [
    {"name": "openrouter", "priority": 1, ...},
    {"name": "local", "priority": 2, ...}
]

# Request
request = LLMRequest(
    system_prompt="You are a helpful bot",
    user_prompt="Tell me about Robert Z'Dar"
)

# Result
response = await llm_manager.generate_response(request)
assert response.provider_used == "openrouter"
# No fallback occurred
```

### Example 2: Primary Fails, Fallback Succeeds

```python
# OpenRouter returns 500 error
# Local Ollama succeeds

response = await llm_manager.generate_response(request)
assert response.provider_used == "local"
# Logs show openrouter failed, local succeeded
```

### Example 3: All Providers Fail

```python
# Both providers timeout

try:
    response = await llm_manager.generate_response(request)
except RuntimeError as e:
    assert "All LLM providers failed" in str(e)
    assert "openrouter" in str(e)
    assert "local" in str(e)
# No response sent to chat
```

### Example 4: Video Context Injection

```python
# Video playing: "Tango & Cash (1989)"
context = context_manager.get_context()
# {
#   "current_video": {"title": "Tango & Cash (1989)", ...},
#   "recent_messages": [...]
# }

prompt = prompt_builder.build_user_prompt(
    username="user1",
    message="Tell me about this movie",
    trigger_context=None,
    context=context
)

# Result:
# user1 says: Tell me about this movie
#
# Currently playing: Tango & Cash (1989) (queued by user2)
```

### Example 5: Chat History Injection

```python
# Recent messages:
# - user1: "I love action movies"
# - user2: "Me too!"
# - user1: "Especially 80s films"

prompt = prompt_builder.build_user_prompt(
    username="user1",
    message="What's a good 80s action film?",
    context=context
)

# Result:
# user1 says: What's a good 80s action film?
#
# Recent conversation:
# - user1: I love action movies
# - user2: Me too!
# - user1: Especially 80s films
```

### Example 6: Trigger with Preferred Provider

```python
# Trigger configuration
trigger = {
    "name": "toddy",
    "context": "Respond enthusiastically about Robert Z'Dar",
    "preferred_provider": "openrouter"
}

# Request specifies preferred provider
request = LLMRequest(
    system_prompt="...",
    user_prompt="...",
    preferred_provider="openrouter"
)

# OpenRouter tried first, even if local has higher priority
```

### Edge Case 1: Very Long Video Title

```python
title = "Very Long Title " * 50  # 800+ characters

# ContextManager truncates
video = VideoMetadata(title=title[:200], ...)
assert len(video.title) == 200
```

### Edge Case 2: No Video Playing

```python
context = context_manager.get_context()
assert context["current_video"] is None

# PromptBuilder skips video section
prompt = prompt_builder.build_user_prompt(...)
assert "Currently playing:" not in prompt
```

### Edge Case 3: Empty Chat History

```python
context = context_manager.get_context()
assert context["recent_messages"] == []

# PromptBuilder skips chat history section
prompt = prompt_builder.build_user_prompt(...)
assert "Recent conversation:" not in prompt
```

### Edge Case 4: Prompt Too Long

```python
# Chat history with 50 long messages
# Video title is 200 chars
# Trigger context is 100 chars
# User message is 200 chars
# Total: ~3500 chars

# PromptBuilder truncates to fit context window
prompt = prompt_builder.build_user_prompt(...)
assert len(prompt) <= 3000  # Below limit
# Chat history truncated, but user message and trigger context intact
```

### Edge Case 5: Provider API Key from Environment

```python
# config.json
"api_key": "${OPENROUTER_API_KEY}"

# Environment
os.environ["OPENROUTER_API_KEY"] = "sk-..."

# LLMManager resolves
provider = llm_manager.providers["openrouter"]
assert provider.api_key == "sk-..."
assert "${" not in provider.api_key  # Resolved
```

## 10. Validation Criteria

### Functional Validation

**VAL-001**: Provider fallback works
- Test: Disable primary provider, send request
- Expected: Secondary provider used, response received
- Method: Integration test with mock HTTP

**VAL-002**: Context injection works
- Test: Set video and chat history, build prompt
- Expected: Prompt includes video title and recent messages
- Method: Unit test with mock context

**VAL-003**: Exponential backoff works
- Test: Provider fails 3 times, measure delays
- Expected: Delays are approximately 1s, 2s, 4s
- Method: Integration test with time mocking

**VAL-004**: Chat history buffer works
- Test: Add 100 messages to buffer with max size 30
- Expected: Only last 30 messages retained
- Method: Unit test

**VAL-005**: API key resolution works
- Test: Configure provider with `${ENV_VAR}`, set environment variable
- Expected: Provider uses environment variable value
- Method: Unit test

### Performance Validation

**VAL-006**: Context lookup is fast
- Test: Benchmark `get_context()` call
- Expected: <10ms per call
- Method: Performance test with timeit

**VAL-007**: Provider selection is fast
- Test: Benchmark `_get_provider_priority()` call
- Expected: <1ms per call
- Method: Performance test

**VAL-008**: Total response time acceptable
- Test: End-to-end request with all providers succeeding
- Expected: <10 seconds total
- Method: Integration test with real providers

### Security Validation

**VAL-009**: API keys not logged
- Test: Trigger provider failure, check logs
- Expected: No API keys in log output
- Method: Integration test with log inspection

**VAL-010**: Chat history not persisted
- Test: Restart service, check for chat history files
- Expected: No files created, memory cleared
- Method: Integration test

### Error Handling Validation

**VAL-011**: All providers failing handled gracefully
- Test: Disable all providers, send request
- Expected: RuntimeError raised, no response sent, detailed error logged
- Method: Integration test

**VAL-012**: Missing context handled gracefully
- Test: Request with no video or chat history
- Expected: Prompt built without context, response succeeds
- Method: Unit test

## 11. Related Specifications / Further Reading

### Related Kryten-LLM Specifications
- Phase 1 Specification: Basic Response (if created)
- Phase 2 Specification: Triggers & Rate Limiting (if created)
- Phase 4 Specification: Intelligent Formatting (future)

### External Documentation
- [OpenAI API Reference](https://platform.openai.com/docs/api-reference/chat/create) - Chat completions API standard
- [OpenRouter Documentation](https://openrouter.ai/docs) - Provider-specific details
- [Ollama API Documentation](https://github.com/ollama/ollama/blob/main/docs/api.md) - Local model API
- [aiohttp Documentation](https://docs.aiohttp.org/) - HTTP client library
- [asyncio Documentation](https://docs.python.org/3/library/asyncio.html) - Async patterns

### Design Patterns
- Circuit Breaker Pattern - For provider failure handling
- Retry Pattern with Exponential Backoff - For transient failures
- Priority Queue Pattern - For provider selection
- Ring Buffer Pattern - For chat history

### Best Practices
- [12-Factor App Configuration](https://12factor.net/config) - Environment-based config
- [Semantic Versioning](https://semver.org/) - Version management
- [Keep a Changelog](https://keepachangelog.com/) - Change documentation

---

*This specification provides a comprehensive blueprint for implementing Phase 3 multi-provider LLM support and context management. All requirements are testable and support incremental development and validation.*
