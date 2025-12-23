"""Trigger detection engine for chat messages."""

import logging
import random
import re
from collections import deque
from typing import Any, Optional

from kryten.kv_store import get_kv_store, kv_get, kv_put
from kryten_llm.models.config import LLMConfig
from kryten_llm.models.events import TriggerResult

logger = logging.getLogger(__name__)


class TriggerEngine:
    """Detects trigger conditions in chat messages.

    """

    def __init__(self, config: LLMConfig):
        """Initialize with configuration.

        Args:
            config: LLM configuration containing personality name variations and triggers
        """
        self.config = config
        
        # Feature: Context-aware triggers
        # Maintain in-memory buffer of recent messages
        self.history_buffer: deque = deque(maxlen=config.context.chat_history_size)

        # Feature: Media change triggers
        self.last_qualifying_media: dict[str, Any] | None = None

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

        # Feature: Semi-random conversational participation
        self.messages_since_last_trigger = 0
        self.non_trigger_threshold = 0
        self._calculate_next_threshold()

        logger.info(
            f"TriggerEngine initialized with {len(self.name_variations)} name variations, "
            f"{len(self.triggers)} enabled triggers. "
            f"Auto-participation enabled: {config.auto_participation.enabled}"
        )

    def _calculate_next_threshold(self) -> None:
        """Calculate the next message count threshold for auto-participation."""
        config = self.config.auto_participation
        if not config.enabled:
            self.non_trigger_threshold = 999999  # Effectively disable
            return

        base = config.base_message_interval
        prob = config.probability_range

        min_threshold = round(base * (1 - prob))
        max_threshold = round(base * (1 + prob))

        # Clamp to [1, 100]
        min_threshold = max(1, min(100, min_threshold))
        max_threshold = max(1, min(100, max_threshold))
        
        # Ensure min <= max (floating point rounding could weirdly affect this if prob is high?)
        # With range [0.0, 0.5], min <= max is guaranteed for base > 0.
        # But if base=1, min=1, max=1.
        if min_threshold > max_threshold:
             max_threshold = min_threshold

        self.non_trigger_threshold = random.randint(min_threshold, max_threshold)
        logger.debug(f"Next auto-participation threshold set to: {self.non_trigger_threshold}")

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns for name variations and trigger phrases.
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

    def _get_history_context(self) -> list[dict]:
        """Get recent chat history for context.

        Returns last X messages where X is configured in config.context.max_chat_history_in_prompt.
        """
        limit = self.config.context.max_chat_history_in_prompt
        
        # Handle edge cases
        if limit <= 0:
            return []
            
        # Efficiently get last X messages
        # list(deque) copies all, then slice. For small history this is fine.
        # history_buffer automatically handles maxlen (total buffer size).
        context = list(self.history_buffer)[-limit:]
        logger.debug(f"Retrieved {len(context)} messages for context history")
        return context

    async def check_triggers(self, message: dict) -> TriggerResult:
        """Check if message triggers a response.

        Phase 2: Checks mentions first, then trigger word patterns with probabilities

        Processing order (REQ-008):
        1. Check mentions (highest priority)
        2. Check trigger words (by configured priority)
        3. Check auto-participation threshold
        4. Apply probability check if trigger matches

        Args:
            message: Filtered message dict from MessageListener

        Returns:
            TriggerResult indicating if triggered and details
        """
        # Feature: Context-aware triggers - Update history buffer
        self.history_buffer.append(message)

        msg_text = message["msg"]

        # REQ-008: Check mentions FIRST (priority over trigger words)
        mention_result = self._check_mention(msg_text)
        if mention_result:
            self.messages_since_last_trigger = 0  # Reset counter
            logger.info(
                f"Mention detected: '{mention_result.trigger_name}' from " f"{message['username']}"
            )
            # Attach context history
            mention_result.history = self._get_history_context()
            return mention_result

        # Phase 2: Check trigger words (REQ-002)
        trigger_word_result = self._check_trigger_words(msg_text)
        if trigger_word_result:
            self.messages_since_last_trigger = 0  # Reset counter
            logger.info(
                f"Trigger word activated: '{trigger_word_result.trigger_name}' "
                f"(probability check passed) from {message['username']}"
            )
            # Attach context history
            trigger_word_result.history = self._get_history_context()
            return trigger_word_result

        # Feature: Semi-random conversational participation
        # If no traditional trigger, increment counter and check threshold
        if self.config.auto_participation.enabled:
            self.messages_since_last_trigger += 1
            logger.debug(
                f"No traditional trigger. Messages since last trigger: "
                f"{self.messages_since_last_trigger}/{self.non_trigger_threshold}"
            )

            if self.messages_since_last_trigger >= self.non_trigger_threshold:
                logger.info(
                    f"Auto-participation triggered! (Count: {self.messages_since_last_trigger})"
                )
                self.messages_since_last_trigger = 0
                self._calculate_next_threshold()

                return TriggerResult(
                    triggered=True,
                    trigger_type="auto_participant",
                    trigger_name="auto_participation",
                    cleaned_message=msg_text,  # No cleaning needed
                    context=None,
                    priority=1,  # Low priority for chiming in
                    history=self._get_history_context(),
                )

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

    async def load_media_state(self, client: Any) -> None:
        """Load last qualifying media state from KV store.
        
        This tracks the previous media that was long enough to trigger a response,
        allowing the bot to refer to "what just played" in its prompts.
        """
        try:
            # Ensure bucket exists (Get or create)
            # This prevents BucketNotFoundError on first run
            bucket = await get_kv_store(client._nats, "kryten_llm_trigger_state", logger=logger)

            # Using kryten-py kv_store functions to access KV
            data = await kv_get(bucket, "last_qualifying_media", default=None, parse_json=True, logger=logger)
            if data:
                self.last_qualifying_media = data
                logger.info(f"Loaded last qualifying media: {data}")
            else:
                logger.info("No previous media state found (fresh start)")
                
        except Exception as e:
            # Log full error as requested by user to expose underlying issues
            logger.error(f"Failed to load persistent media state: {e}")
            logger.error("Verify NATS JetStream status and 'kryten_llm_trigger_state' bucket existence.")

    async def save_media_state(self, client: Any) -> None:
        """Save last qualifying media state to KV store."""
        if self.last_qualifying_media:
            try:
                # Ensure bucket exists before writing
                bucket = await get_kv_store(client._nats, "kryten_llm_trigger_state", logger=logger)

                await kv_put(
                    bucket,
                    "last_qualifying_media",
                    self.last_qualifying_media,
                    as_json=True,
                    logger=logger
                )
            except Exception as e:
                logger.error(f"Failed to save media state: {e}")

    async def sync_state_from_context(self, current_video: Any, client: Any) -> None:
        """Sync TriggerEngine state with actual current media on startup.
        
        This ensures that if the service restarts, the TriggerEngine knows
        what is currently playing, so that the NEXT media change correctly
        identifies this as the 'previous' media.
        
        Args:
            current_video: VideoMetadata object or dict from ContextManager
            client: KrytenClient for KV access
        """
        if not current_video:
            return

        # Extract title
        title = getattr(current_video, "title", None)
        if not title and isinstance(current_video, dict):
            title = current_video.get("title")
            
        if not title:
            return

        # Extract duration
        duration = 0
        if hasattr(current_video, "duration"):
            duration = current_video.duration
        elif isinstance(current_video, dict):
            duration = current_video.get("duration") or current_video.get("seconds", 0)
            
        try:
            duration = int(duration)
        except (ValueError, TypeError):
            duration = 0

        new_state = {"title": title, "duration": duration}
        
        # Update if different or missing
        # We assume if it's playing NOW, it is the 'last qualifying' (current)
        if self.last_qualifying_media != new_state:
            logger.info(f"Syncing trigger state with current media: {title}")
            self.last_qualifying_media = new_state
            await self.save_media_state(client)

    async def check_media_change(
        self, media_data: dict, client: Any
    ) -> Optional[TriggerResult]:
        """Check if media change triggers a response.

        Args:
            media_data: Dict containing media info (title, duration, etc.)
            client: KrytenClient for KV store access

        Returns:
            TriggerResult if triggered, None otherwise
        """
        config = self.config.media_change
        if not config.enabled:
            return None

        title = media_data.get("title", "Unknown")
        # duration might be in seconds or string? Usually seconds in these events.
        try:
            duration = int(media_data.get("duration", 0) or 0)
        except (ValueError, TypeError):
            duration = 0

        # Threshold check (minutes -> seconds)
        min_seconds = config.min_duration_minutes * 60

        if duration < min_seconds:
            logger.debug(
                f"Media '{title}' duration {duration}s below threshold {min_seconds}s"
            )
            return None

        # It qualifies!
        logger.info(f"Media change trigger: '{title}' ({duration}s) meets length threshold.")

        previous = self.last_qualifying_media

        # Update state
        self.last_qualifying_media = {"title": title, "duration": duration}
        await self.save_media_state(client)

        # Build context/message
        template_data = {
            "current_media_title": title,
            "current_media_duration": f"{duration // 60}m",
            "previous_media_title": previous.get("title", "Unknown")
            if previous
            else "None",
            "transition_explanation": config.transition_explanation,
        }

        # Retrieve chat history (limited by config)
        history_limit = config.chat_context_depth
        history = list(self.history_buffer)[-history_limit:] if history_limit > 0 else []

        return TriggerResult(
            triggered=True,
            trigger_type="media_change",
            trigger_name="media_change",
            cleaned_message="",  # Not used
            context=template_data,  # Pass template data dict
            priority=5,
            history=history,
        )

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
