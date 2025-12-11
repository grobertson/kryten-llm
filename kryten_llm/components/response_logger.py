"""Response logging for analysis and debugging."""

import json
import logging
from datetime import datetime
from pathlib import Path

from kryten_llm.models.config import LLMConfig
from kryten_llm.models.events import TriggerResult
from kryten_llm.components.rate_limiter import RateLimitDecision


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
        sent: bool
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
        """
        # REQ-033: Respect log_responses config flag
        if not self.enabled:
            return
        
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
                "details": rate_limit_decision.details
            }
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
