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
        trigger_context: str | None = None
    ) -> str:
        """Build user prompt from message.
        
        Implements REQ-013 (Phase 1): Simple user prompt with username and message.
        Implements REQ-034 (Phase 2): Optionally inject trigger context.
        
        Args:
            username: Username of message sender
            message: Cleaned message text (bot name already removed)
            trigger_context: Optional context from trigger (Phase 2)
            
        Returns:
            User prompt text
        """
        # Base format: "{username} says: {message}"
        prompt = f"{username} says: {message}"
        
        # Phase 2: Add trigger context if provided
        if trigger_context:
            prompt += f"\n\nContext: {trigger_context}"
        
        logger.debug(
            f"Built user prompt for {username} ({len(prompt)} chars)"
            + (f" with context" if trigger_context else "")
        )
        return prompt
