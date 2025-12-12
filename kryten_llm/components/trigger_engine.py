"""Trigger detection engine for chat messages."""

import logging
import random
import re
from typing import Optional

from kryten_llm.models.config import LLMConfig
from kryten_llm.models.events import TriggerResult

logger = logging.getLogger(__name__)


class TriggerEngine:
    """Detects trigger conditions in chat messages.

    Implements REQ-004, REQ-005, REQ-006 from Phase 1 specification:
    - Detect mentions using name variations (case-insensitive)
    - Clean message by removing bot name
    - Return TriggerResult with appropriate fields

    Phase 1: Only mention detection
    Phase 2: Add trigger word patterns with probabilities
    """

    def __init__(self, config: LLMConfig):
        """Initialize with configuration.

        Args:
            config: LLM configuration containing personality name variations and triggers
        """
        self.config = config
        # Sort name variations by length (longest first) to match longer names first
        # This prevents "cynthia" from matching "cynthiarothbot"
        self.name_variations = sorted(
            [name.lower() for name in config.personality.name_variations], key=len, reverse=True
        )

        # Phase 2: Load enabled triggers and sort by priority (REQ-001, REQ-007)
        self.triggers = [t for t in config.triggers if t.enabled]
        # Sort by priority (highest first) for REQ-010
        self.triggers.sort(key=lambda t: t.priority, reverse=True)

        # Phase 6: Pre-compile regex patterns for efficiency
        self._compiled_name_patterns: dict[str, re.Pattern] = {}
        self._compiled_trigger_patterns: dict[str, re.Pattern] = {}
        self._compile_patterns()

        logger.info(
            f"TriggerEngine initialized with {len(self.name_variations)} name variations "
            f"and {len(self.triggers)} enabled triggers"
        )

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns for name variations and trigger phrases.

        Phase 6: Pattern compilation for performance optimization.
        """
        # Compile name variation patterns
        for name in self.name_variations:
            self._compiled_name_patterns[name] = re.compile(
                r"\b" + re.escape(name) + r"\b[,.:;!?]?\s*", re.IGNORECASE
            )

        # Compile trigger phrase patterns
        for trigger in self.triggers:
            for pattern in trigger.patterns:
                pattern_lower = pattern.lower()
                if pattern_lower not in self._compiled_trigger_patterns:
                    self._compiled_trigger_patterns[pattern_lower] = re.compile(
                        r"\b" + re.escape(pattern) + r"\b[,.:;!?]?\s*", re.IGNORECASE
                    )

        logger.debug(
            f"Compiled {len(self._compiled_name_patterns)} name patterns "
            f"and {len(self._compiled_trigger_patterns)} trigger patterns"
        )

    async def check_triggers(self, message: dict) -> TriggerResult:
        """Check if message triggers a response.

        Phase 2: Checks mentions first, then trigger word patterns with probabilities

        Processing order (REQ-008):
        1. Check mentions (highest priority)
        2. Check trigger words (by configured priority)
        3. Apply probability check if trigger matches

        Args:
            message: Filtered message dict from MessageListener

        Returns:
            TriggerResult indicating if triggered and details
        """
        msg_text = message["msg"]

        # REQ-008: Check mentions FIRST (priority over trigger words)
        mention_result = self._check_mention(msg_text)
        if mention_result:
            logger.info(
                f"Mention detected: '{mention_result.trigger_name}' from " f"{message['username']}"
            )
            return mention_result

        # Phase 2: Check trigger words (REQ-002)
        trigger_word_result = self._check_trigger_words(msg_text)
        if trigger_word_result:
            logger.info(
                f"Trigger word activated: '{trigger_word_result.trigger_name}' "
                f"(probability check passed) from {message['username']}"
            )
            return trigger_word_result

        # No triggers detected
        logger.debug(f"No triggers in message from {message['username']}")
        return TriggerResult(
            triggered=False,
            trigger_type=None,
            trigger_name=None,
            cleaned_message=msg_text,
            context=None,
            priority=0,
        )

    def _check_mention(self, message_text: str) -> Optional[TriggerResult]:
        """Check for bot name mentions.

        Args:
            message_text: Message text to check

        Returns:
            TriggerResult with trigger_type="mention" if found, else None
        """
        msg_lower = message_text.lower()

        for name_variation in self.name_variations:
            if name_variation in msg_lower:
                cleaned_message = self._remove_bot_name(message_text, name_variation)

                return TriggerResult(
                    triggered=True,
                    trigger_type="mention",
                    trigger_name=name_variation,
                    cleaned_message=cleaned_message,
                    context=None,  # Mentions don't have context
                    priority=10,  # High priority for mentions
                )

        return None

    def _check_trigger_words(self, message_text: str) -> Optional[TriggerResult]:
        """Check for trigger word patterns with probability.

        Iterates through triggers by priority (highest first).
        For each trigger, checks if any pattern matches.
        If match found, applies probability check (REQ-004).

        Args:
            message_text: Message text to check

        Returns:
            TriggerResult with trigger_type="trigger_word" if triggered, else None
        """
        msg_lower = message_text.lower()

        # REQ-010: Check triggers in priority order (highest first)
        for trigger in self.triggers:
            # Check if any pattern matches (REQ-003, REQ-009)
            matched_pattern = None
            for pattern in trigger.patterns:
                if self._match_pattern(pattern, msg_lower):
                    matched_pattern = pattern
                    break

            if matched_pattern:
                # REQ-004: Apply probability check
                roll = random.random()
                logger.debug(
                    f"Trigger '{trigger.name}' pattern matched, "
                    f"probability roll: {roll:.3f} vs {trigger.probability}"
                )

                if roll < trigger.probability:
                    # Trigger activated!
                    cleaned_message = self._clean_message(message_text, matched_pattern)

                    # REQ-005, REQ-006: Return trigger context and priority
                    return TriggerResult(
                        triggered=True,
                        trigger_type="trigger_word",
                        trigger_name=trigger.name,
                        cleaned_message=cleaned_message,
                        context=trigger.context if trigger.context else None,
                        priority=trigger.priority,
                    )
                else:
                    # Probability check failed, continue to next trigger
                    logger.debug(
                        f"Trigger '{trigger.name}' pattern matched but "
                        f"probability check failed ({roll:.3f} >= {trigger.probability})"
                    )

        return None

    def _match_pattern(self, pattern: str, text: str) -> bool:
        """Check if pattern matches text (case-insensitive substring).

        Phase 2: Simple substring matching (CON-001)
        Phase 3+: Could add regex support

        Args:
            pattern: Pattern to match (will be lowercased)
            text: Text to search in (already lowercased)

        Returns:
            True if pattern found in text
        """
        return pattern.lower() in text

    def _clean_message(self, message: str, trigger_phrase: str) -> str:
        """Remove trigger phrase from message for LLM processing.

        Args:
            message: Original message text
            trigger_phrase: The phrase that was matched

        Returns:
            Cleaned message with trigger phrase removed
        """
        # Phase 6: Use cached compiled pattern if available
        pattern_lower = trigger_phrase.lower()
        if pattern_lower in self._compiled_trigger_patterns:
            compiled = self._compiled_trigger_patterns[pattern_lower]
        else:
            # Fallback: compile on the fly for patterns not in cache
            compiled = re.compile(
                r"\b" + re.escape(trigger_phrase) + r"\b[,.:;!?]?\s*", re.IGNORECASE
            )

        # Remove the phrase
        cleaned = compiled.sub("", message)

        # Clean up extra whitespace
        cleaned = " ".join(cleaned.split())

        return cleaned.strip()

    def _remove_bot_name(self, message: str, name_variation: str) -> str:
        """Remove bot name from message (case-insensitive).

        Removes the matched name variation and cleans up extra whitespace.

        Args:
            message: Original message text
            name_variation: The name variation that was matched (lowercase)

        Returns:
            Cleaned message with bot name removed
        """
        # Phase 6: Use cached compiled pattern
        if name_variation in self._compiled_name_patterns:
            compiled = self._compiled_name_patterns[name_variation]
        else:
            # Fallback: compile on the fly
            compiled = re.compile(
                r"\b" + re.escape(name_variation) + r"\b[,.:;!?]?\s*", re.IGNORECASE
            )

        # Remove the name
        cleaned = compiled.sub("", message)

        # Clean up extra whitespace
        cleaned = " ".join(cleaned.split())

        # Remove leading/trailing whitespace and punctuation
        cleaned = cleaned.strip(" ,.:;!?")

        return cleaned
