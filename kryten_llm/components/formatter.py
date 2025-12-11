"""Response formatter for chat output."""

import logging
import re

from kryten_llm.models.config import LLMConfig


logger = logging.getLogger(__name__)


class ResponseFormatter:
    """Formats LLM responses for chat output.
    
    Implements REQ-014 through REQ-017 from Phase 1 specification:
    - Limit response length to max_message_length
    - Split long responses into multiple messages
    - Respect split_delay_seconds between parts
    - Remove common LLM artifacts (self-references)
    
    Phase 1: Basic length-based splitting
    Phase 4: Intelligent sentence-aware splitting
    """

    def __init__(self, config: LLMConfig):
        """Initialize with configuration.
        
        Args:
            config: LLM configuration containing message processing settings
        """
        self.config = config
        self.max_length = config.message_processing.max_message_length
        self.character_name = config.personality.character_name
        
        logger.info(
            f"ResponseFormatter initialized: max_length={self.max_length}, "
            f"character={self.character_name}"
        )

    async def format_response(self, response: str) -> list[str]:
        """Format LLM response for chat.
        
        Implements formatting rules from specification:
        1. Remove leading/trailing whitespace
        2. Remove self-references
        3. Split if needed (length-based in Phase 1)
        
        Args:
            response: Raw LLM response text
            
        Returns:
            List of formatted message parts (split if needed)
        """
        if not response:
            logger.warning("Empty response received")
            return []
        
        # Step 1: Remove leading/trailing whitespace
        formatted = response.strip()
        
        # Check if empty after stripping
        if not formatted:
            logger.warning("Response empty after stripping whitespace")
            return []
        
        # Step 2: REQ-017: Remove self-references
        formatted = self._remove_self_references(formatted)
        
        # Step 3: REQ-014, REQ-015: Check length and split if needed
        if len(formatted) <= self.max_length:
            logger.debug(f"Response fits in single message ({len(formatted)} chars)")
            return [formatted]
        
        # Split into multiple parts
        parts = self._split_response(formatted)
        logger.info(f"Response split into {len(parts)} parts")
        
        return parts

    def _remove_self_references(self, text: str) -> str:
        """Remove common LLM self-reference patterns.
        
        Removes patterns like:
        - "As {character_name}, "
        - "As {character_name} I "
        
        Args:
            text: Response text
            
        Returns:
            Text with self-references removed
        """
        # Pattern: "As {character_name}," or "As {character_name} I"
        # Case-insensitive, match at start of string
        patterns = [
            rf"^As {re.escape(self.character_name)},?\s*",
            rf"^As {re.escape(self.character_name)}\s+I\s+",
        ]
        
        for pattern in patterns:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)
        
        # Clean up any resulting leading whitespace
        text = text.strip()
        
        return text

    def _split_response(self, text: str) -> list[str]:
        """Split long response into multiple parts.
        
        Phase 1: Simple length-based splitting at max_length boundary.
        Adds "..." continuation indicators.
        
        Phase 4: Will implement intelligent sentence-aware splitting.
        
        Args:
            text: Response text to split
            
        Returns:
            List of message parts with continuation indicators
        """
        parts = []
        remaining = text
        
        # Account for "..." continuation indicator (3 chars)
        chunk_size = self.max_length - 3
        
        while remaining:
            if len(remaining) <= self.max_length:
                # Last part (or only part if it fits)
                if parts:  # Not the first part, add leading "..."
                    parts.append(f"...{remaining}")
                else:  # Single part that fits
                    parts.append(remaining)
                break
            
            # Split at chunk_size boundary
            chunk = remaining[:chunk_size]
            
            # Add trailing "..." for continuation
            if parts:  # Not the first part
                parts.append(f"...{chunk}...")
            else:  # First part
                parts.append(f"{chunk}...")
            
            # Move to next chunk (skip overlap with "...")
            remaining = remaining[chunk_size:]
        
        return parts
