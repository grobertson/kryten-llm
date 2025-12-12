"""Phase 3 data models for multi-provider LLM and context management."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class VideoMetadata:
    """Current video information from CyTube.

    Phase 3: Tracks current video for context injection (REQ-008, REQ-009).
    """

    title: str
    duration: int  # seconds
    type: str  # "yt", "vm", "dm", etc.
    queued_by: str
    timestamp: datetime


@dataclass
class ChatMessage:
    """A chat message for history buffer.

    Phase 3: Stored in rolling buffer for context injection (REQ-010).
    """

    username: str
    message: str
    timestamp: datetime


@dataclass
class LLMRequest:
    """Request to LLM provider.

    Phase 3: Enhanced with preferred_provider for trigger-specific routing (REQ-004).
    """

    system_prompt: str
    user_prompt: str
    temperature: float = 0.7
    max_tokens: int = 500
    preferred_provider: Optional[str] = None


@dataclass
class LLMResponse:
    """Response from LLM provider.

    Phase 3: Includes provider metrics for logging and monitoring (REQ-006).
    """

    content: str
    provider_used: str
    model_used: str
    tokens_used: Optional[int] = None
    response_time: float = 0.0
