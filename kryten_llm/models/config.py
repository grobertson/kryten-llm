"""Configuration management for kryten-llm."""

from kryten import KrytenConfig  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

# ============================================================================
# LLM-Specific Configuration Models
# ============================================================================


class PersonalityConfig(BaseModel):
    """Bot personality configuration."""

    character_name: str = Field(default="CynthiaRothbot", description="Bot character name")
    character_description: str = Field(
        default="legendary martial artist and actress",
        description="Character description for LLM context",
    )
    personality_traits: list[str] = Field(
        default=["confident", "action-oriented", "pithy", "martial arts expert"],
        description="List of personality traits",
    )
    expertise: list[str] = Field(
        default=["kung fu", "action movies", "martial arts", "B-movies"],
        description="Areas of expertise",
    )
    response_style: str = Field(default="short and punchy", description="Desired response style")
    name_variations: list[str] = Field(
        default=["cynthia", "rothrock", "cynthiarothbot"],
        description="Alternative names that trigger mentions",
    )


class LLMProvider(BaseModel):
    """LLM provider configuration.

    Phase 3 enhancement: Added priority, max_retries, and custom_headers
    to support multi-provider fallback strategy (REQ-001, REQ-003, REQ-007, REQ-024).
    """

    name: str = Field(description="Provider identifier")
    type: str = Field(description="Provider type: openai_compatible, openrouter, anthropic")
    base_url: str = Field(description="API base URL")
    api_key: str = Field(description="API key for authentication")
    model: str = Field(description="Model identifier")
    max_tokens: int = Field(default=256, description="Maximum tokens in response", ge=1, le=4096)
    temperature: float = Field(default=0.8, description="Sampling temperature", ge=0.0, le=2.0)
    timeout_seconds: int = Field(default=30, description="Request timeout", ge=1, le=120)
    max_retries: int = Field(
        default=3, description="Maximum retry attempts per provider", ge=0, le=10
    )
    priority: int = Field(
        default=99, description="Provider priority (lower number = higher priority)", ge=1
    )
    custom_headers: dict[str, str] | None = Field(
        default=None, description="Custom HTTP headers for provider"
    )
    fallback: str | None = Field(
        default=None,
        description="Fallback provider name on failure (deprecated, use priority instead)",
    )


class Trigger(BaseModel):
    """Trigger word configuration.

    Phase 3 enhancement: Added preferred_provider to support trigger-specific
    provider selection (REQ-004, REQ-022).
    """

    name: str = Field(description="Trigger identifier")
    patterns: list[str] = Field(description="List of regex patterns or strings to match")
    probability: float = Field(
        default=1.0, description="Probability of responding (0.0-1.0)", ge=0.0, le=1.0
    )
    cooldown_seconds: int = Field(
        default=300, description="Cooldown between trigger activations", ge=0
    )
    context: str = Field(default="", description="Additional context to inject into prompt")
    response_style: str | None = Field(
        default=None, description="Override response style for this trigger"
    )
    max_responses_per_hour: int = Field(
        default=10, description="Maximum responses per hour for this trigger", ge=0
    )
    priority: int = Field(
        default=5, description="Trigger priority (higher = more important)", ge=1, le=10
    )
    enabled: bool = Field(default=True, description="Whether trigger is active")
    llm_provider: str | None = Field(
        default=None, description="Specific LLM provider for this trigger (deprecated)"
    )
    preferred_provider: str | None = Field(
        default=None, description="Preferred LLM provider for this trigger (Phase 3)"
    )


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
    """Context management configuration.

    Phase 3: Controls video and chat history context injection into prompts
    (REQ-008 through REQ-013, REQ-023).
    """

    chat_history_size: int = Field(
        default=30, ge=0, le=100, description="Number of messages to buffer"
    )
    context_window_chars: int = Field(
        default=12000, ge=1000, description="Approximate context limit in characters"
    )
    include_video_context: bool = Field(
        default=True, description="Include current video in prompts"
    )
    include_chat_history: bool = Field(default=True, description="Include recent chat in prompts")
    max_video_title_length: int = Field(
        default=200, ge=50, le=500, description="Maximum video title length"
    )
    max_chat_history_in_prompt: int = Field(
        default=10, ge=0, le=50, description="Maximum chat messages in prompt"
    )


