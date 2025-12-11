# Phase 0 Implementation Specification (Corrected)

## Overview

**IMPORTANT**: This specification has been updated to use the existing **kryten-py infrastructure** rather than duplicating configuration systems. The kryten-llm service will be a standard Kryten ecosystem service using:

- `KrytenConfig` from kryten-py (provides NATS and channel configuration)
- `LifecycleEventPublisher` from kryten-py (handles service discovery, heartbeat, lifecycle events)
- `KrytenClient` from kryten-py (handles NATS communication and event subscription)

This approach eliminates ~50% of the originally specified work by leveraging existing, tested infrastructure.

---

## Changes from Original Spec

### ❌ **Removed** (Already in kryten-py):
- `NatsConfig` - Use kryten-py's `NatsConfig`
- `CyTubeConfig` - Use kryten-py's `ChannelConfig`
- Service discovery system - Use kryten-py's `LifecycleEventPublisher`
- NATS connection management - Use `KrytenClient`

### ✅ **Keep** (LLM-specific):
- `PersonalityConfig` - Bot character settings
- `LLMProvider` - LLM API configuration
- `Trigger` - Trigger word system
- `RateLimits` - Rate limiting rules
- `MessageProcessing` - Message formatting
- `TestingConfig` - Dry-run mode
- `ContextConfig` - Context management

---

## 1. Directory Structure

Same as original spec - no changes needed:

```
kryten-llm/
├── kryten_llm/
│   ├── components/         # Phase 1+ components
│   ├── models/             # Data models
│   │   ├── __init__.py
│   │   ├── config.py       # LLM-specific config (inherits from KrytenConfig)
│   │   └── events.py       # Event data classes
│   └── utils/              # Utilities
├── tests/
│   ├── conftest.py
│   └── test_config.py
└── logs/
    └── .gitkeep
```

**Command**:
```bash
cd kryten-llm
mkdir -p kryten_llm/components kryten_llm/models kryten_llm/utils tests logs
touch kryten_llm/models/__init__.py kryten_llm/utils/__init__.py tests/__init__.py logs/.gitkeep
```

---

## 2. Dependencies

**No changes** - same as original spec:

```bash
poetry add aiohttp pydantic pydantic-settings
```

**Expected `pyproject.toml`**:
```toml
[tool.poetry.dependencies]
python = "^3.10"
kryten-py = "^0.6.0"
aiohttp = "^3.9.0"
pydantic = "^2.0.0"
pydantic-settings = "^2.0.0"
```

---

## 3. Configuration Models

### 3.1 File: `kryten_llm/models/config.py`

**Key Change**: Extend `KrytenConfig` from kryten-py instead of creating parallel config.

