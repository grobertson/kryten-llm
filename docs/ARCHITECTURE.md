# Kryten-LLM Technical Architecture

## System Overview

```
┌─────────────────┐
│   CyTube Chat   │
│   (Users)       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────┐
│  Kryten-Robot   │────▶│      NATS        │
│   (Bridge)      │◀────│  Message Bus     │
└─────────────────┘     └────────┬─────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │  kryten-llm     │
                        │   Service       │
                        └────────┬────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
          ┌─────────────┐  ┌──────────┐  ┌──────────┐
          │ LLM Provider│  │  NATS KV │  │  Logs    │
          │ (Local/Cloud)│  │  Store   │  │          │
          └─────────────┘  └──────────┘  └──────────┘
```

## Component Architecture

### Core Components

#### 1. Message Listener

**Responsibility**: Monitor CyTube chat messages via NATS

**Implementation**:
```python
class MessageListener:
    """Subscribes to chat messages and filters for relevance."""
    
    def __init__(self, client: KrytenClient, config: Config):
        self.client = client
        self.config = config
        self.message_queue = asyncio.Queue()
        
    async def start(self):
        """Subscribe to chat messages."""
        @self.client.on("chatmsg")
        async def on_message(event: ChatMessageEvent):
            if self._should_process(event):
                await self.message_queue.put(event)
                
    def _should_process(self, event: ChatMessageEvent) -> bool:
        """Filter spam, commands, and bot messages."""
        # Ignore own messages
        if event.username == self.config.cytube.username:
            return False
            
        # Ignore command messages (starting with !)
        if event.message.startswith('!'):
            return False
            
        # Ignore empty/whitespace
        if not event.message.strip():
            return False
            
        return True
```

**NATS Subjects**:
- Subscribe: `kryten.events.cytube.{channel}.chatmsg`
- Publish: `kryten.events.cytube.{channel}.chatmsg` (responses)

#### 2. Trigger Engine

**Responsibility**: Analyze messages for mentions and trigger words

**Implementation**:
```python
class TriggerEngine:
    """Analyzes messages and determines if bot should respond."""
    
    def __init__(self, config: Config):
        self.config = config
        self.triggers = self._load_triggers()
        self.bot_name = config.cytube.username
        
    async def analyze(self, message: str, username: str, rank: int) -> TriggerResult:
        """Analyze message and return trigger result."""
        
        # Check for direct mention (highest priority)
        if self._is_mentioned(message):
            return TriggerResult(
                triggered=True,
                trigger_type="mention",
                trigger_name="direct_mention",
                cleaned_message=self._strip_bot_name(message),
                context={},
                priority=10
            )
        
        # Check trigger words
        for trigger in self.triggers:
            if self._matches_trigger(message, trigger):
                # Probability check
                if random.random() < trigger.probability:
                    return TriggerResult(
                        triggered=True,
                        trigger_type="trigger_word",
                        trigger_name=trigger.name,
                        cleaned_message=message,
                        context=trigger.context,
                        priority=trigger.priority
                    )
        
        return TriggerResult(triggered=False)
    
    def _is_mentioned(self, message: str) -> bool:
        """Check if bot name appears in message."""
        message_lower = message.lower()
        bot_name_lower = self.bot_name.lower()
        
        # Check full name
        if bot_name_lower in message_lower:
            return True
            
        # Check partial names (configurable)
        for partial in self.config.personality.name_variations:
            if partial.lower() in message_lower:
                return True
                
        return False
```

**Trigger Configuration**:
```python
@dataclass
class Trigger:
    name: str
    patterns: list[str]
    probability: float
    cooldown_seconds: int
    context: dict[str, Any]
    response_style: str
    max_responses_per_hour: int
    priority: int = 5
    enabled: bool = True
```

#### 3. Rate Limiter

**Responsibility**: Enforce cooldowns and rate limits

