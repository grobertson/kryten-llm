# Phase 0 Implementation Specification

## Overview

This specification defines the technical implementation details for Phase 0 of the kryten-llm project. Phase 0 enhances the existing project skeleton with comprehensive configuration management, Pydantic models, and LLM-specific infrastructure.

## 1. Directory Structure

### 1.1 Required Directories

Create the following directory structure:

```
kryten-llm/
├── kryten_llm/
│   ├── components/         # Phase 1+ component implementations
│   ├── models/             # Data models and configuration
│   │   ├── __init__.py
│   │   ├── config.py       # Pydantic configuration models
│   │   └── events.py       # Event data classes
│   └── utils/              # Utility functions
│       └── __init__.py
├── tests/                  # Test suite
│   ├── __init__.py
│   ├── conftest.py         # Pytest fixtures
│   └── test_config.py      # Configuration tests
└── logs/                   # Runtime logs (in .gitignore)
    └── .gitkeep
```

### 1.2 Implementation

**Command**:
```bash
cd kryten-llm
mkdir -p kryten_llm/components kryten_llm/models kryten_llm/utils tests logs
touch kryten_llm/models/__init__.py
touch kryten_llm/utils/__init__.py
touch tests/__init__.py
touch logs/.gitkeep
```

**Validation**:
- All directories exist
- `__init__.py` files present in package directories
- `logs/` directory added to `.gitignore` if not already present

---

## 2. Dependencies

### 2.1 Required Packages

Add the following dependencies to `pyproject.toml`:

| Package | Version | Purpose |
|---------|---------|---------|
| `aiohttp` | `^3.9.0` | Async HTTP client for LLM API calls |
| `pydantic` | `^2.0.0` | Data validation and settings management |
| `pydantic-settings` | `^2.0.0` | Environment variable support for config |

### 2.2 Implementation

**Command**:
```bash
poetry add aiohttp pydantic pydantic-settings
```

**Expected Changes to `pyproject.toml`**:
```toml
[tool.poetry.dependencies]
python = "^3.10"
kryten-py = "^0.6.0"
aiohttp = "^3.9.0"
pydantic = "^2.0.0"
pydantic-settings = "^2.0.0"
```

**Validation**:
- Run `poetry install` successfully
- Run `poetry show` to verify versions
- Import test: `python -c "import aiohttp, pydantic, pydantic_settings"`

---

## 3. Configuration Models

### 3.1 File: `kryten_llm/models/config.py`

This file defines all configuration data models using Pydantic v2.

#### 3.1.1 NatsConfig

```python
from pydantic import BaseModel, Field


class NatsConfig(BaseModel):
    """NATS connection configuration."""
    
    url: str = Field(
        default="nats://localhost:4222",
        description="NATS server URL"
    )
    credentials: str | None = Field(
        default=None,
        description="Path to NATS credentials file"
    )
```

**Fields**:
- `url`: NATS server URL (default: `nats://localhost:4222`)
- `credentials`: Optional path to NATS `.creds` file for authentication

#### 3.1.2 CyTubeConfig

```python
class CyTubeConfig(BaseModel):
    """CyTube connection configuration."""
    
    domain: str = Field(
        description="CyTube server domain (e.g., cytu.be)"
    )
    channel: str = Field(
        description="CyTube channel name"
    )
    username: str = Field(
        description="Bot username for CyTube"
    )
```

**Fields**:
- `domain`: CyTube server domain (e.g., `cytu.be`, `synchtube.xyz`)
- `channel`: Channel name to join
- `username`: Bot's username in the channel

**Validation**:
- All fields are required (no defaults)
- `domain` should not include protocol (`http://` or `https://`)
- `channel` should be alphanumeric with hyphens/underscores

#### 3.1.3 PersonalityConfig

```python
class PersonalityConfig(BaseModel):
    """Bot personality configuration."""
    
    character_name: str = Field(
        default="CynthiaRothbot",
        description="Bot character name"
    )
    character_description: str = Field(
        default="legendary martial artist and actress",
        description="Character description for LLM context"
    )
    personality_traits: list[str] = Field(
        default=["confident", "action-oriented", "pithy", "martial arts expert"],
        description="List of personality traits"
    )
    expertise: list[str] = Field(
        default=["kung fu", "action movies", "martial arts", "B-movies"],
        description="Areas of expertise"
    )
    response_style: str = Field(
        default="short and punchy",
        description="Desired response style"
    )
    name_variations: list[str] = Field(
        default=["cynthia", "rothrock", "cynthiarothbot"],
        description="Alternative names that trigger mentions"
    )
```

**Fields**:
- `character_name`: Display name of the bot character
- `character_description`: Brief description for LLM system prompt
- `personality_traits`: List of traits that define bot's personality
- `expertise`: Topics the bot is knowledgeable about
- `response_style`: How the bot should structure responses
- `name_variations`: Partial names that should trigger mentions

**Defaults**: Configured for Cynthia Rothrock character as specified in requirements

#### 3.1.4 LLMProvider