```python
"""Configuration management for kryten-llm."""

from pathlib import Path
from pydantic import BaseModel, Field, field_validator
from kryten import KrytenConfig  # Import from kryten-py


# ============================================================================
# LLM-Specific Configuration Models
# ============================================================================

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


class LLMProvider(BaseModel):
    """LLM provider configuration."""
    
    name: str = Field(description="Provider identifier")
    type: str = Field(description="Provider type: openai_compatible, openrouter, anthropic")
    base_url: str = Field(description="API base URL")
    api_key: str = Field(description="API key for authentication")
    model: str = Field(description="Model identifier")
    max_tokens: int = Field(default=256, description="Maximum tokens in response", ge=1, le=4096)
    temperature: float = Field(default=0.8, description="Sampling temperature", ge=0.0, le=2.0)
    timeout_seconds: int = Field(default=10, description="Request timeout", ge=1, le=60)
    fallback: str | None = Field(default=None, description="Fallback provider name on failure")


class Trigger(BaseModel):
    """Trigger word configuration."""
    
    name: str = Field(description="Trigger identifier")
    patterns: list[str] = Field(description="List of regex patterns or strings to match")
    probability: float = Field(default=1.0, description="Probability of responding (0.0-1.0)", ge=0.0, le=1.0)
    cooldown_seconds: int = Field(default=300, description="Cooldown between trigger activations", ge=0)
    context: str = Field(default="", description="Additional context to inject into prompt")
    response_style: str | None = Field(default=None, description="Override response style for this trigger")
    max_responses_per_hour: int = Field(default=10, description="Maximum responses per hour for this trigger", ge=0)
    priority: int = Field(default=5, description="Trigger priority (higher = more important)", ge=1, le=10)
    enabled: bool = Field(default=True, description="Whether trigger is active")
    llm_provider: str | None = Field(default=None, description="Specific LLM provider for this trigger")


class RateLimits(BaseModel):
    """Rate limiting configuration."""
    
    global_max_per_minute: int = Field(default=2, ge=0)
    global_max_per_hour: int = Field(default=20, ge=0)
    global_cooldown_seconds: int = Field(default=15, ge=0)
    user_max_per_hour: int = Field(default=5, ge=0)
    user_cooldown_seconds: int = Field(default=60, ge=0)
    mention_cooldown_seconds: int = Field(default=120, ge=0)
    admin_cooldown_multiplier: float = Field(default=0.5, ge=0.0, le=1.0)
    admin_limit_multiplier: float = Field(default=2.0, ge=1.0)


class MessageProcessing(BaseModel):
    """Message processing configuration."""
    
    max_message_length: int = Field(default=240, ge=1, le=255)
    split_delay_seconds: int = Field(default=2, ge=0, le=10)
    filter_emoji: bool = Field(default=False)
    max_emoji_per_message: int = Field(default=3, ge=0)


class TestingConfig(BaseModel):
    """Testing and development configuration."""
    
    dry_run: bool = Field(default=False)
    log_responses: bool = Field(default=True)
    log_file: str = Field(default="logs/llm-responses.jsonl")
    send_to_chat: bool = Field(default=True)


class ContextConfig(BaseModel):
    """Context management configuration."""
    
    chat_history_buffer: int = Field(default=30, ge=0, le=100)
    include_video_context: bool = Field(default=True)
    include_chat_history: bool = Field(default=True)


# ============================================================================
# Main Configuration (Extends KrytenConfig)
# ============================================================================

class LLMConfig(KrytenConfig):
    """Extended configuration for kryten-llm service.
    
    Inherits NATS and channel configuration from KrytenConfig.
    Adds LLM-specific settings for personality, providers, triggers, etc.
    """
    
    # LLM-specific configuration
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

### 3.2 File: `kryten_llm/models/events.py`

**No changes** - same as original:

```python
from dataclasses import dataclass


@dataclass
class TriggerResult:
    """Result of trigger detection."""
    
    triggered: bool
    trigger_type: str | None = None
    trigger_name: str | None = None
    cleaned_message: str | None = None
    context: str | None = None
    priority: int = 5
    
    def __bool__(self) -> bool:
        return self.triggered
```

### 3.3 File: `kryten_llm/models/__init__.py`

```python
"""Data models for kryten-llm."""