class FormattingConfig(BaseModel):
    """Response formatting configuration.

    Phase 4: Controls intelligent response formatting (REQ-001 through REQ-008).
    """

    max_message_length: int = Field(
        default=255, ge=100, le=500, description="Maximum message length"
    )
    continuation_indicator: str = Field(
        default=" ...", description="Continuation indicator for multi-part messages"
    )
    enable_emoji_limiting: bool = Field(default=False, description="Enable emoji count limiting")
    max_emoji_per_message: int | None = Field(
        default=None, ge=1, description="Maximum emoji per message (if enabled)"
    )
    remove_self_references: bool = Field(
        default=True, description="Remove self-referential phrases"
    )
    remove_llm_artifacts: bool = Field(default=True, description="Remove common LLM artifacts")
    artifact_patterns: list[str] = Field(
        default=[
            r"^Here's ",
            r"^Let me ",
            r"^Sure!\\s*",
            r"\\bAs an AI\\b",
            r"^I think ",
            r"^In my opinion ",
        ],
        description="Regex patterns for LLM artifacts to remove",
    )


class ValidationConfig(BaseModel):
    """Response validation configuration.

    Phase 4: Controls response quality validation (REQ-009 through REQ-015).
    """

    min_length: int = Field(default=10, ge=1, description="Minimum response length in characters")
    max_length: int = Field(
        default=2000, ge=100, description="Maximum response length before splitting"
    )
    check_repetition: bool = Field(default=True, description="Check for repetitive responses")
    repetition_history_size: int = Field(
        default=10, ge=1, le=50, description="Number of responses to track for repetition"
    )
    repetition_threshold: float = Field(
        default=0.9, ge=0.0, le=1.0, description="Similarity threshold for repetition (0.0-1.0)"
    )
    check_relevance: bool = Field(default=False, description="Check response relevance to input")
    relevance_threshold: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Minimum relevance score"
    )
    inappropriate_patterns: list[str] = Field(
        default=[], description="Regex patterns for inappropriate content"
    )
    check_inappropriate: bool = Field(default=False, description="Check for inappropriate content")


class MessageWindow(BaseModel):
    """Time window for message rate limiting.

    Phase 4: Used by spam detection (REQ-016).
    """

    seconds: int = Field(ge=1, description="Time window in seconds")
    max_messages: int = Field(ge=1, description="Maximum messages allowed in window")


class SpamDetectionConfig(BaseModel):
    """Spam detection configuration.

    Phase 4: Controls user spam detection and penalties (REQ-016 through REQ-022).
    Supports both structured MessageWindow format and simple threshold format from config.json.
    """

    enabled: bool = Field(default=True, description="Enable spam detection")

    # Rate limiting windows
    message_windows: list[MessageWindow] = Field(
        default_factory=lambda: [
            MessageWindow(seconds=60, max_messages=5),
            MessageWindow(seconds=300, max_messages=10),
            MessageWindow(seconds=900, max_messages=20),
        ],
        description="Message rate limit windows",
    )

    # Identical message detection - supports both formats
    identical_message_window: MessageWindow | None = Field(
        default=None, description="Window for identical message detection (structured format)"
    )
    identical_message_threshold: int = Field(
        default=3, ge=1, description="Max identical messages before spam (simple format)"
    )

    # Mention spam detection - supports both formats
    mention_spam_window: MessageWindow | int = Field(
        default=30, description="Window for mention spam - int (seconds) or MessageWindow"
    )
    mention_spam_threshold: int = Field(
        default=3, ge=1, description="Max mentions in window before spam"
    )

    # Penalty configuration
    initial_penalty: int = Field(
        default=30, ge=1, description="Initial penalty duration in seconds"
    )
    penalty_multiplier: float = Field(
        default=2.0, ge=1.0, description="Penalty duration multiplier"
    )
    max_penalty: int = Field(default=600, ge=60, description="Maximum penalty duration in seconds")
    penalty_durations: list[int] | None = Field(
        default=None,
        description="Explicit penalty durations (overrides initial_penalty/multiplier if set)",
    )

    # Reset and exemptions
    clean_period: int = Field(
        default=600, ge=60, description="Clean period to reset offense counts in seconds"
    )
    admin_exempt_ranks: list[int] = Field(
        default=[3, 4, 5], description="User ranks exempt from spam detection"
    )

    # Backwards compatibility aliases
    @property
    def max_penalty_duration(self) -> int:
        """Alias for max_penalty."""
        return self.max_penalty

    @property
    def clean_period_for_reset(self) -> int:
        """Alias for clean_period."""
        return self.clean_period

    @property
    def admin_ranks(self) -> list[int]:
        """Alias for admin_exempt_ranks."""
        return self.admin_exempt_ranks

    def get_identical_message_window(self) -> MessageWindow:
        """Get identical message window, handling both formats."""
        if self.identical_message_window:
            return self.identical_message_window
        # Create from simple threshold
        return MessageWindow(seconds=300, max_messages=self.identical_message_threshold)

    def get_mention_spam_window(self) -> MessageWindow:
        """Get mention spam window, handling both formats."""
        if isinstance(self.mention_spam_window, MessageWindow):
            return self.mention_spam_window
        # Create from simple int (seconds) + threshold
        return MessageWindow(
            seconds=self.mention_spam_window, max_messages=self.mention_spam_threshold
        )

    def get_penalty_durations(self) -> list[int]:
        """Get penalty durations, calculating if not explicit."""
        if self.penalty_durations:
            return self.penalty_durations
        # Calculate from initial_penalty and multiplier
        durations = []
        current: float = self.initial_penalty
        while current <= self.max_penalty:
            durations.append(int(current))
            current = current * self.penalty_multiplier
        return durations or [self.initial_penalty]