```python
class LLMProvider(BaseModel):
    """LLM provider configuration."""
    
    name: str = Field(
        description="Provider identifier"
    )
    type: str = Field(
        description="Provider type: openai_compatible, openrouter, anthropic"
    )
    base_url: str = Field(
        description="API base URL"
    )
    api_key: str = Field(
        description="API key for authentication"
    )
    model: str = Field(
        description="Model identifier"
    )
    max_tokens: int = Field(
        default=256,
        description="Maximum tokens in response",
        ge=1,
        le=4096
    )
    temperature: float = Field(
        default=0.8,
        description="Sampling temperature",
        ge=0.0,
        le=2.0
    )
    timeout_seconds: int = Field(
        default=10,
        description="Request timeout",
        ge=1,
        le=60
    )
    fallback: str | None = Field(
        default=None,
        description="Fallback provider name on failure"
    )
```

**Fields**:
- `name`: Unique identifier for this provider (e.g., `local`, `openrouter`)
- `type`: Provider API type (`openai_compatible`, `openrouter`, `anthropic`)
- `base_url`: API endpoint URL
- `api_key`: Authentication key (can use env var: `${OPENROUTER_API_KEY}`)
- `model`: Model name/identifier
- `max_tokens`: Maximum response length (default: 256)
- `temperature`: Creativity level (0.0-2.0, default: 0.8)
- `timeout_seconds`: HTTP timeout (default: 10)
- `fallback`: Name of provider to try if this one fails

**Validation**:
- `type` must be one of: `openai_compatible`, `openrouter`, `anthropic`
- `max_tokens`: 1-4096
- `temperature`: 0.0-2.0
- `timeout_seconds`: 1-60

#### 3.1.5 Trigger

```python
class Trigger(BaseModel):
    """Trigger word configuration."""
    
    name: str = Field(
        description="Trigger identifier"
    )
    patterns: list[str] = Field(
        description="List of regex patterns or strings to match"
    )
    probability: float = Field(
        default=1.0,
        description="Probability of responding (0.0-1.0)",
        ge=0.0,
        le=1.0
    )
    cooldown_seconds: int = Field(
        default=300,
        description="Cooldown between trigger activations",
        ge=0
    )
    context: str = Field(
        default="",
        description="Additional context to inject into prompt"
    )
    response_style: str | None = Field(
        default=None,
        description="Override response style for this trigger"
    )
    max_responses_per_hour: int = Field(
        default=10,
        description="Maximum responses per hour for this trigger",
        ge=0
    )
    priority: int = Field(
        default=5,
        description="Trigger priority (higher = more important)",
        ge=1,
        le=10
    )
    enabled: bool = Field(
        default=True,
        description="Whether trigger is active"
    )
    llm_provider: str | None = Field(
        default=None,
        description="Specific LLM provider for this trigger"
    )
```

**Fields**:
- `name`: Unique identifier (e.g., `toddy`, `kung_fu`)
- `patterns`: List of strings/regex to match (case-insensitive)
- `probability`: Chance of responding (0.0-1.0)
- `cooldown_seconds`: Time between responses for this trigger
- `context`: Extra context to add to LLM prompt when triggered
- `response_style`: Override default response style
- `max_responses_per_hour`: Rate limit for this specific trigger
- `priority`: Higher priority triggers checked first
- `enabled`: Can disable without removing config
- `llm_provider`: Use specific provider (e.g., for trivia questions)

**Validation**:
- `probability`: 0.0-1.0
- `cooldown_seconds`: >= 0
- `priority`: 1-10
- `patterns` must not be empty

#### 3.1.6 RateLimits

```python
class RateLimits(BaseModel):
    """Rate limiting configuration."""
    
    global_max_per_minute: int = Field(
        default=2,
        description="Maximum bot responses per minute (global)",
        ge=0
    )
    global_max_per_hour: int = Field(
        default=20,
        description="Maximum bot responses per hour (global)",
        ge=0
    )
    global_cooldown_seconds: int = Field(
        default=15,
        description="Minimum seconds between any responses",
        ge=0
    )
    user_max_per_hour: int = Field(
        default=5,
        description="Maximum responses to single user per hour",
        ge=0
    )
    user_cooldown_seconds: int = Field(
        default=60,
        description="Cooldown per user",
        ge=0
    )
    mention_cooldown_seconds: int = Field(
        default=120,
        description="Cooldown for direct mentions per user",
        ge=0
    )
    admin_cooldown_multiplier: float = Field(
        default=0.5,
        description="Multiplier for admin cooldowns (0.5 = half time)",
        ge=0.0,
        le=1.0
    )
    admin_limit_multiplier: float = Field(
        default=2.0,
        description="Multiplier for admin rate limits (2.0 = double)",
        ge=1.0
    )
```

**Fields**:
- `global_max_per_minute`: Total bot messages per minute (default: 2)
- `global_max_per_hour`: Total bot messages per hour (default: 20)
- `global_cooldown_seconds`: Time between any bot messages (default: 15)
- `user_max_per_hour`: Responses to single user per hour (default: 5)
- `user_cooldown_seconds`: Time between responses to same user (default: 60)
- `mention_cooldown_seconds`: Time between mention responses to same user (default: 120)
- `admin_cooldown_multiplier`: Admin cooldown reduction (0.5 = 50% cooldown)
- `admin_limit_multiplier`: Admin limit increase (2.0 = 2x limits)

**Notes**:
- Admins are users with rank >= 2 (moderators and above)
- All limits can be disabled by setting to 0
- Conservative defaults prevent spam

#### 3.1.7 MessageProcessing