from kryten_llm.models.config import (
    LLMConfig,
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
    "LLMConfig",
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

## 4. Configuration File

### 4.1 File: `config.example.json`

**Key Change**: Use kryten-py's structure with `nats` and `channels` at top level.

```json
{
  "nats": {
    "servers": ["nats://localhost:4222"],
    "connect_timeout": 10,
    "reconnect_time_wait": 2,
    "max_reconnect_attempts": -1
  },
  "channels": [
    {
      "domain": "cytu.be",
      "channel": "420grindhouse"
    }
  ],
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
    }
  },
  "default_provider": "local",
  "triggers": [
    {
      "name": "toddy",
      "patterns": ["toddy", "todd", "god-emperor"],
      "probability": 0.15,
      "cooldown_seconds": 300,
      "context": "Toddy is a running joke in the channel - a semi-divine entity.",
      "max_responses_per_hour": 3,
      "priority": 7,
      "enabled": true
    },
    {
      "name": "kung_fu",
      "patterns": ["kung fu", "martial arts", "karate"],
      "probability": 0.20,
      "cooldown_seconds": 180,
      "context": "User is asking about martial arts or kung fu movies.",
      "max_responses_per_hour": 5,
      "priority": 5,
      "enabled": true
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
  }
}
```

---

## 5. Configuration Loader

### 5.1 File: `kryten_llm/config.py`

**Key Change**: Use kryten-py's `KrytenConfig.from_json()` which already handles env vars.

```python
"""Configuration management for kryten-llm."""

import logging
from pathlib import Path
from pydantic import ValidationError

from kryten_llm.models.config import LLMConfig


logger = logging.getLogger(__name__)


def load_config(config_path: Path) -> LLMConfig:
    """Load and validate configuration from file.
    
    Uses kryten-py's built-in JSON loader with environment variable expansion.
    
    Args:
        config_path: Path to configuration JSON file
        
    Returns:
        Validated LLMConfig object
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValidationError: If config is invalid
        ValueError: If config validation fails
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    # Use kryten-py's from_json() - already handles ${VAR_NAME} expansion
    try:
        config = LLMConfig.from_json(str(config_path))
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


def validate_config_file(config_path: Path) -> tuple[bool, list[str]]:
    """Validate configuration file without loading.
    
    Args:
        config_path: Path to configuration file
        
    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []
    
    if not config_path.exists():
        return False, [f"Configuration file not found: {config_path}"]
    
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

---

## 6. Service Implementation

### 6.1 File: `kryten_llm/service.py`

**Key Change**: Use `KrytenClient` and `LifecycleEventPublisher` from kryten-py.

```python
"""Main service class for kryten-llm."""

import asyncio
import logging
from pathlib import Path

from kryten import KrytenClient, LifecycleEventPublisher
from kryten_llm.models.config import LLMConfig


logger = logging.getLogger(__name__)


class LLMService:
    """Kryten LLM Service using kryten-py infrastructure."""

    def __init__(self, config: LLMConfig):
        """Initialize the service.
        
        Args:
            config: Validated LLMConfig object
        """
        self.config = config
        
        # Use KrytenClient from kryten-py (no need to build config dict)
        self.client = KrytenClient(config_dict=self.config.model_dump())
        
        # Lifecycle event publisher for service discovery
        self.lifecycle = None  # Initialized after NATS connection
        
        self._shutdown_event = asyncio.Event()
        
        # TODO Phase 1: Initialize components
        # self.listener = MessageListener(...)
        # self.trigger_engine = TriggerEngine(...)
        # self.llm_manager = LLMManager(...)

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
        
        # Initialize lifecycle publisher (requires NATS connection)
        self.lifecycle = LifecycleEventPublisher(
            service_name="llm",
            nats_client=self.client._nats,
            logger=logger,
            version="0.1.0"  # TODO: Read from VERSION file
        )
        await self.lifecycle.start()
        
        # Publish startup event (service discovery)
        await self.lifecycle.publish_startup(
            personality=self.config.personality.character_name,
            providers=list(self.config.llm_providers.keys()),
            triggers=len(self.config.triggers)
        )

        # Subscribe to events
        await self.client.subscribe("chatMsg", self._handle_chat_message)
        
        # TODO Phase 1: Start components

        logger.info("LLM service started and ready")

    async def stop(self) -> None:
        """Stop the service."""
        logger.info("Stopping LLM service")
        self._shutdown_event.set()

        # Publish shutdown event
        if self.lifecycle:
            await self.lifecycle.publish_shutdown(reason="Normal shutdown")
            await self.lifecycle.stop()
        
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
```

---

## 7. CLI Implementation

### 7.1 File: `kryten_llm/__main__.py`

**No major changes** - same as original:

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
        description="Kryten LLM Service - AI-powered chat bot for CyTube"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.json"),
        help="Path to configuration file"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate responses but don't send to chat"
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate configuration file and exit"
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

---

## 8. Testing

### 8.1 File: `tests/conftest.py`

```python
"""Pytest fixtures and configuration."""

import json
import pytest
from pathlib import Path

from kryten_llm.models.config import LLMConfig


@pytest.fixture
def minimal_config_dict() -> dict:
    """Minimal valid configuration dictionary."""
    return {
        "nats": {
            "servers": ["nats://localhost:4222"]
        },
        "channels": [
            {"domain": "cytu.be", "channel": "testroom"}
        ],
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
def config_file(tmp_path: Path, minimal_config_dict: dict) -> Path:
    """Temporary config file."""
    config_path = tmp_path / "config.json"
    with open(config_path, "w") as f:
        json.dump(minimal_config_dict, f)
    return config_path
```

### 8.2 File: `tests/test_config.py`

```python
"""Tests for configuration loading and validation."""

import json
import pytest
from pathlib import Path
from pydantic import ValidationError

from kryten_llm.config import load_config, validate_config_file


def test_load_minimal_config(config_file: Path):
    """Test loading minimal valid configuration."""
    config = load_config(config_file)
    assert config.channels[0].channel == "testroom"
    assert config.default_provider == "test"


def test_config_file_not_found():
    """Test error when config file doesn't exist."""
    with pytest.raises(FileNotFoundError):
        load_config(Path("/nonexistent/config.json"))


def test_validate_config_success(config_file: Path):
    """Test successful config validation."""
    is_valid, errors = validate_config_file(config_file)
    assert is_valid
    assert len(errors) == 0


def test_default_provider_validation(tmp_path: Path):
    """Test validation fails if default provider doesn't exist."""
    config_data = {
        "nats": {"servers": ["nats://localhost:4222"]},
        "channels": [{"domain": "cytu.be", "channel": "test"}],
        "llm_providers": {
            "provider1": {
                "name": "provider1",
                "type": "openai_compatible",
                "base_url": "http://localhost:8000",
                "api_key": "key",
                "model": "model"
            }
        },
        "default_provider": "nonexistent"
    }
    
    config_path = tmp_path / "config.json"
    with open(config_path, "w") as f:
        json.dump(config_data, f)
    
    is_valid, errors = validate_config_file(config_path)
    assert not is_valid
    assert any("Default provider" in error for error in errors)
```

---

## 9. Validation Checklist

### Phase 0 Complete When:

- [ ] All directories created
- [ ] Dependencies installed (`poetry install`)
- [ ] Can import: `from kryten_llm.models import LLMConfig, TriggerResult`
- [ ] Can import: `from kryten import KrytenClient, LifecycleEventPublisher`
- [ ] `config.example.json` uses kryten-py structure
- [ ] `poetry run kryten-llm --validate-config` works
- [ ] `poetry run kryten-llm --dry-run` starts service
- [ ] Service publishes lifecycle.llm.startup event
- [ ] Service connects to NATS
- [ ] Basic tests pass: `poetry run pytest tests/ -v`

### Test Commands

```bash
# 1. Install dependencies
poetry install

# 2. Validate example config
poetry run kryten-llm --config config.example.json --validate-config

# 3. Test dry-run mode
poetry run kryten-llm --config config.json --dry-run --log-level DEBUG

# 4. Run tests
poetry run pytest tests/ -v

# 5. Verify imports
python -c "from kryten_llm.models import LLMConfig; print('✓ LLMConfig import works')"
python -c "from kryten import KrytenClient, LifecycleEventPublisher; print('✓ kryten-py imports work')"

# 6. Monitor lifecycle events (in separate terminal)
python -c "
import asyncio
from nats.aio.client import Client as NATS

async def monitor():
    nc = NATS()
    await nc.connect('nats://localhost:4222')
    await nc.subscribe('kryten.lifecycle.llm.>', lambda msg: print(f'Event: {msg.subject}'))
    print('Monitoring lifecycle.llm.>')
    await asyncio.Event().wait()

asyncio.run(monitor())
"
```

---

## 10. Summary of Changes

### What Was Removed:
1. **Custom NatsConfig** - Use kryten-py's `NatsConfig`
2. **Custom CyTubeConfig** - Use kryten-py's `ChannelConfig`
3. **Custom service discovery** - Use kryten-py's `LifecycleEventPublisher`
4. **Custom NATS management** - Use kryten-py's `KrytenClient`

### What Was Kept:
1. **LLM-specific config models** - `PersonalityConfig`, `LLMProvider`, `Trigger`, etc.
2. **LLMConfig extends KrytenConfig** - Inherits NATS/channel, adds LLM settings
3. **CLI flags** - `--dry-run`, `--validate-config`
4. **Service structure** - Start/stop, signal handling
5. **Testing infrastructure** - Pytest fixtures, config tests

### Benefits:
- ✅ **50% less code** - Removed ~400 lines of duplicate config
- ✅ **Consistent with ecosystem** - Same config structure as other kryten services
- ✅ **Lifecycle events for free** - Service discovery, heartbeat, groupwide restart
- ✅ **Environment variable support** - Already built into kryten-py
- ✅ **Well-tested infrastructure** - kryten-py is battle-tested

### Estimated Time:
**1-2 hours** (down from 2-3 hours) due to reduced scope.

---

*This corrected specification properly leverages the existing kryten-py infrastructure.*