class ErrorHandlingConfig(BaseModel):
    """Error handling configuration.

    Phase 4: Controls error handling and fallback responses (REQ-023 through REQ-028).
    """

    enable_fallback_responses: bool = Field(
        default=False, description="Enable fallback responses on errors"
    )
    fallback_messages: list[str] = Field(
        default=[
            "I'm having trouble thinking right now. Try again later!",
            "My circuits are a bit scrambled. Give me a moment!",
            "ERROR: Brain.exe has stopped responding.",
        ],
        description="Fallback messages for errors",
    )
    log_full_context: bool = Field(default=True, description="Log full context on errors")
    generate_correlation_ids: bool = Field(
        default=True, description="Generate correlation IDs for request tracking"
    )


class MetricsConfig(BaseModel):
    """Metrics and health endpoint configuration.

    HTTP metrics server for observability.
    Provides /health and /metrics endpoints for Prometheus scraping.
    """

    enabled: bool = Field(default=True, description="Enable metrics HTTP server")
    port: int = Field(default=28286, ge=1024, le=65535, description="HTTP port for metrics")
    host: str = Field(default="0.0.0.0", description="Host to bind metrics server")


class ServiceMetadata(BaseModel):
    """Service discovery and monitoring configuration.

    Phase 5: Service discovery configuration (REQ-009).
    Controls how the service announces itself to the Kryten ecosystem
    and publishes health/heartbeat information.
    """

    service_name: str = Field(default="llm", description="Service identifier for discovery")

    service_version: str = Field(default="1.0.0", description="Service version string")

    heartbeat_interval_seconds: int = Field(
        default=10, ge=1, le=60, description="Heartbeat publishing interval in seconds"
    )

    enable_service_discovery: bool = Field(
        default=True, description="Enable service discovery announcements"
    )

    enable_heartbeats: bool = Field(
        default=True, description="Enable periodic heartbeat publishing"
    )

    graceful_shutdown_timeout_seconds: int = Field(
        default=30, ge=5, le=120, description="Maximum time to wait for graceful shutdown"
    )


# ============================================================================
# Main Configuration (Extends KrytenConfig)
# ============================================================================


class RetryStrategy(BaseModel):
    """Retry strategy configuration for LLM providers.

    Phase 3: Exponential backoff configuration (REQ-003).
    """

    initial_delay: float = Field(
        default=1.0, ge=0.1, le=10.0, description="Initial retry delay in seconds"
    )
    multiplier: float = Field(
        default=2.0, ge=1.0, le=5.0, description="Delay multiplier for exponential backoff"
    )
    max_delay: float = Field(
        default=30.0, ge=1.0, le=120.0, description="Maximum retry delay in seconds"
    )


class AutoParticipationConfig(BaseModel):
    """Configuration for semi-random conversational participation (non-triggered messages)."""

    base_message_interval: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Target number of received messages between potential non-trigger messages",
    )
    probability_range: float = Field(
        default=0.2,
        ge=0.0,
        le=0.5,
        description="Randomness range for interval adjustment (0.0-0.5)",
    )
    enabled: bool = Field(
        default=False, description="Enable semi-random conversational participation"
    )


