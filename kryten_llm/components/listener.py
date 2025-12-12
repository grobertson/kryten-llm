"""Message listener and filter for chat messages."""

import logging
from typing import Optional

from kryten_llm.models.config import LLMConfig

logger = logging.getLogger(__name__)


class MessageListener:
    """Filters and validates incoming chat messages.

    Implements REQ-001, REQ-002, REQ-003 from Phase 1 specification:
    - Filter spam messages (commands starting with !, /, .)
    - Filter system users ([server], [bot], [system])
    - Validate required fields (username, msg, time)
    """

    # System usernames to ignore
    SYSTEM_USERS = {"[server]", "[bot]", "[system]"}

    # Command prefixes to filter
    COMMAND_PREFIXES = ("!", "/", ".")

    def __init__(self, config: LLMConfig):
        """Initialize with configuration.

        Args:
            config: LLM configuration containing filtering rules
        """
        self.config = config
        logger.info("MessageListener initialized")

    async def filter_message(self, data: dict) -> Optional[dict]:
        """Filter and validate a chatMsg event.

        Implements filtering logic per specification:
        1. Check required fields exist
        2. Filter spam/command messages
        3. Filter system users

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
        # REQ-003: Validate required fields
        required_fields = ["username", "msg", "time"]
        for field in required_fields:
            if field not in data:
                logger.debug(f"Invalid message format: missing required field '{field}'")
                return None

        username = data["username"]
        msg = data["msg"]

        # REQ-002: Filter system users
        if username in self.SYSTEM_USERS:
            logger.debug(f"Filtered system user message from: {username}")
            return None

        # REQ-001: Filter spam messages (commands)
        if msg.startswith(self.COMMAND_PREFIXES):
            logger.debug(f"Filtered command message: {msg[:20]}...")
            return None

        # Message passed all filters
        logger.debug(f"Accepted message from {username}: {msg[:50]}...")
        return data
