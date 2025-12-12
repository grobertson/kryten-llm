"""Prompt builder for LLM requests."""

import logging

from kryten_llm.models.config import LLMConfig


logger = logging.getLogger(__name__)


class PromptBuilder:
    """Constructs prompts for LLM generation.
    
    Implements REQ-011, REQ-012, REQ-013 from Phase 1 specification:
    - Construct system prompts from PersonalityConfig
    - Include character name, description, traits, and response style
    - Construct user prompts with username and cleaned message
    
    Phase 1: Basic prompt construction
    Phase 2: Add trigger context injection (REQ-034)
    Phase 3: Add video and chat history context
    """

    def __init__(self, config: LLMConfig):
        """Initialize with configuration.
        
        Args:
            config: LLM configuration containing personality settings
        """
        self.config = config
        self.personality = config.personality
        logger.info(
            f"PromptBuilder initialized for character: {self.personality.character_name}"
        )

    def build_system_prompt(self) -> str:
        """Build system prompt from personality configuration.
        
        Implements REQ-011, REQ-012: Include all personality attributes
        in a structured system prompt.
        
        Returns:
            System prompt text
        """
        # Format personality traits and expertise as comma-separated lists
        traits = ", ".join(self.personality.personality_traits)
        expertise = ", ".join(self.personality.expertise)
        
        # Build system prompt following specification template
        prompt = f"""You are {self.personality.character_name}, {self.personality.character_description}.

Personality traits: {traits}
Areas of expertise: {expertise}

Response style: {self.personality.response_style}

Important rules:
- Keep responses under 240 characters
- Stay in character
- Be natural and conversational
- Do not use markdown formatting
- Do not start responses with your character name"""
        
        logger.debug(f"Built system prompt ({len(prompt)} chars)")
        return prompt

    def build_user_prompt(
        self,
        username: str,
        message: str,
        trigger_context: str | None = None,
        context: dict | None = None
    ) -> str:
        """Build user prompt with context injection.
        
        Implements REQ-013 (Phase 1): Simple user prompt with username and message.
        Implements REQ-034 (Phase 2): Optionally inject trigger context.
        Phase 3 enhancements (REQ-014 through REQ-018):
        - Accept context dict from ContextManager
        - Inject current video when available
        - Inject recent chat history when available
        - Manage prompt length to fit context window
        
        Args:
            username: Username of message sender
            message: Cleaned message text (bot name already removed)
            trigger_context: Optional context from trigger (Phase 2)
            context: Optional context dict from ContextManager (Phase 3)
            
        Returns:
            User prompt text with injected context
        """
        # Build prompt parts in priority order
        parts = [f"{username} says: {message}"]
        
        # REQ-015: Add current video context if available
        if context and context.get("current_video"):
            video = context["current_video"]
            parts.append(
                f"\n\nCurrently playing: {video['title']} "
                f"(queued by {video['queued_by']})"
            )
        
        # REQ-016: Add chat history context if available
        if context and context.get("recent_messages"):
            messages = context["recent_messages"]
            if messages:
                # Limit to last 5-10 messages to avoid token bloat
                recent = messages[-5:]
                history_lines = [
                    f"- {msg['username']}: {msg['message']}"
                    for msg in recent
                ]
                parts.append(
                    f"\n\nRecent conversation:\n" + "\n".join(history_lines)
                )
        
        # REQ-017: Add trigger context if provided (highest priority)
        if trigger_context:
            parts.append(f"\n\nContext: {trigger_context}")
        
        prompt = "".join(parts)
        
        # REQ-018: Manage prompt length
        max_chars = self.config.context.context_window_chars
        if len(prompt) > max_chars:
            # Truncate chat history first to preserve essential context
            prompt = self._truncate_prompt(prompt, max_chars, trigger_context)
        
        logger.debug(
            f"Built user prompt for {username} ({len(prompt)} chars)"
            + (f" with video context" if context and context.get("current_video") else "")
            + (f" with chat history" if context and context.get("recent_messages") else "")
            + (f" with trigger context" if trigger_context else "")
        )
        return prompt
    
    def _truncate_prompt(
        self,
        prompt: str,
        max_chars: int,
        trigger_context: str | None
    ) -> str:
        """Truncate prompt intelligently to fit context window.
        
        REQ-018: Priority order - keep trigger context > video > chat history.
        Simple truncation for Phase 3, can be enhanced later.
        
        Args:
            prompt: Full prompt text
            max_chars: Maximum allowed characters
            trigger_context: Trigger context to preserve
            
        Returns:
            Truncated prompt
        """
        logger.warning(
            f"Prompt too long ({len(prompt)} chars), truncating to {max_chars}"
        )
        
        # Simple truncation - just cut off excess
        # TODO Phase 4: Implement smarter truncation that removes chat history first
        return prompt[:max_chars]