**Implementation**:
```python
class RateLimiter:
    """Tracks and enforces rate limits and cooldowns."""
    
    def __init__(self, config: Config):
        self.config = config
        self.global_responses: deque = deque(maxlen=100)
        self.user_responses: dict[str, deque] = {}
        self.trigger_cooldowns: dict[str, datetime] = {}
        self.user_cooldowns: dict[str, datetime] = {}
        
    async def check_allowed(
        self,
        username: str,
        user_rank: int,
        trigger_name: str
    ) -> tuple[bool, str]:
        """Check if response is allowed. Returns (allowed, reason)."""
        
        now = datetime.now(UTC)
        
        # Apply admin multipliers
        multiplier = self._get_multiplier(user_rank)
        
        # Check global rate limit
        global_limit = self.config.rate_limits.global_max_per_minute
        recent_global = sum(1 for ts in self.global_responses 
                           if (now - ts).total_seconds() < 60)
        if recent_global >= global_limit:
            return False, "Global rate limit exceeded"
        
        # Check global cooldown
        if self.global_responses:
            last_response = self.global_responses[-1]
            cooldown = self.config.rate_limits.global_cooldown_seconds * multiplier
            if (now - last_response).total_seconds() < cooldown:
                return False, "Global cooldown active"
        
        # Check user-specific limits
        user_limit = int(self.config.rate_limits.user_max_per_hour * multiplier)
        user_responses = self.user_responses.get(username, deque())
        recent_user = sum(1 for ts in user_responses 
                         if (now - ts).total_seconds() < 3600)
        if recent_user >= user_limit:
            return False, f"User rate limit exceeded for {username}"
        
        # Check user cooldown
        if username in self.user_cooldowns:
            last_user_response = self.user_cooldowns[username]
            cooldown = self.config.rate_limits.user_cooldown_seconds * multiplier
            if (now - last_user_response).total_seconds() < cooldown:
                return False, f"User cooldown active for {username}"
        
        # Check trigger-specific cooldown
        if trigger_name in self.trigger_cooldowns:
            trigger = self._get_trigger(trigger_name)
            last_trigger = self.trigger_cooldowns[trigger_name]
            if (now - last_trigger).total_seconds() < trigger.cooldown_seconds:
                return False, f"Trigger cooldown active for {trigger_name}"
        
        return True, "OK"
    
    def record_response(self, username: str, trigger_name: str):
        """Record that a response was sent."""
        now = datetime.now(UTC)
        self.global_responses.append(now)
        
        if username not in self.user_responses:
            self.user_responses[username] = deque(maxlen=50)
        self.user_responses[username].append(now)
        
        self.user_cooldowns[username] = now
        self.trigger_cooldowns[trigger_name] = now
    
    def _get_multiplier(self, user_rank: int) -> float:
        """Get cooldown/limit multiplier for user rank."""
        if user_rank >= 2:  # Moderator+
            return self.config.rate_limits.admin_cooldown_multiplier
        return 1.0
```

#### 4. LLM Manager

**Responsibility**: Manage LLM providers and generate responses

**Implementation**:
```python
class LLMManager:
    """Manages multiple LLM providers and generates responses."""
    
    def __init__(self, config: Config):
        self.config = config
        self.providers = self._init_providers()
        self.prompt_builder = PromptBuilder(config)
        
    async def generate_response(
        self,
        message: str,
        username: str,
        trigger_result: TriggerResult,
        context: dict[str, Any]
    ) -> str:
        """Generate LLM response for message."""
        
        # Select provider based on trigger
        provider = self._select_provider(trigger_result)
        
        # Build prompt
        prompt = self.prompt_builder.build(
            message=message,
            username=username,
            trigger_result=trigger_result,
            context=context
        )
        
        # Generate response with retries
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                response = await self._call_llm(provider, prompt)
                
                # Validate and process response
                processed = self._process_response(response)
                
                if self._is_valid_response(processed, message):
                    return processed
                    
            except Exception as e:
                logger.error(f"LLM attempt {attempt + 1} failed: {e}")
                
                # Try fallback provider
                if attempt < max_attempts - 1 and provider.fallback:
                    provider = self.providers[provider.fallback]
        
        # All attempts failed
        return None
    
    async def _call_llm(
        self,
        provider: LLMProvider,
        prompt: str
    ) -> str:
        """Call LLM API with timeout."""
        
        async with aiohttp.ClientSession() as session:
            async with asyncio.timeout(provider.timeout_seconds):
                async with session.post(
                    f"{provider.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {provider.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": provider.model,
                        "messages": [
                            {"role": "system", "content": self.prompt_builder.system_prompt},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": provider.max_tokens,
                        "temperature": provider.temperature
                    }
                ) as resp:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
```

