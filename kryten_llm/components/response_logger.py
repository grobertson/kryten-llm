"""Response logging for analysis and debugging."""

import json
import logging
from datetime import datetime
from pathlib import Path

from kryten_llm.components.rate_limiter import RateLimitDecision
from kryten_llm.models.config import LLMConfig
from kryten_llm.models.events import TriggerResult

logger = logging.getLogger(__name__)


class ResponseLogger:
    """Logs bot responses to JSONL file for analysis.

    Implements REQ-024 through REQ-029:
    - Log all responses to JSONL file
    - Include comprehensive metadata
    - Handle file I/O errors gracefully
    - Create directories and files as needed
    - Append to existing logs
    - Produce valid JSON per line
    """

    def __init__(self, config: LLMConfig):
        """Initialize logger with configuration.

        Args:
            config: LLM configuration containing testing.log_file setting
        """
        self.config = config
        self.log_path = Path(config.testing.log_file)
        self.enabled = config.testing.log_responses

        # REQ-027, REQ-032: Create log directory if missing
        if self.enabled:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                logger.info(f"ResponseLogger initialized: {self.log_path}")
            except Exception as e:
                logger.error(f"Failed to create log directory: {e}")
                self.enabled = False

    async def log_response(
        self,
        username: str,
        trigger_result: TriggerResult,
        input_message: str,
        llm_response: str,
        formatted_parts: list[str],
        rate_limit_decision: RateLimitDecision,
        sent: bool,
        full_prompt: str = "",  # Added full prompt
    ) -> None:
        """Log a response event to JSONL file.

        Implements REQ-024, REQ-025: Log all responses with comprehensive metadata.

        Args:
            username: User who triggered response
            trigger_result: TriggerResult from trigger check
            input_message: Original user message
            llm_response: Raw LLM response
            formatted_parts: List of formatted message parts
            rate_limit_decision: Rate limit decision details
            sent: Whether response was actually sent (False if dry-run or blocked)
            full_prompt: The full prompt sent to the LLM
        """
        # REQ-033: Respect log_responses config flag
        if not self.enabled:
            return

        # Detailed logging for manual inspection (requested format)
        try:
            detailed_log_entry = (
                f"Which trigger was called: {trigger_result.trigger_type} ({trigger_result.trigger_name})\n"
                f"Priority: {trigger_result.priority}\n"
                f"\n---\n\n"
                f"The line which triggered it: {input_message}\n"
                f"Username: {username}\n"
                f"Cleaned Message: {trigger_result.cleaned_message}\n"
                f"\n---\n\n"
                f"The prompt in detail:\n{full_prompt}\n"
                f"\n---\n\n"
                f"The LLM's response in detail:\n{llm_response}\n"
                f"\nFormatted Parts: {json.dumps(formatted_parts)}\n"
                f"\n---\n\n"
                f"Metadata:\n"
                f"Response Sent: {sent}\n"
                f"Rate Limit: {json.dumps({'allowed': rate_limit_decision.allowed, 'reason': rate_limit_decision.reason, 'retry_after': rate_limit_decision.retry_after, 'details': rate_limit_decision.details})}\n"
                f"\n---\n"
            )
            # Log to a separate human-readable file or append to the main log if structured logging isn't strictly required there
            # Since the requirement asks for "a log from the llm", creating a specific readable log file seems appropriate.
            # We'll use a separate file "detailed_responses.log" in the same directory.
            detailed_log_path = self.log_path.parent / "detailed_responses.log"
            with open(detailed_log_path, "a", encoding="utf-8") as f:
                f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                f.write(detailed_log_entry)
                f.write("\n" + "=" * 80 + "\n\n")

        except Exception as e:
            logger.error(f"Failed to write detailed log: {e}")

        # REQ-025: Build comprehensive log entry
        entry = {
            "timestamp": datetime.now().isoformat(),
            "trigger_type": trigger_result.trigger_type,
            "trigger_name": trigger_result.trigger_name,
            "trigger_priority": trigger_result.priority,
            "username": username,
            "input_message": input_message,
            "cleaned_message": trigger_result.cleaned_message,
            "llm_response": llm_response,
            "formatted_parts": formatted_parts,
            "response_sent": sent,
            "rate_limit": {
                "allowed": rate_limit_decision.allowed,
                "reason": rate_limit_decision.reason,
                "retry_after": rate_limit_decision.retry_after,
                "details": rate_limit_decision.details,
            },
            "full_prompt": full_prompt,
        }

        # REQ-026: Handle file I/O errors gracefully
        try:
            # REQ-028, REQ-029: Append valid JSON (one per line)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

            logger.debug(
                f"Logged response: {trigger_result.trigger_type}/{trigger_result.trigger_name} "
                f"from {username} (sent={sent})"
            )
        except Exception as e:
            # REQ-026: Don't crash on I/O errors
            logger.error(f"Failed to write response log: {e}")
