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
    assert len(errors) > 0
    # Check if any error contains the default provider message
    error_text = " ".join(errors)
    assert "nonexistent" in error_text and "llm_providers" in error_text