**Provider Configuration**:
```python
@dataclass
class LLMProvider:
    name: str
    type: str  # "openai_compatible", "openrouter", "anthropic"
    base_url: str
    api_key: str
    model: str
    max_tokens: int
    temperature: float
    timeout_seconds: int = 10
    fallback: str | None = None
```

#### 5. Prompt Builder

**Responsibility**: Construct LLM prompts with context

**Implementation**:
```python
class PromptBuilder:
    """Builds contextualized prompts for LLM."""
    
    def __init__(self, config: Config):
        self.config = config
        self.system_prompt = self._build_system_prompt()
        
    def build(
        self,
        message: str,
        username: str,
        trigger_result: TriggerResult,
        context: dict[str, Any]
    ) -> str:
        """Build prompt with all context."""
        
        # Start with base prompt
        prompt_parts = []
        
        # Add current video context if available
        if context.get("current_video"):
            video = context["current_video"]
            prompt_parts.append(
                f"Currently playing: {video['title']}"
            )
        
        # Add trigger-specific context
        if trigger_result.context:
            prompt_parts.append(
                f"Context: {trigger_result.context}"
            )
        
        # Add recent chat history (optional)
        if context.get("recent_messages"):
            history = "\n".join(
                f"{msg.username}: {msg.message}"
                for msg in context["recent_messages"][-3:]
            )
            prompt_parts.append(f"Recent chat:\n{history}")
        
        # Add user message
        prompt_parts.append(
            f"\nUser {username} says: {message}\n\n"
            f"Respond as {self.config.personality.character_name} "
            f"(under 200 characters):"
        )
        
        return "\n\n".join(prompt_parts)
    
    def _build_system_prompt(self) -> str:
        """Build system prompt from personality config."""
        p = self.config.personality
        
        traits = ", ".join(p.personality_traits)
        expertise = ", ".join(p.expertise)
        
        return f"""You are {p.character_name}, {p.character_description}.

Personality: {traits}

Your expertise: {expertise}

You're chatting in a CyTube channel dedicated to grindhouse films, B-movies, and cult classics. The audience loves kung fu films, horror, and 1980s action movies.

Guidelines:
- Keep responses SHORT (under 200 characters)
- Be pithy, entertaining, and in-character
- Match the casual, fun tone of the chat
- Reference your expertise when relevant
- Don't be preachy or overly helpful
- Embrace the absurd and humorous

Response style: {p.response_style}"""
```

#### 6. Response Formatter

**Responsibility**: Format and split responses for CyTube

**Implementation**:
```python
class ResponseFormatter:
    """Formats LLM responses for CyTube chat."""
    
    def __init__(self, config: Config):
        self.max_length = config.message_processing.max_message_length
        self.split_delay = config.message_processing.split_delay_seconds
        
    def format(self, response: str) -> list[str]:
        """Format response and split if needed."""
        
        # Clean up response
        cleaned = self._clean_response(response)
        
        # Check if splitting needed
        if len(cleaned) <= self.max_length:
            return [cleaned]
        
        # Split intelligently
        return self._split_message(cleaned)
    
    def _clean_response(self, response: str) -> str:
        """Clean up LLM response."""
        
        # Remove common LLM artifacts
        cleaned = response.strip()
        
        # Remove self-referential prefixes
        prefixes_to_remove = [
            "As Cynthia Rothrock, ",
            "As an AI, ",
            "In my opinion, "
        ]
        for prefix in prefixes_to_remove:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
        
        # Limit emoji (if configured)
        if self.config.message_processing.filter_emoji:
            cleaned = self._limit_emoji(cleaned)
        
        return cleaned
    
    def _split_message(self, message: str) -> list[str]:
        """Split long message intelligently."""
        
        parts = []
        current = ""
        
        # Split on sentence boundaries
        sentences = re.split(r'([.!?]+\s+)', message)
        
        for i in range(0, len(sentences), 2):
            sentence = sentences[i]
            separator = sentences[i+1] if i+1 < len(sentences) else ""
            
            if len(current) + len(sentence) + len(separator) <= self.max_length:
                current += sentence + separator
            else:
                if current:
                    parts.append(current.strip())
                current = sentence + separator
        
        if current:
            parts.append(current.strip())
        
        # Add continuation indicators
        for i in range(len(parts) - 1):
            if not parts[i].endswith(('...', '…')):
                parts[i] += '...'
        
        return parts
```