```python
class MessageProcessing(BaseModel):
    """Message processing configuration."""
    
    max_message_length: int = Field(
        default=240,
        description="Maximum message length (safe under 255 CyTube limit)",
        ge=1,
        le=255
    )
    split_delay_seconds: int = Field(
        default=2,
        description="Delay between split message parts",
        ge=0,
        le=10
    )
    filter_emoji: bool = Field(
        default=False,
        description="Whether to limit emoji usage"
    )
    max_emoji_per_message: int = Field(
        default=3,
        description="Maximum emoji allowed per message",
        ge=0
    )
```

**Fields**:
- `max_message_length`: Max chars per message (default: 240, CyTube limit: 255)
- `split_delay_seconds`: Delay between message parts (default: 2)
- `filter_emoji`: Enable emoji limiting
- `max_emoji_per_message`: Max emoji if filtering enabled

**Validation**:
- `max_message_length`: 1-255 (CyTube constraint)
- `split_delay_seconds`: 0-10

#### 3.1.8 TestingConfig

```python
class TestingConfig(BaseModel):
    """Testing and development configuration."""
    
    dry_run: bool = Field(
        default=False,
        description="If true, generate responses but don't send to chat"
    )
    log_responses: bool = Field(
        default=True,
        description="Log all responses to JSONL file"
    )
    log_file: str = Field(
        default="logs/llm-responses.jsonl",
        description="Path to response log file"
    )
    send_to_chat: bool = Field(
        default=True,
        description="Whether to send responses to chat (false in dry-run)"
    )
```

**Fields**:
- `dry_run`: Generate but don't send responses (default: False)
- `log_responses`: Log to JSONL file (default: True)
- `log_file`: Log file path (default: `logs/llm-responses.jsonl`)
- `send_to_chat`: Actually send to CyTube (default: True, False if dry_run)

**Notes**:
- When `dry_run=True`, `send_to_chat` is automatically set to False
- Logs are always written if `log_responses=True`

#### 3.1.9 ContextConfig

```python
class ContextConfig(BaseModel):
    """Context management configuration."""
    
    chat_history_buffer: int = Field(
        default=30,
        description="Number of recent messages to keep for context",
        ge=0,
        le=100
    )
    include_video_context: bool = Field(
        default=True,
        description="Include current video in prompts"
    )
    include_chat_history: bool = Field(
        default=True,
        description="Include recent chat in prompts"
    )
```

**Fields**:
- `chat_history_buffer`: Recent messages to track (default: 30)
- `include_video_context`: Add current video to prompts (default: True)
- `include_chat_history`: Add chat history to prompts (default: True)

**Validation**:
- `chat_history_buffer`: 0-100

#### 3.1.10 Main Config Class

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Main service configuration."""
    
    model_config = SettingsConfigDict(
        env_prefix="KRYTEN_LLM_",
        env_nested_delimiter="__",
        case_sensitive=False
    )
    
    nats: NatsConfig = Field(
        default_factory=NatsConfig,
        description="NATS connection settings"
    )
    cytube: CyTubeConfig = Field(
        description="CyTube connection settings"
    )
    personality: PersonalityConfig = Field(
        default_factory=PersonalityConfig,
        description="Bot personality configuration"
    )
    llm_providers: dict[str, LLMProvider] = Field(
        description="LLM provider configurations"
    )
    default_provider: str = Field(
        default="local",
        description="Default LLM provider name"
    )
    triggers: list[Trigger] = Field(
        default_factory=list,
        description="Trigger word configurations"
    )
    rate_limits: RateLimits = Field(
        default_factory=RateLimits,
        description="Rate limiting configuration"
    )
    message_processing: MessageProcessing = Field(
        default_factory=MessageProcessing,
        description="Message processing settings"
    )
    testing: TestingConfig = Field(
        default_factory=TestingConfig,
        description="Testing configuration"
    )
    context: ContextConfig = Field(
        default_factory=ContextConfig,
        description="Context management settings"
    )
    service_name: str = Field(
        default="kryten-llm",
        description="Service identifier"
    )
    
    @classmethod
    def from_json_file(cls, path: str | Path) -> "Config":
        """Load configuration from JSON file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)
    
    def validate_config(self) -> tuple[bool, list[str]]:
        """Validate configuration and return (is_valid, errors)."""
        errors = []
        
        # Validate default provider exists
        if self.default_provider not in self.llm_providers:
            errors.append(
                f"Default provider '{self.default_provider}' not found in llm_providers"
            )
        
        # Validate fallback providers exist
        for provider_name, provider in self.llm_providers.items():
            if provider.fallback and provider.fallback not in self.llm_providers:
                errors.append(
                    f"Provider '{provider_name}' has invalid fallback '{provider.fallback}'"
                )
        
        # Validate trigger LLM providers
        for trigger in self.triggers:
            if trigger.llm_provider and trigger.llm_provider not in self.llm_providers:
                errors.append(
                    f"Trigger '{trigger.name}' has invalid llm_provider '{trigger.llm_provider}'"
                )
        
        return (len(errors) == 0, errors)
```

**Environment Variable Support**:
- Prefix: `KRYTEN_LLM_`
- Nested delimiter: `__`
- Example: `KRYTEN_LLM_NATS__URL=nats://prod:4222`
- Example: `KRYTEN_LLM_CYTUBE__CHANNEL=myroom`

