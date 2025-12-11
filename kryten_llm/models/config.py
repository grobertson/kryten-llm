"""Configuration management for kryten-llm."""

from pathlib import Path
from pydantic import BaseModel, Field, field_validator
from kryten import KrytenConfig  # Import from kryten-py


# ============================================================================
# LLM-Specific Configuration Models
# ============================================================================

class PersonalityConfig(BaseModel):
    """Bot personality configuration."""
    
    character_name: str = Field(
        default="CynthiaRothbot",
        description="Bot character name"
    )
    character_description: str = Field(
        default="legendary martial artist and actress",
        description="Character description for LLM context"
    )
    personality_traits: list[str] = Field(
        default=["confident", "action-oriented", "pithy", "martial arts expert"],
        description="List of personality traits"
    )
    expertise: list[str] = Field(
        default=["kung fu", "action movies", "martial arts", "B-movies"],
        description="Areas of expertise"
    )
    response_style: str = Field(
        default="short and punchy",
        description="Desired response style"
    )
    name_variations: list[str] = Field(
        default=["cynthia", "rothrock", "cynthiarothbot"],
        description="Alternative names that trigger mentions"
    )


class LLMProvider(BaseModel):
    """LLM provider configuration."""
    
    name: str = Field(description="Provider identifier")
    type: str = Field(description="Provider type: openai_compatible, openrouter, anthropic")
    base_url: str = Field(description="API base URL")
    api_key: str = Field(description="API key for authentication")
    model: str = Field(description="Model identifier")
    max_tokens: int = Field(default=256, description="Maximum tokens in response", ge=1, le=4096)
    temperature: float = Field(default=0.8, description="Sampling temperature", ge=0.0, le=2.0)
    timeout_seconds: int = Field(default=10, description="Request timeout", ge=1, le=60)
    fallback: str | None = Field(default=None, description="Fallback provider name on failure")


class Trigger(BaseModel):
    """Trigger word configuration."""
    
    name: str = Field(description="Trigger identifier")
    patterns: list[str] = Field(description="List of regex patterns or strings to match")
    probability: float = Field(default=1.0, description="Probability of responding (0.0-1.0)", ge=0.0, le=1.0)
    cooldown_seconds: int = Field(default=300, description="Cooldown between trigger activations", ge=0)
    context: str = Field(default="", description="Additional context to inject into prompt")
    response_style: str | None = Field(default=None, description="Override response style for this trigger")
    max_responses_per_hour: int = Field(default=10, description="Maximum responses per hour for this trigger", ge=0)
    priority: int = Field(default=5, description="Trigger priority (higher = more important)", ge=1, le=10)
    enabled: bool = Field(default=True, description="Whether trigger is active")
    llm_provider: str | None = Field(default=None, description="Specific LLM provider for this trigger")


class RateLimits(BaseModel):
    """Rate limiting configuration."""
    
    global_max_per_minute: int = Field(default=2, ge=0)
    global_max_per_hour: int = Field(default=20, ge=0)
    global_cooldown_seconds: int = Field(default=15, ge=0)
    user_max_per_hour: int = Field(default=5, ge=0)
    user_cooldown_seconds: int = Field(default=60, ge=0)
    mention_cooldown_seconds: int = Field(default=120, ge=0)
    admin_cooldown_multiplier: float = Field(default=0.5, ge=0.0, le=1.0)
    admin_limit_multiplier: float = Field(default=2.0, ge=1.0)


class MessageProcessing(BaseModel):
    """Message processing configuration."""
    
    max_message_length: int = Field(default=240, ge=1, le=255)
    split_delay_seconds: int = Field(default=2, ge=0, le=10)
    filter_emoji: bool = Field(default=False)
    max_emoji_per_message: int = Field(default=3, ge=0)


class TestingConfig(BaseModel):
    """Testing and development configuration."""
    
    dry_run: bool = Field(default=False)
    log_responses: bool = Field(default=True)
    log_file: str = Field(default="logs/llm-responses.jsonl")
    send_to_chat: bool = Field(default=True)


class ContextConfig(BaseModel):
    """Context management configuration."""
    
    chat_history_buffer: int = Field(default=30, ge=0, le=100)
    include_video_context: bool = Field(default=True)
    include_chat_history: bool = Field(default=True)


# ============================================================================
# Main Configuration (Extends KrytenConfig)
# ============================================================================

class LLMConfig(KrytenConfig):
    """Extended configuration for kryten-llm service.
    
    Inherits NATS and channel configuration from KrytenConfig.
    Adds LLM-specific settings for personality, providers, triggers, etc.
    """
    
    # LLM-specific configuration
    personality: PersonalityConfig = Field(
        default_factory=PersonalityConfig,
        description="Bot personality configuration"
    )
    llm_providers: dict[str, LLMProvider] = Field(
        description="LLM provider configurations"
    )
    default_provider: str = Field(
        default="local",
        description="Default LLM provider name"
    )
    triggers: list[Trigger] = Field(
        default_factory=list,
        description="Trigger word configurations"
    )
    rate_limits: RateLimits = Field(
        default_factory=RateLimits,
        description="Rate limiting configuration"
    )
    message_processing: MessageProcessing = Field(
        default_factory=MessageProcessing,
        description="Message processing settings"
    )
    testing: TestingConfig = Field(
        default_factory=TestingConfig,
        description="Testing configuration"
    )
    context: ContextConfig = Field(
        default_factory=ContextConfig,
        description="Context management settings"
    )
    
    def validate_config(self) -> tuple[bool, list[str]]:
        """Validate configuration and return (is_valid, errors)."""
        errors = []
        
        # Validate default provider exists
        if self.default_provider not in self.llm_providers:
            errors.append(
                f"Default provider '{self.default_provider}' not found in llm_providers"
            )
        
        # Validate fallback providers exist
        for provider_name, provider in self.llm_providers.items():
            if provider.fallback and provider.fallback not in self.llm_providers:
                errors.append(
                    f"Provider '{provider_name}' has invalid fallback '{provider.fallback}'"
                )
        
        # Validate trigger LLM providers
        for trigger in self.triggers:
            if trigger.llm_provider and trigger.llm_provider not in self.llm_providers:
                errors.append(
                    f"Trigger '{trigger.name}' has invalid llm_provider '{trigger.llm_provider}'"
                )
        
        return (len(errors) == 0, errors)