class MediaChangeConfig(BaseModel):
    """Configuration for media change triggers."""

    enabled: bool = Field(default=False, description="Enable media change triggers")
    min_duration_minutes: int = Field(
        default=30, ge=1, le=240, description="Minimum duration in minutes for triggering"
    )
    chat_context_depth: int = Field(
        default=3, ge=1, le=10, description="Number of chat messages to include in context"
    )
    transition_explanation: str = Field(
        default="The media has just changed.",
        max_length=140,
        description="Explanation text for the transition",
    )


class LLMConfig(KrytenConfig):
    """Extended configuration for kryten-llm service.

    Inherits NATS and channel configuration from KrytenConfig.
    Adds LLM-specific settings for personality, providers, triggers, etc.

    Phase 3 enhancements: Multi-provider support with fallback, retry strategy,
    and default provider priority order (REQ-002, REQ-003, REQ-021).
    """

    # LLM-specific configuration
    personality: PersonalityConfig = Field(
        default_factory=PersonalityConfig, description="Bot personality configuration"
    )
    llm_providers: dict[str, LLMProvider] = Field(description="LLM provider configurations")
    default_provider: str = Field(default="local", description="Default LLM provider name")
    default_provider_priority: list[str] = Field(
        default_factory=list, description="Default provider priority order (Phase 3)"
    )
    retry_strategy: RetryStrategy = Field(
        default_factory=RetryStrategy, description="Retry strategy for provider failures (Phase 3)"
    )
    auto_participation: AutoParticipationConfig = Field(
        default_factory=AutoParticipationConfig,
        description="Semi-random participation configuration",
    )
    media_change: MediaChangeConfig = Field(
        default_factory=MediaChangeConfig, description="Media change trigger configuration"
    )
    triggers: list[Trigger] = Field(default_factory=list, description="Trigger word configurations")
    rate_limits: RateLimits = Field(
        default_factory=RateLimits, description="Rate limiting configuration"
    )
    message_processing: MessageProcessing = Field(
        default_factory=MessageProcessing, description="Message processing settings"
    )
    testing: TestingConfig = Field(
        default_factory=TestingConfig, description="Testing configuration"
    )
    context: ContextConfig = Field(
        default_factory=ContextConfig, description="Context management settings"
    )
    formatting: FormattingConfig = Field(
        default_factory=FormattingConfig, description="Response formatting settings (Phase 4)"
    )
    validation: ValidationConfig = Field(
        default_factory=ValidationConfig, description="Response validation settings (Phase 4)"
    )
    spam_detection: SpamDetectionConfig = Field(
        default_factory=SpamDetectionConfig, description="Spam detection settings (Phase 4)"
    )
    error_handling: ErrorHandlingConfig = Field(
        default_factory=ErrorHandlingConfig, description="Error handling settings (Phase 4)"
    )
    service_metadata: ServiceMetadata = Field(
        default_factory=ServiceMetadata,
        description="Service discovery and monitoring settings (Phase 5)",
    )
    metrics: MetricsConfig = Field(
        default_factory=MetricsConfig,
        description="Metrics and health endpoint settings",
    )

    def validate_config(self) -> tuple[bool, list[str]]:
        """Validate configuration and return (is_valid, errors)."""
        errors = []

        # Validate default provider exists
        if self.default_provider not in self.llm_providers:
            errors.append(f"Default provider '{self.default_provider}' not found in llm_providers")

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

    def model_dump(self, **kwargs: object) -> dict[str, object]:
        """Override to transform service_metadata to service for KrytenClient compatibility.

        KrytenClient expects a 'service' key with specific field names.
        This transforms our 'service_metadata' structure to match.
        """
        data: dict[str, object] = super().model_dump(**kwargs)

        # Transform service_metadata to service format expected by KrytenClient
        if "service_metadata" in data:
            sm = data["service_metadata"]
            if isinstance(sm, dict):
                data["service"] = {
                    "name": sm.get("service_name", "llm"),
                    "version": sm.get("service_version", "1.0.0"),
                    "heartbeat_interval": sm.get("heartbeat_interval_seconds", 30),
                    "enable_heartbeat": sm.get("enable_heartbeats", True),
                    "enable_discovery": sm.get("enable_service_discovery", True),
                    "enable_lifecycle": True,  # Always enable lifecycle events
                }

        return data