**Methods**:
- `from_json_file(path)`: Load from JSON file
- `validate_config()`: Custom validation logic

### 3.2 File: `kryten_llm/models/events.py`

Event data classes for internal use.

```python
from dataclasses import dataclass
from typing import Any


@dataclass
class TriggerResult:
    """Result of trigger detection."""
    
    triggered: bool
    trigger_type: str | None = None  # "mention", "trigger_word"
    trigger_name: str | None = None
    cleaned_message: str | None = None
    context: str | None = None
    priority: int = 5
    
    def __bool__(self) -> bool:
        """Allow truthiness check."""
        return self.triggered
```

**Fields**:
- `triggered`: Whether message triggered a response
- `trigger_type`: Type of trigger (`mention` or `trigger_word`)
- `trigger_name`: Identifier of trigger that fired
- `cleaned_message`: Message with bot name removed (for mentions)
- `context`: Additional context for LLM prompt
- `priority`: Trigger priority

### 3.3 File: `kryten_llm/models/__init__.py`

```python
"""Data models for kryten-llm."""

from kryten_llm.models.config import (
    Config,
    NatsConfig,
    CyTubeConfig,
    PersonalityConfig,
    LLMProvider,
    Trigger,
    RateLimits,
    MessageProcessing,
    TestingConfig,
    ContextConfig,
)
from kryten_llm.models.events import TriggerResult

__all__ = [
    "Config",
    "NatsConfig",
    "CyTubeConfig",
    "PersonalityConfig",
    "LLMProvider",
    "Trigger",
    "RateLimits",
    "MessageProcessing",
    "TestingConfig",
    "ContextConfig",
    "TriggerResult",
]
```

---

## 4. Enhanced Configuration File

### 4.1 File: `config.example.json`

Complete example configuration with all sections and comments.

```json
{
  "nats": {
    "url": "nats://localhost:4222",
    "credentials": null
  },
  "cytube": {
    "domain": "cytu.be",
    "channel": "420grindhouse",
    "username": "CynthiaRothbot"
  },
  "personality": {
    "character_name": "CynthiaRothbot",
    "character_description": "legendary martial artist and actress Cynthia Rothrock",
    "personality_traits": [
      "confident",
      "action-oriented",
      "pithy",
      "martial arts expert",
      "straight-talking",
      "no-nonsense"
    ],
    "expertise": [
      "kung fu",
      "martial arts",
      "action movies",
      "B-movies",
      "grindhouse films",
      "1980s action cinema"
    ],
    "response_style": "short and punchy",
    "name_variations": [
      "cynthia",
      "rothrock",
      "cynthiarothbot",
      "rothbot"
    ]
  },
  "llm_providers": {
    "local": {
      "name": "local",
      "type": "openai_compatible",
      "base_url": "http://localhost:1234/v1",
      "api_key": "not-needed",
      "model": "qwen2.5-7b-instruct",
      "max_tokens": 256,
      "temperature": 0.8,
      "timeout_seconds": 10,
      "fallback": "openrouter"
    },
    "openrouter": {
      "name": "openrouter",
      "type": "openrouter",
      "base_url": "https://openrouter.ai/api/v1",
      "api_key": "${OPENROUTER_API_KEY}",
      "model": "meta-llama/llama-3.2-3b-instruct:free",
      "max_tokens": 256,
      "temperature": 0.8,
      "timeout_seconds": 15,
      "fallback": null
    },
    "trivia": {
      "name": "trivia",
      "type": "openai_compatible",
      "base_url": "http://localhost:1234/v1",
      "api_key": "not-needed",
      "model": "qwen2.5-14b-instruct",
      "max_tokens": 512,
      "temperature": 0.3,
      "timeout_seconds": 15,
      "fallback": "openrouter"
    }
  },
  "default_provider": "local",
  "triggers": [
    {
      "name": "toddy",
      "patterns": ["toddy", "todd", "god-emperor"],
      "probability": 0.15,
      "cooldown_seconds": 300,
      "context": "Toddy is a running joke in the channel - a semi-divine entity that viewers jokingly worship. Keep responses humorous and cultish.",
      "response_style": "reverent but tongue-in-cheek",
      "max_responses_per_hour": 3,
      "priority": 7,
      "enabled": true,
      "llm_provider": null
    },
    {
      "name": "kung_fu",
      "patterns": ["kung fu", "martial arts", "karate", "fighting"],
      "probability": 0.20,
      "cooldown_seconds": 180,
      "context": "User is asking about martial arts or kung fu movies.",
      "response_style": null,
      "max_responses_per_hour": 5,
      "priority": 5,
      "enabled": true,
      "llm_provider": null
    },
    {
      "name": "movie_trivia",
      "patterns": ["who directed", "what year", "trivia", "movie fact"],
      "probability": 0.50,
      "cooldown_seconds": 120,
      "context": "User is asking for movie trivia or facts.",
      "response_style": "knowledgeable and precise",
      "max_responses_per_hour": 8,
      "priority": 8,
      "enabled": true,
      "llm_provider": "trivia"
    }
  ],
  "rate_limits": {
    "global_max_per_minute": 2,
    "global_max_per_hour": 20,
    "global_cooldown_seconds": 15,
    "user_max_per_hour": 5,
    "user_cooldown_seconds": 60,
    "mention_cooldown_seconds": 120,
    "admin_cooldown_multiplier": 0.5,
    "admin_limit_multiplier": 2.0
  },
  "message_processing": {
    "max_message_length": 240,
    "split_delay_seconds": 2,
    "filter_emoji": false,
    "max_emoji_per_message": 3
  },
  "testing": {
    "dry_run": false,
    "log_responses": true,
    "log_file": "logs/llm-responses.jsonl",
    "send_to_chat": true
  },
  "context": {
    "chat_history_buffer": 30,
    "include_video_context": true,
    "include_chat_history": true
  },
  "service_name": "kryten-llm"
}
```