#### 7. Context Manager

**Responsibility**: Track video, chat history, and user context

**Implementation**:
```python
class ContextManager:
    """Manages contextual information for LLM prompts."""
    
    def __init__(self, client: KrytenClient, config: Config):
        self.client = client
        self.config = config
        self.current_video: dict | None = None
        self.chat_history: deque = deque(
            maxlen=config.context.chat_history_buffer
        )
        
    async def start(self):
        """Subscribe to video changes and chat."""
        
        @self.client.on("changemedia")
        async def on_video_change(event):
            self.current_video = {
                "title": event.title,
                "type": event.type,
                "id": event.id,
                "duration": event.duration
            }
            logger.info(f"Video changed: {event.title}")
        
        @self.client.on("chatmsg")
        async def on_chat(event):
            self.chat_history.append(event)
    
    def get_context(self) -> dict[str, Any]:
        """Get current context for LLM."""
        return {
            "current_video": self.current_video,
            "recent_messages": list(self.chat_history)[-5:],
            "time_of_day": datetime.now().strftime("%H:%M")
        }
```

#### 8. Response Logger

**Responsibility**: Log responses for evaluation

**Implementation**:
```python
class ResponseLogger:
    """Logs LLM responses for evaluation and tuning."""
    
    def __init__(self, config: Config):
        self.config = config
        self.log_file = Path(config.testing.log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
    async def log_response(
        self,
        message: str,
        username: str,
        user_rank: int,
        trigger_result: TriggerResult,
        llm_response: str,
        response_sent: bool,
        rate_limit_status: dict
    ):
        """Log response details as JSONL."""
        
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "message_id": str(uuid.uuid4()),
            "trigger_type": trigger_result.trigger_type,
            "trigger_name": trigger_result.trigger_name,
            "username": username,
            "user_rank": user_rank,
            "input_message": message,
            "llm_provider": "...",
            "llm_model": "...",
            "llm_response_raw": llm_response,
            "response_sent": response_sent,
            "dry_run": self.config.testing.dry_run,
            "rate_limit_status": rate_limit_status
        }
        
        # Append to JSONL file
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
```

### Main Service Loop

```python
class LLMService:
    """Main service coordinator."""
    
    def __init__(self, config_path: Path):
        self.config = Config.load(config_path)
        self.client = KrytenClient(...)
        
        # Initialize components
        self.listener = MessageListener(self.client, self.config)
        self.trigger_engine = TriggerEngine(self.config)
        self.rate_limiter = RateLimiter(self.config)
        self.llm_manager = LLMManager(self.config)
        self.formatter = ResponseFormatter(self.config)
        self.context_manager = ContextManager(self.client, self.config)
        self.logger = ResponseLogger(self.config)
        
    async def start(self):
        """Start service."""
        await self.client.connect()
        await self.listener.start()
        await self.context_manager.start()
        
        # Process messages
        asyncio.create_task(self._process_messages())
        
        logger.info("LLM service started")
        
    async def _process_messages(self):
        """Main message processing loop."""
        
        while True:
            try:
                # Get message from queue
                event = await self.listener.message_queue.get()
                
                # Analyze for triggers
                trigger_result = await self.trigger_engine.analyze(
                    event.message,
                    event.username,
                    event.rank
                )
                
                if not trigger_result.triggered:
                    continue
                
                # Check rate limits
                allowed, reason = await self.rate_limiter.check_allowed(
                    event.username,
                    event.rank,
                    trigger_result.trigger_name
                )
                
                if not allowed:
                    logger.debug(f"Rate limit: {reason}")
                    continue
                
                # Generate LLM response
                context = self.context_manager.get_context()
                llm_response = await self.llm_manager.generate_response(
                    trigger_result.cleaned_message,
                    event.username,
                    trigger_result,
                    context
                )
                
                if not llm_response:
                    logger.warning("LLM failed to generate response")
                    continue
                
                # Format response
                formatted = self.formatter.format(llm_response)
                
                # Send or log (dry run)
                if self.config.testing.dry_run:
                    logger.info(f"DRY RUN - Would send: {formatted}")
                else:
                    await self._send_responses(formatted)
                    self.rate_limiter.record_response(
                        event.username,
                        trigger_result.trigger_name
                    )
                
                # Log for evaluation
                await self.logger.log_response(
                    event.message,
                    event.username,
                    event.rank,
                    trigger_result,
                    llm_response,
                    not self.config.testing.dry_run,
                    {"allowed": allowed, "reason": reason}
                )
                
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
    
    async def _send_responses(self, messages: list[str]):
        """Send formatted responses to chat."""
        for i, msg in enumerate(messages):
            await self.client.send_chat(
                self.config.cytube.channel,
                msg
            )
            
            # Delay between parts
            if i < len(messages) - 1:
                await asyncio.sleep(self.formatter.split_delay)
```

