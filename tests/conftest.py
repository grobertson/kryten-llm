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


# Phase 1 Test Fixtures

@pytest.fixture
def sample_chat_message() -> dict:
    """Valid chat message for testing."""
    return {
        "username": "testuser",
        "msg": "hey cynthia, how are you?",
        "time": 1640000000,
        "meta": {"rank": 1}
    }


@pytest.fixture
def spam_message() -> dict:
    """Spam message for filtering tests."""
    return {
        "username": "testuser",
        "msg": "!skip",
        "time": 1640000000,
        "meta": {"rank": 1}
    }


@pytest.fixture
def system_message() -> dict:
    """System message for filtering tests."""
    return {
        "username": "[server]",
        "msg": "Server announcement",
        "time": 1640000000,
        "meta": {"rank": 0}
    }


@pytest.fixture
def llm_config() -> LLMConfig:
    """Full LLM configuration for testing."""
    config_dict = {
        "nats": {
            "servers": ["nats://localhost:4222"]
        },
        "channels": [
            {"domain": "cytu.be", "channel": "testroom"}
        ],
        "personality": {
            "character_name": "CynthiaRothbot",
            "character_description": "legendary martial artist",
            "personality_traits": ["confident", "action-oriented"],
            "expertise": ["kung fu", "action movies"],
            "response_style": "short and punchy",
            "name_variations": ["cynthia", "rothrock", "cynthiarothbot"]
        },
        "llm_providers": {
            "test": {
                "name": "test",
                "type": "openai_compatible",
                "base_url": "http://localhost:8000",
                "api_key": "test-key",
                "model": "test-model",
                "max_tokens": 256,
                "temperature": 0.8,
                "timeout_seconds": 10
            }
        },
        "default_provider": "test",
        "triggers": [],
        "rate_limits": {},
        "message_processing": {
            "max_message_length": 240,
            "split_delay_seconds": 2,
            "filter_emoji": False
        },
        "testing": {
            "dry_run": False,
            "log_responses": True
        },
        "context": {
            "chat_history_buffer": 30,
            "include_video_context": True,
            "include_chat_history": True
        }
    }
    return LLMConfig(**config_dict)


# Phase 2 Test Fixtures

@pytest.fixture
def trigger_word_message() -> dict:
    """Message with trigger word for testing."""
    return {
        "username": "testuser",
        "msg": "praise toddy!",
        "time": 1640000000,
        "meta": {"rank": 1}
    }


@pytest.fixture
def admin_message() -> dict:
    """Message from admin user."""
    return {
        "username": "admin",
        "msg": "hey cynthia help",
        "time": 1640000000,
        "meta": {"rank": 3}
    }


@pytest.fixture
def llm_config_with_triggers() -> LLMConfig:
    """LLM configuration with trigger words for Phase 2 testing."""
    config_dict = {
        "nats": {
            "servers": ["nats://localhost:4222"]
        },
        "channels": [
            {"domain": "cytu.be", "channel": "testroom"}
        ],
        "personality": {
            "character_name": "CynthiaRothbot",
            "character_description": "legendary martial artist",
            "personality_traits": ["confident", "action-oriented"],
            "expertise": ["kung fu", "action movies"],
            "response_style": "short and punchy",
            "name_variations": ["cynthia", "rothrock", "cynthiarothbot"]
        },
        "llm_providers": {
            "test": {
                "name": "test",
                "type": "openai_compatible",
                "base_url": "http://localhost:8000",
                "api_key": "test-key",
                "model": "test-model",
                "max_tokens": 256,
                "temperature": 0.8,
                "timeout_seconds": 10
            }
        },
        "default_provider": "test",
        "triggers": [
            {
                "name": "toddy",
                "patterns": ["toddy", "robert z'dar"],
                "probability": 1.0,
                "cooldown_seconds": 300,
                "context": "Respond enthusiastically about Robert Z'Dar",
                "max_responses_per_hour": 10,
                "priority": 8,
                "enabled": True
            },
            {
                "name": "kung_fu",
                "patterns": ["kung fu", "martial arts"],
                "probability": 0.3,
                "cooldown_seconds": 600,
                "context": "Discuss martial arts philosophy briefly",
                "max_responses_per_hour": 5,
                "priority": 5,
                "enabled": True
            },
            {
                "name": "movie",
                "patterns": ["movie", "film"],
                "probability": 0.1,
                "cooldown_seconds": 900,
                "context": "",
                "max_responses_per_hour": 3,
                "priority": 3,
                "enabled": True
            },
            {
                "name": "never_trigger",
                "patterns": ["never"],
                "probability": 0.0,
                "cooldown_seconds": 60,
                "context": "",
                "max_responses_per_hour": 1,
                "priority": 1,
                "enabled": True
            },
            {
                "name": "disabled",
                "patterns": ["disabled"],
                "probability": 1.0,
                "cooldown_seconds": 60,
                "context": "",
                "max_responses_per_hour": 1,
                "priority": 1,
                "enabled": False
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
            "filter_emoji": False
        },
        "testing": {
            "dry_run": False,
            "log_responses": True,
            "log_file": "logs/llm-responses.jsonl"
        },
        "context": {
            "chat_history_buffer": 30,
            "include_video_context": True,
            "include_chat_history": True
        }
    }
    return LLMConfig(**config_dict)