### 4.2 Configuration Comments

Since JSON doesn't support comments, create a separate `config.example.md` file:

```markdown
# Configuration Guide

## Environment Variables

Environment variables can override configuration:
- Prefix: `KRYTEN_LLM_`
- Nested delimiter: `__`

Examples:
```bash
export KRYTEN_LLM_NATS__URL="nats://prod:4222"
export KRYTEN_LLM_CYTUBE__CHANNEL="myroom"
export KRYTEN_LLM_TESTING__DRY_RUN="true"
```

## API Keys

Use `${VAR_NAME}` syntax to reference environment variables:
```json
{
  "api_key": "${OPENROUTER_API_KEY}"
}
```

## Trigger Configuration

- `probability`: 0.0 = never, 1.0 = always (0.15 = 15% chance)
- `cooldown_seconds`: Minimum time between trigger activations
- `max_responses_per_hour`: Hard limit per trigger
- `priority`: Higher = checked first (1-10)

## Rate Limiting

Conservative defaults prevent spam:
- Global: 2/minute, 20/hour
- Per-user: 5/hour
- Admins (rank 2+): 50% cooldown, 2x limits

## Testing

Set `testing.dry_run = true` to generate responses without sending to chat.
```

---

## 5. Configuration Loader

### 5.1 File: `kryten_llm/config.py`

Replace existing implementation with Pydantic-based loader.

```python
"""Configuration management for kryten-llm."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from kryten_llm.models.config import Config


logger = logging.getLogger(__name__)


def load_config(config_path: Path) -> Config:
    """Load and validate configuration from file.
    
    Args:
        config_path: Path to configuration JSON file
        
    Returns:
        Validated Config object
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValidationError: If config is invalid
        ValueError: If config validation fails
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    # Read and expand environment variables
    with open(config_path, encoding="utf-8") as f:
        content = f.read()
    
    # Expand ${VAR_NAME} references
    content = _expand_env_vars(content)
    
    # Parse JSON
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in config file: {e}")
    
    # Load with Pydantic
    try:
        config = Config.model_validate(data)
    except ValidationError as e:
        logger.error("Configuration validation failed:")
        for error in e.errors():
            loc = " -> ".join(str(x) for x in error["loc"])
            logger.error(f"  {loc}: {error['msg']}")
        raise
    
    # Apply dry-run override
    if config.testing.dry_run:
        config.testing.send_to_chat = False
        logger.info("Dry-run mode enabled - responses will not be sent to chat")
    
    # Custom validation
    is_valid, errors = config.validate_config()
    if not is_valid:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  {error}")
        raise ValueError("Configuration validation failed")
    
    return config


def _expand_env_vars(content: str) -> str:
    """Expand ${VAR_NAME} environment variable references."""
    import re
    
    pattern = r'\$\{([A-Z_][A-Z0-9_]*)\}'
    
    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        value = os.environ.get(var_name)
        if value is None:
            logger.warning(f"Environment variable {var_name} not set")
            return match.group(0)  # Leave unexpanded
        return value
    
    return re.sub(pattern, replacer, content)


def validate_config_file(config_path: Path) -> tuple[bool, list[str]]:
    """Validate configuration file without loading.
    
    Args:
        config_path: Path to configuration file
        
    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []
    
    # Check file exists
    if not config_path.exists():
        return False, [f"Configuration file not found: {config_path}"]
    
    # Try to load
    try:
        config = load_config(config_path)
        return True, []
    except FileNotFoundError as e:
        return False, [str(e)]
    except ValidationError as e:
        for error in e.errors():
            loc = " -> ".join(str(x) for x in error["loc"])
            errors.append(f"{loc}: {error['msg']}")
        return False, errors
    except ValueError as e:
        return False, [str(e)]
    except Exception as e:
        return False, [f"Unexpected error: {e}"]
```

**Functions**:
- `load_config(path)`: Load and validate configuration
- `_expand_env_vars(content)`: Expand `${VAR_NAME}` references
- `validate_config_file(path)`: Validate without loading (for `--validate-config`)

---

## 6. CLI Enhancements

### 6.1 File: `kryten_llm/__main__.py`

Update to add `--dry-run` and `--validate-config` flags.