## Data Models

### Configuration

```python
@dataclass
class NatsConfig:
    url: str
    credentials: str | None = None

@dataclass
class CyTubeConfig:
    domain: str
    channel: str
    username: str

@dataclass
class PersonalityConfig:
    character_name: str
    character_description: str
    personality_traits: list[str]
    expertise: list[str]
    response_style: str
    name_variations: list[str]

@dataclass
class Config:
    nats: NatsConfig
    cytube: CyTubeConfig
    personality: PersonalityConfig
    llm_providers: dict[str, LLMProvider]
    triggers: list[Trigger]
    rate_limits: RateLimits
    message_processing: MessageProcessing
    testing: TestingConfig
    context: ContextConfig
```

### Events

```python
@dataclass
class TriggerResult:
    triggered: bool
    trigger_type: str | None = None  # "mention", "trigger_word"
    trigger_name: str | None = None
    cleaned_message: str | None = None
    context: dict[str, Any] | None = None
    priority: int = 5
```

## File Structure

```
kryten-llm/
├── kryten_llm/
│   ├── __init__.py
│   ├── __main__.py              # Entry point
│   ├── config.py                # Configuration management
│   ├── service.py               # Main service class
│   ├── components/
│   │   ├── __init__.py
│   │   ├── listener.py          # MessageListener
│   │   ├── trigger_engine.py    # TriggerEngine
│   │   ├── rate_limiter.py      # RateLimiter
│   │   ├── llm_manager.py       # LLMManager
│   │   ├── prompt_builder.py    # PromptBuilder
│   │   ├── formatter.py         # ResponseFormatter
│   │   ├── context_manager.py   # ContextManager
│   │   └── logger.py            # ResponseLogger
│   ├── models/
│   │   ├── __init__.py
│   │   ├── config.py            # Configuration data classes
│   │   └── events.py            # Event data classes
│   └── utils/
│       ├── __init__.py
│       └── text_utils.py        # Text processing utilities
├── config.example.json
├── config.json
├── logs/
│   └── llm-responses.jsonl
├── tests/
│   ├── test_trigger_engine.py
│   ├── test_rate_limiter.py
│   └── test_formatter.py
└── docs/
    ├── REQUIREMENTS.md
    ├── ARCHITECTURE.md
    └── IMPLEMENTATION_PLAN.md
```

## Dependencies

```toml
[project]
dependencies = [
    "kryten-py>=0.6.0",
    "aiohttp>=3.9.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
]
```

## Observability

### Logging

- Structured logging with correlation IDs
- Log levels: DEBUG, INFO, WARNING, ERROR
- Key events logged:
  - Message received and processed
  - Trigger activations
  - Rate limit decisions
  - LLM calls and responses
  - Errors and exceptions

### Metrics (Future)

- Messages processed per minute
- Trigger activations by type
- Response generation time
- LLM success/failure rate
- Rate limit hits

### Health

- Publish heartbeats on `kryten.service.heartbeat`
- Service discovery on `kryten.service.discovery`
- Health status: healthy/degraded/failing
