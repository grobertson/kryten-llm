"""Configuration management for kryten-llm."""

import json
from pathlib import Path
from typing import Any


class Config:
    """Service configuration."""

    def __init__(self, config_path: Path):
        """Initialize configuration from file."""
        self.config_path = config_path
        self._config: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load configuration from file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, encoding="utf-8") as f:
            self._config = json.load(f)

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self._config.get(key, default)

    @property
    def nats_url(self) -> str:
        """Get NATS server URL."""
        return self.get("nats_url", "nats://localhost:4222")

    @property
    def nats_subject_prefix(self) -> str:
        """Get NATS subject prefix."""
        return self.get("nats_subject_prefix", "cytube")

    @property
    def service_name(self) -> str:
        """Get service name."""
        return self.get("service_name", "kryten-llm")