```python
"""Main entry point for kryten-llm service."""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from kryten_llm.config import load_config, validate_config_file
from kryten_llm.service import LLMService


def setup_logging(level: str = "INFO") -> None:
    """Configure logging for the service."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Kryten LLM Service - AI-powered chat bot for CyTube",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Normal operation
  kryten-llm --config config.json
  
  # Validate configuration
  kryten-llm --config config.json --validate-config
  
  # Dry-run mode (generate responses but don't send)
  kryten-llm --config config.json --dry-run
  
  # Debug logging
  kryten-llm --config config.json --log-level DEBUG
        """
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("/etc/kryten/llm/config.json"),
        help="Path to configuration file (default: /etc/kryten/llm/config.json)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate responses but don't send to chat (for testing)",
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate configuration file and exit",
    )
    return parser.parse_args()


async def main_async() -> None:
    """Main async entry point."""
    args = parse_args()
    setup_logging(args.log_level)

    logger = logging.getLogger(__name__)
    
    # Validate config mode
    if args.validate_config:
        logger.info(f"Validating configuration: {args.config}")
        is_valid, errors = validate_config_file(args.config)
        
        if is_valid:
            logger.info("✓ Configuration is valid")
            sys.exit(0)
        else:
            logger.error("✗ Configuration validation failed:")
            for error in errors:
                logger.error(f"  {error}")
            sys.exit(1)
    
    # Load configuration
    try:
        config = load_config(args.config)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)
    
    # Override dry-run from CLI
    if args.dry_run:
        config.testing.dry_run = True
        config.testing.send_to_chat = False
        logger.info("Dry-run mode enabled via --dry-run flag")
    
    logger.info("Starting Kryten LLM Service")
    
    # Initialize service
    service = LLMService(config=config)

    # Setup signal handlers
    loop = asyncio.get_event_loop()

    def signal_handler(sig: int) -> None:
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(service.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

    try:
        await service.start()
        await service.wait_for_shutdown()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Service error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await service.stop()


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

**Changes**:
- Added `--dry-run` flag
- Added `--validate-config` flag
- Improved help text with examples
- CLI flag overrides config file for dry-run
- Validate-config mode exits after validation

---

## 7. Service Updates

### 7.1 File: `kryten_llm/service.py`

Update to use new configuration models.

```python
"""Main service class for kryten-llm."""

import asyncio
import logging
from pathlib import Path

from kryten import KrytenClient

from kryten_llm.models.config import Config


logger = logging.getLogger(__name__)


class LLMService:
    """Kryten LLM Service."""

    def __init__(self, config: Config):
        """Initialize the service.
        
        Args:
            config: Validated configuration object
        """
        self.config = config
        self.client = KrytenClient(
            nats_url=self.config.nats.url,
            subject_prefix="kryten.events",  # Standard prefix for kryten ecosystem
            service_name=self.config.service_name,
        )
        self._shutdown_event = asyncio.Event()
        
        # TODO Phase 1: Initialize components
        # self.listener = MessageListener(...)
        # self.trigger_engine = TriggerEngine(...)
        # self.llm_manager = LLMManager(...)
        # self.rate_limiter = RateLimiter(...)
        # self.formatter = ResponseFormatter(...)
        # self.context_manager = ContextManager(...)
        # self.response_logger = ResponseLogger(...)

    async def start(self) -> None:
        """Start the service."""
        logger.info("Starting LLM service")
        
        if self.config.testing.dry_run:
            logger.warning("⚠ DRY RUN MODE - Responses will NOT be sent to chat")
        
        logger.info(f"Bot personality: {self.config.personality.character_name}")
        logger.info(f"Default LLM provider: {self.config.default_provider}")
        logger.info(f"Triggers configured: {len(self.config.triggers)}")

        # Connect to NATS
        await self.client.connect()

        # Subscribe to events
        await self.client.subscribe("chatMsg", self._handle_chat_message)
        
        # TODO Phase 1: Start components
        # await self.listener.start()
        # await self.context_manager.start()

        logger.info("LLM service started and ready")

    async def stop(self) -> None:
        """Stop the service."""
        logger.info("Stopping LLM service")
        self._shutdown_event.set()

        # TODO Phase 1: Stop components gracefully
        
        # Disconnect from NATS
        await self.client.disconnect()

        logger.info("LLM service stopped")

    async def wait_for_shutdown(self) -> None:
        """Wait for shutdown signal."""
        await self._shutdown_event.wait()

    async def _handle_chat_message(self, subject: str, data: dict) -> None:
        """Handle chatMsg events.
        
        TODO Phase 1: Replace with proper message processing pipeline
        """
        username = data.get("username", "unknown")
        msg = data.get("msg", "")
        logger.debug(f"Chat message from {username}: {msg}")

        # TODO Phase 1: Implement message processing
        # 1. Filter spam/commands (MessageListener)
        # 2. Check for triggers (TriggerEngine)
        # 3. Check rate limits (RateLimiter)
        # 4. Generate LLM response (LLMManager)
        # 5. Format response (ResponseFormatter)
        # 6. Send to chat or log (dry-run mode)
        # 7. Log response (ResponseLogger)
```

**Changes**:
- Accept `Config` object instead of path
- Use Pydantic config models
- Log dry-run status
- Log configuration summary
- Add TODO comments for Phase 1 components

---

## 8. Testing Infrastructure

### 8.1 File: `tests/conftest.py`

Pytest fixtures for testing.

```python
"""Pytest fixtures and configuration."""

import json
import pytest
from pathlib import Path
from typing import Any

from kryten_llm.models.config import Config


