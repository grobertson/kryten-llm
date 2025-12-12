"""Response formatter for chat output.

Phase 4: Intelligent formatting with sentence-aware splitting,
artifact removal, and code block stripping (REQ-001 through REQ-008).
"""

import logging
import re

import emoji

from kryten_llm.models.config import FormattingConfig, LLMConfig, PersonalityConfig

logger = logging.getLogger(__name__)


class ResponseFormatter:
    """Formats LLM responses for chat output.

    Phase 4 Implementation (REQ-001 through REQ-008):
    - Intelligent sentence boundary splitting (REQ-001, REQ-002)
    - Self-reference removal (REQ-003)
    - LLM artifact removal (REQ-004)
    - Emoji limiting (REQ-005)
    - Whitespace normalization (REQ-006)
    - Code block removal (REQ-007)
    - Returns list of formatted strings (REQ-008)

    Follows pipeline pattern (PAT-001):
    1. Remove code blocks
    2. Remove artifacts
    3. Remove self-references
    4. Normalize whitespace
    5. Split on sentences
    6. Add continuation indicators
    7. Return list of strings
    """

    def __init__(self, config: LLMConfig):
        """Initialize with configuration.

        Args:
            config: LLM configuration containing formatting and personality settings
        """
        self.formatting_config: FormattingConfig = config.formatting
        self.personality_config: PersonalityConfig = config.personality
        self.max_length = self.formatting_config.max_message_length
        self.continuation = self.formatting_config.continuation_indicator

        # Compile regex patterns for performance
        self._compile_patterns()

        logger.info(
            f"ResponseFormatter initialized: max_length={self.max_length}, "
            f"character={self.personality_config.character_name}, "
            f"remove_artifacts={self.formatting_config.remove_llm_artifacts}, "
            f"remove_self_refs={self.formatting_config.remove_self_references}"
        )

    def _compile_patterns(self):
        """Compile regex patterns for hot path performance."""
        # Code block pattern (triple backticks)
        self.code_block_pattern = re.compile(r"```[a-z]*\n.*?```", re.DOTALL | re.IGNORECASE)

        # Artifact patterns from config
        self.artifact_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.formatting_config.artifact_patterns
        ]

        # Self-reference patterns
        bot_name = re.escape(self.personality_config.character_name)
        self.self_ref_patterns = [
            re.compile(rf"^(As |I am |I\'m )?{bot_name}[,:]?\s*", re.IGNORECASE),
            re.compile(rf"\b(speaking as|in the role of|playing)\s+{bot_name}\b", re.IGNORECASE),
        ]

        # Sentence boundary pattern - handles . ! ? followed by space or end
        self.sentence_boundary = re.compile(r"([.!?])\s+")

        # Multiple whitespace pattern
        self.multi_space = re.compile(r"\s+")

        # Empty lines pattern
        self.empty_lines = re.compile(r"\n\s*\n")

    def format_response(self, response: str) -> list[str]:
        """Format LLM response for chat following Phase 4 pipeline.

        Pipeline (PAT-001):
        1. Remove code blocks (REQ-007)
        2. Remove artifacts (REQ-004)
        3. Remove self-references (REQ-003)
        4. Normalize whitespace (REQ-006)
        5. Split on sentences (REQ-001)
        6. Add continuation indicators (REQ-002)
        7. Limit emoji if enabled (REQ-005)

        Args:
            response: Raw LLM response text

        Returns:
            List of formatted message strings, each ≤ max_message_length
            Empty list if response is invalid/empty
        """
        if not response or not response.strip():
            logger.warning("Empty response received")
            return []

        try:
            # Step 1: Remove code blocks (REQ-007)
            formatted = self._remove_code_blocks(response)
            if not formatted.strip():
                logger.warning("Response empty after removing code blocks")
                return []

            # Step 2: Remove artifacts (REQ-004)
            if self.formatting_config.remove_llm_artifacts:
                formatted = self._remove_artifacts(formatted)
                if not formatted.strip():
                    logger.warning("Response empty after removing artifacts")
                    return []

            # Step 3: Remove self-references (REQ-003)
            if self.formatting_config.remove_self_references:
                formatted = self._remove_self_references(formatted)
                if not formatted.strip():
                    logger.warning("Response empty after removing self-references")
                    return []

            # Step 4: Normalize whitespace (REQ-006)
            formatted = self._normalize_whitespace(formatted)
            if not formatted:
                logger.warning("Response empty after normalizing whitespace")
                return []

            # Step 5 & 6: Split on sentences and add continuation (REQ-001, REQ-002)
            parts = self._split_on_sentences(formatted, self.max_length)
            parts = self._add_continuation_indicators(parts)

            # Step 7: Limit emoji if enabled (REQ-005)
            if (
                self.formatting_config.enable_emoji_limiting
                and self.formatting_config.max_emoji_per_message
            ):
                parts = [
                    self._limit_emoji(part, self.formatting_config.max_emoji_per_message)
                    for part in parts
                ]

            if not parts:
                logger.warning("No parts generated from response")
                return []

            logger.debug(f"Formatted response into {len(parts)} part(s)")
            return parts

        except Exception as e:
            logger.error(f"Error formatting response: {e}", exc_info=True)
            # Return empty list on error (graceful degradation)
            return []

    def _remove_code_blocks(self, text: str) -> str:
        """Remove triple-backtick code blocks.

        Implements REQ-007: Code blocks are not suitable for chat display.
        Removes entire code block including backticks and content.
        Preserves text before and after code blocks.

        Args:
            text: Response text

        Returns:
            Text with code blocks removed
        """
        # Remove all ```language...``` blocks
        text = self.code_block_pattern.sub("", text)
        return text.strip()

    def _remove_artifacts(self, text: str) -> str:
        """Remove common LLM artifacts and preambles.

        Implements REQ-004: Remove introductory phrases, meta-commentary,
        and hedging language using configured patterns.

        Args:
            text: Response text

        Returns:
            Text with artifacts removed
        """
        for pattern in self.artifact_patterns:
            text = pattern.sub("", text)

        return text.strip()

    def _remove_self_references(self, text: str) -> str:
        """Remove self-referential phrases.

        Implements REQ-003: Remove patterns where bot refers to itself
        in third person or explains its role.

        Examples removed:
        - "As CynthiaRothbot, I think..."
        - "I am CynthiaRothbot and..."
        - "Speaking as CynthiaRothbot..."

        Args:
            text: Response text

        Returns:
            Text with self-references removed
        """
        for pattern in self.self_ref_patterns:
            text = pattern.sub("", text)

        return text.strip()

    def _normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace and line breaks.

        Implements REQ-006:
        - Remove leading/trailing whitespace
        - Replace multiple spaces with single space
        - Remove empty lines
        - Preserve single line breaks where intentional

        Args:
            text: Response text

        Returns:
            Text with normalized whitespace
        """
        # Remove empty lines (multiple newlines)
        text = self.empty_lines.sub("\n", text)

        # Replace multiple spaces with single space
        text = self.multi_space.sub(" ", text)

        # Strip leading/trailing whitespace
        text = text.strip()

        return text

    def _split_on_sentences(self, text: str, max_length: int) -> list[str]:
        """Split text at sentence boundaries.

        Implements REQ-001: Split messages at sentence boundaries (. ! ?)
        rather than mid-word or mid-sentence. Respects max_length constraint.

        If a sentence exceeds max_length, falls back to word boundary splitting.

        Args:
            text: Text to split
            max_length: Maximum length per part

        Returns:
            List of text parts split at sentence boundaries
        """
        if len(text) <= max_length:
            return [text]

        parts = []
        current_part = ""

        # Split into sentences
        sentences = self.sentence_boundary.split(text)

        # Reconstruct sentences with punctuation
        i = 0
        while i < len(sentences):
            if i + 1 < len(sentences) and sentences[i + 1] in ".!?":
                sentence = sentences[i] + sentences[i + 1]
                i += 2
            else:
                sentence = sentences[i]
                i += 1

            # Skip empty sentences
            if not sentence.strip():
                continue

            # If sentence alone exceeds max_length, split on words
            if len(sentence) > max_length:
                # Flush current part if any
                if current_part:
                    parts.append(current_part.strip())
                    current_part = ""

                # Split long sentence on word boundaries
                words = sentence.split()
                word_part = ""
                for word in words:
                    if len(word_part) + len(word) + 1 <= max_length:
                        word_part += (" " if word_part else "") + word
                    else:
                        if word_part:
                            parts.append(word_part.strip())
                        word_part = word

                if word_part:
                    current_part = word_part
                continue

            # Check if adding sentence exceeds limit
            test_part = (current_part + " " + sentence).strip() if current_part else sentence

            if len(test_part) <= max_length:
                current_part = test_part
            else:
                # Current part is full, start new part
                if current_part:
                    parts.append(current_part.strip())
                current_part = sentence.strip()

        # Add final part
        if current_part:
            parts.append(current_part.strip())

        return parts if parts else [text]

    def _add_continuation_indicators(self, parts: list[str]) -> list[str]:
        """Add continuation indicators to multi-part messages.

        Implements REQ-002: Append continuation indicator (default " ...")
        to all parts except the last one.

        Args:
            parts: List of message parts

        Returns:
            List of parts with continuation indicators added
        """
        if len(parts) <= 1:
            return parts

        # Add continuation to all but last part
        result = []
        for i, part in enumerate(parts):
            if i < len(parts) - 1:
                # Ensure continuation fits
                max_content = self.max_length - len(self.continuation)
                if len(part) > max_content:
                    part = part[:max_content].rstrip()
                result.append(part + self.continuation)
            else:
                result.append(part)

        return result

    def _limit_emoji(self, text: str, max_emoji: int) -> str:
        """Limit emoji count in text.

        Implements REQ-005: Optional emoji limiting.
        Counts emoji and truncates if exceeds max.

        Args:
            text: Text to limit
            max_emoji: Maximum emoji allowed

        Returns:
            Text with emoji limited
        """
        # Count emoji in text
        emoji_count = emoji.emoji_count(text)

        if emoji_count <= max_emoji:
            return text

        # Remove excess emoji
        # Extract all emoji
        emojis = emoji.emoji_list(text)

        # Mark emoji to remove (those beyond max_emoji)
        if len(emojis) > max_emoji:
            to_remove = emojis[max_emoji:]
            # Remove from end to start to preserve indices
            for em in reversed(to_remove):
                start = em["match_start"]
                end = em["match_end"]
                text = text[:start] + text[end:]

        return text
