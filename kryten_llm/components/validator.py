"""Response validator for quality checking.

Phase 4: Response validation to ensure quality and relevance
(REQ-009 through REQ-015).
"""

import logging
import re
from collections import deque
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal

from kryten_llm.models.config import ValidationConfig

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of response validation.

    Implements PAT-002 from Phase 4 specification.
    """

    valid: bool
    reason: str
    severity: Literal["INFO", "WARNING", "ERROR"]


class ResponseValidator:
    """Validates LLM responses before sending.

    Phase 4 Implementation (REQ-009 through REQ-015):
    - Length checking (min/max) (REQ-009, REQ-010)
    - Repetition detection (REQ-011)
    - Inappropriate content filtering (REQ-012)
    - Relevance checking (REQ-013)
    - Detailed rejection reasons (REQ-014)
    - Personality-aware validation (REQ-015)
    """

    def __init__(self, config: ValidationConfig):
        """Initialize validator with configuration.

        Args:
            config: Validation configuration
        """
        self.config = config
        self._recent_responses: deque[str] = deque(maxlen=config.repetition_history_size)

        # Compile inappropriate content patterns if enabled
        self.inappropriate_patterns = []
        if config.check_inappropriate and config.inappropriate_patterns:
            self.inappropriate_patterns = [
                re.compile(pattern, re.IGNORECASE) for pattern in config.inappropriate_patterns
            ]

        logger.info(
            f"ResponseValidator initialized: "
            f"min_length={config.min_length}, max_length={config.max_length}, "
            f"check_repetition={config.check_repetition}, "
            f"check_relevance={config.check_relevance}, "
            f"check_inappropriate={config.check_inappropriate}"
        )

    def validate(
        self, response: str, user_message: str, context: dict[str, Any]
    ) -> ValidationResult:
        """Validate response against quality criteria.

        Runs all enabled validation checks and returns result.

        Args:
            response: Formatted response to validate
            user_message: Original user message
            context: Context dict from ContextManager

        Returns:
            ValidationResult with valid flag and reason
        """
        # Check length (REQ-009, REQ-010)
        result = self._check_length(response)
        if not result.valid:
            return result

        # Check repetition (REQ-011)
        if self.config.check_repetition:
            result = self._check_repetition(response)
            if not result.valid:
                return result

        # Check inappropriate content (REQ-012)
        if self.config.check_inappropriate:
            result = self._check_inappropriate(response)
            if not result.valid:
                return result

        # Check relevance (REQ-013)
        if self.config.check_relevance:
            result = self._check_relevance(response, user_message, context)
            if not result.valid:
                return result

        # All checks passed - add to history for repetition checking
        self._recent_responses.append(response.lower())

        return ValidationResult(valid=True, reason="All validation checks passed", severity="INFO")

    def _check_length(self, response: str) -> ValidationResult:
        """Check if response length is acceptable.

        Implements REQ-009 (min length) and REQ-010 (max length).

        Args:
            response: Response to check

        Returns:
            ValidationResult
        """
        length = len(response)

        if length < self.config.min_length:
            return ValidationResult(
                valid=False,
                reason=f"Response too short ({length} chars, minimum {self.config.min_length})",
                severity="WARNING",
            )

        if length > self.config.max_length:
            return ValidationResult(
                valid=False,
                reason=f"Response too long ({length} chars, maximum {self.config.max_length})",
                severity="ERROR",
            )

        return ValidationResult(valid=True, reason="Length acceptable", severity="INFO")

    def _check_repetition(self, response: str) -> ValidationResult:
        """Check if response is repetitive.

        Implements REQ-011: Detects if response is identical or highly similar
        to recent responses using similarity threshold.

        Args:
            response: Response to check

        Returns:
            ValidationResult
        """
        if not self._recent_responses:
            return ValidationResult(valid=True, reason="No history to compare", severity="INFO")

        response_lower = response.lower()

        # Check for exact match first (fastest)
        if response_lower in self._recent_responses:
            return ValidationResult(
                valid=False,
                reason="Response is identical to recent response (exact match)",
                severity="WARNING",
            )

        # Check for high similarity
        for past_response in self._recent_responses:
            similarity = self._calculate_similarity(response_lower, past_response)
            if similarity >= self.config.repetition_threshold:
                return ValidationResult(
                    valid=False,
                    reason=(
                        f"Response is too similar to recent response "
                        f"(similarity: {similarity:.2f})"
                    ),
                    severity="WARNING",
                )

        return ValidationResult(valid=True, reason="Response is unique", severity="INFO")

    def _check_inappropriate(self, response: str) -> ValidationResult:
        """Check for inappropriate content patterns.

        Implements REQ-012: Checks response against configured inappropriate
        content patterns (profanity, personal info, etc.).

        Args:
            response: Response to check

        Returns:
            ValidationResult
        """
        for pattern in self.inappropriate_patterns:
            match = pattern.search(response)
            if match:
                return ValidationResult(
                    valid=False,
                    reason=f"Response contains inappropriate content: {match.group()}",
                    severity="ERROR",
                )

        return ValidationResult(
            valid=True, reason="No inappropriate content detected", severity="INFO"
        )

    def _check_relevance(self, response: str, user_message: str, context: dict) -> ValidationResult:
        """Check if response is relevant to input.

        Implements REQ-013: Optional relevance checking.
        Checks if response contains keywords from user message or current video context.

        Args:
            response: Response to check
            user_message: Original user message
            context: Context dict

        Returns:
            ValidationResult
        """
        # Simple keyword-based relevance check
        # Extract significant words from user message (>3 chars)
        user_words = {word.lower() for word in re.findall(r"\b\w{4,}\b", user_message)}

        if not user_words:
            # No significant words to check
            return ValidationResult(
                valid=True, reason="No keywords to check relevance", severity="INFO"
            )

        response_lower = response.lower()

        # Check if any user words appear in response
        matching_words = sum(1 for word in user_words if word in response_lower)
        relevance_score = matching_words / len(user_words) if user_words else 0.0

        # Also check video context if available
        if context.get("current_video"):
            video_title = context["current_video"].get("title", "").lower()
            video_words = {word.lower() for word in re.findall(r"\b\w{4,}\b", video_title)}
            if video_words:
                video_matches = sum(1 for word in video_words if word in response_lower)
                # Boost relevance if video context mentioned
                relevance_score = max(relevance_score, video_matches / len(video_words))

        if relevance_score < self.config.relevance_threshold:
            return ValidationResult(
                valid=False,
                reason=f"Response not relevant to input (score: {relevance_score:.2f})",
                severity="WARNING",
            )

        return ValidationResult(
            valid=True,
            reason=f"Response is relevant (score: {relevance_score:.2f})",
            severity="INFO",
        )

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity score between texts.

        Uses SequenceMatcher from difflib for fuzzy matching.
        Returns similarity score between 0.0 and 1.0.

        Args:
            text1: First text
            text2: Second text

        Returns:
            Similarity score (0.0 = completely different, 1.0 = identical)
        """
        return SequenceMatcher(None, text1, text2).ratio()