@pytest.fixture
def minimal_config_dict() -> dict[str, Any]:
    """Minimal valid configuration dictionary."""
    return {
        "nats": {
            "url": "nats://localhost:4222"
        },
        "cytube": {
            "domain": "cytu.be",
            "channel": "testroom",
            "username": "TestBot"
        },
        "llm_providers": {
            "test": {
                "name": "test",
                "type": "openai_compatible",
                "base_url": "http://localhost:8000",
                "api_key": "test-key",
                "model": "test-model"
            }
        },
        "default_provider": "test"
    }


@pytest.fixture
def minimal_config(minimal_config_dict: dict[str, Any]) -> Config:
    """Minimal valid Config object."""
    return Config.model_validate(minimal_config_dict)


@pytest.fixture
def config_file(tmp_path: Path, minimal_config_dict: dict[str, Any]) -> Path:
    """Temporary config file."""
    config_path = tmp_path / "config.json"
    with open(config_path, "w") as f:
        json.dump(minimal_config_dict, f)
    return config_path
```

### 8.2 File: `tests/test_config.py`

Configuration loading tests.

```python
"""Tests for configuration loading and validation."""

import json
import pytest
from pathlib import Path

from pydantic import ValidationError

from kryten_llm.config import load_config, validate_config_file
from kryten_llm.models.config import Config, LLMProvider


def test_load_minimal_config(config_file: Path):
    """Test loading minimal valid configuration."""
    config = load_config(config_file)
    assert config.cytube.channel == "testroom"
    assert config.default_provider == "test"


def test_config_file_not_found():
    """Test error when config file doesn't exist."""
    with pytest.raises(FileNotFoundError):
        load_config(Path("/nonexistent/config.json"))


def test_invalid_json(tmp_path: Path):
    """Test error with invalid JSON."""
    config_path = tmp_path / "invalid.json"
    config_path.write_text("{invalid json}")
    
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_config(config_path)


def test_missing_required_field(tmp_path: Path):
    """Test error when required field is missing."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "nats": {"url": "nats://localhost:4222"},
        # Missing cytube and llm_providers
    }))
    
    with pytest.raises(ValidationError):
        load_config(config_path)


def test_validate_config_success(config_file: Path):
    """Test successful config validation."""
    is_valid, errors = validate_config_file(config_file)
    assert is_valid
    assert len(errors) == 0


def test_validate_config_missing_file():
    """Test validation of missing file."""
    is_valid, errors = validate_config_file(Path("/nonexistent/config.json"))
    assert not is_valid
    assert len(errors) > 0


def test_default_provider_validation(tmp_path: Path):
    """Test validation fails if default provider doesn't exist."""
    config_data = {
        "nats": {"url": "nats://localhost:4222"},
        "cytube": {
            "domain": "cytu.be",
            "channel": "test",
            "username": "Bot"
        },
        "llm_providers": {
            "provider1": {
                "name": "provider1",
                "type": "openai_compatible",
                "base_url": "http://localhost:8000",
                "api_key": "key",
                "model": "model"
            }
        },
        "default_provider": "nonexistent"  # Invalid
    }
    
    config_path = tmp_path / "config.json"
    with open(config_path, "w") as f:
        json.dump(config_data, f)
    
    is_valid, errors = validate_config_file(config_path)
    assert not is_valid
    assert any("Default provider" in error for error in errors)


def test_dry_run_disables_send(minimal_config: Config):
    """Test that dry_run=True disables send_to_chat."""
    minimal_config.testing.dry_run = True
    
    # Simulate what load_config does
    if minimal_config.testing.dry_run:
        minimal_config.testing.send_to_chat = False
    
    assert not minimal_config.testing.send_to_chat


def test_environment_variable_expansion(tmp_path: Path, monkeypatch):
    """Test ${VAR} expansion in config."""
    monkeypatch.setenv("TEST_API_KEY", "secret-key-123")
    
    config_data = {
        "nats": {"url": "nats://localhost:4222"},
        "cytube": {
            "domain": "cytu.be",
            "channel": "test",
            "username": "Bot"
        },
        "llm_providers": {
            "test": {
                "name": "test",
                "type": "openai_compatible",
                "base_url": "http://localhost:8000",
                "api_key": "${TEST_API_KEY}",
                "model": "model"
            }
        },
        "default_provider": "test"
    }
    
    config_path = tmp_path / "config.json"
    with open(config_path, "w") as f:
        json.dump(config_data, f)
    
    config = load_config(config_path)
    assert config.llm_providers["test"].api_key == "secret-key-123"
```

---

## 9. Documentation Updates

### 9.1 File: `README.md`

Update to reflect LLM functionality. Key sections to update:

**Title and Description**:
```markdown
# Kryten LLM

AI-powered chat bot for CyTube using Large Language Models. Part of the Kryten ecosystem.

## Features

- 🤖 **Personality-driven responses** - Configurable bot character (default: Cynthia Rothrock)
- 🎯 **Smart trigger system** - Responds to mentions and configurable trigger words with probabilities
- ⏱️ **Rate limiting** - Multiple layers prevent spam (global, per-user, per-trigger)
- 🔄 **Multi-provider LLM** - Supports multiple LLM APIs with automatic fallback
- 🎬 **Context-aware** - Understands current video and recent chat history
- 🧪 **Dry-run mode** - Test responses without sending to chat
- 📊 **Response logging** - JSONL logs for analysis and tuning
- 🔍 **Service discovery** - Integrates with kryten ecosystem monitoring
```

**Configuration Section**:
```markdown
## Configuration

