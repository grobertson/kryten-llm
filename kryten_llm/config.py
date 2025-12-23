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
        config: LLMConfig = LLMConfig.from_json(str(config_path))  # type: ignore[no-any-return]
    except ValidationError as e:
        logger.error("Configuration validation failed:")
        for err in e.errors():
            loc = " -> ".join(str(x) for x in err["loc"])
            logger.error(f"  {loc}: {err['msg']}")
        raise

    # Override version from package to ensure it stays in sync
    from kryten_llm import __version__
    config.service_metadata.service_version = __version__
    logger.info(f"Service version: {__version__}")

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
        # Create exception with all error messages
        error_msg = "Configuration validation failed:\n" + "\n".join(f"  {e}" for e in errors)
        raise ValueError(error_msg)

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
        _config = load_config(config_path)
        return True, []
    except FileNotFoundError as e:
        return False, [str(e)]
    except ValidationError as e:
        for error in e.errors():
            loc = " -> ".join(str(x) for x in error["loc"])
            errors.append(f"{loc}: {error['msg']}")
        return False, errors
    except ValueError as e:
        # Parse the error message to extract individual errors
        error_str = str(e)
        if "Configuration validation failed:" in error_str:
            # Split by newlines and filter out the header
            error_lines = error_str.split("\n")[1:]  # Skip first line
            return False, [line.strip() for line in error_lines if line.strip()]
        return False, [error_str]
    except Exception as e:
        return False, [f"Unexpected error: {e}"]