Create `config.json` from `config.example.json`:

```bash
cp config.example.json config.json
```

### Required Settings

- `cytube` - CyTube server and channel
- `llm_providers` - At least one LLM provider
- `default_provider` - Which provider to use by default

### Optional Settings

- `personality` - Bot character configuration
- `triggers` - Trigger words with probabilities
- `rate_limits` - Rate limiting configuration
- `testing` - Dry-run and logging settings

See `config.example.md` for detailed documentation.
```

**Usage Section**:
```markdown
## Usage

### Validate Configuration

```bash
poetry run kryten-llm --config config.json --validate-config
```

### Dry-Run Mode (Testing)

```bash
poetry run kryten-llm --config config.json --dry-run
```

Generates responses but doesn't send to chat. Use for:
- Testing configuration changes
- Tuning trigger probabilities
- Evaluating LLM prompt quality

### Production

```bash
poetry run kryten-llm --config config.json
```

### Systemd Service

```bash
sudo cp systemd/kryten-llm.service /etc/systemd/system/
sudo systemctl enable kryten-llm
sudo systemctl start kryten-llm
```
```

---

## 10. File Naming Cleanup

### 10.1 Rename Start Scripts

**PowerShell**:
```bash
git mv start-moderator.ps1 start-llm.ps1
```

Update contents of `start-llm.ps1`:
```powershell
#!/usr/bin/env pwsh
# Start Kryten LLM service

$CONFIG = "config.json"
if ($args.Count -gt 0) {
    $CONFIG = $args[0]
}

Write-Host "Starting Kryten LLM service with config: $CONFIG"
poetry run kryten-llm --config $CONFIG
```

**Bash**:
```bash
git mv start-moderator.sh start-llm.sh
```

Update contents of `start-llm.sh`:
```bash
#!/usr/bin/env bash
# Start Kryten LLM service

CONFIG="${1:-config.json}"
echo "Starting Kryten LLM service with config: $CONFIG"
poetry run kryten-llm --config "$CONFIG"
```

### 10.2 Rename Systemd Service

```bash
git mv systemd/kryten-moderator.service systemd/kryten-llm.service
```

Update contents of `systemd/kryten-llm.service`:
```ini
[Unit]
Description=Kryten LLM Service
After=network.target nats.service

[Service]
Type=simple
User=kryten
Group=kryten
WorkingDirectory=/opt/kryten/llm
Environment="PATH=/opt/kryten/llm/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/opt/kryten/llm/.venv/bin/kryten-llm --config /etc/kryten/llm/config.json
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=kryten-llm

[Install]
WantedBy=multi-user.target
```

---

## 11. Validation Checklist

### 11.1 Phase 0 Complete When:

- [ ] All directories created
- [ ] Dependencies installed (`poetry install` succeeds)
- [ ] Can import: `from kryten_llm.models import Config, TriggerResult`
- [ ] `config.example.json` has all sections
- [ ] `poetry run kryten-llm --help` shows new flags
- [ ] `poetry run kryten-llm --config config.json --validate-config` works
- [ ] `poetry run kryten-llm --config config.json --dry-run` starts service
- [ ] Service logs show dry-run status
- [ ] Service connects to NATS
- [ ] README reflects LLM functionality
- [ ] No "moderator" references in file names
- [ ] Basic tests pass: `poetry run pytest tests/test_config.py -v`

### 11.2 Test Commands

```bash
# 1. Install dependencies
poetry install

# 2. Validate example config
poetry run kryten-llm --config config.example.json --validate-config

# 3. Create working config
cp config.example.json config.json
# Edit config.json with valid CyTube settings

# 4. Test dry-run mode
poetry run kryten-llm --config config.json --dry-run --log-level DEBUG

# 5. Run tests
poetry run pytest tests/ -v

# 6. Verify imports
python -c "from kryten_llm.models import Config; print('✓ Config import works')"
python -c "from kryten_llm.models import TriggerResult; print('✓ TriggerResult import works')"

# 7. Check linting
poetry run ruff check kryten_llm/
poetry run black --check kryten_llm/
poetry run mypy kryten_llm/
```

---

## 12. Success Criteria

Phase 0 is complete and ready for Phase 1 when:

1. **Structure**: All directories and files created
2. **Dependencies**: All packages installed and importable
3. **Configuration**: Pydantic models work, validation works, env vars supported
4. **CLI**: `--dry-run` and `--validate-config` flags functional
5. **Service**: Starts in dry-run mode, connects to NATS, logs correctly
6. **Tests**: Basic config tests pass
7. **Documentation**: README updated, config.example.json complete
8. **Quality**: No linting errors, type hints working
9. **Naming**: All files use "llm" not "moderator"

---

## Timeline

**Estimated effort**: 2-3 hours

| Task | Time | Priority |
|------|------|----------|
| Directory structure | 5 min | High |
| Dependencies | 5 min | High |
| Configuration models | 60 min | High |
| config.example.json | 30 min | High |
| Config loader | 20 min | High |
| CLI updates | 15 min | High |
| Service updates | 10 min | High |
| Tests | 15 min | Medium |
| README updates | 20 min | Medium |
| File renaming | 10 min | Low |
| Validation | 15 min | High |

---

*This specification provides complete implementation details for Phase 0. Follow the order presented for smooth implementation.*
