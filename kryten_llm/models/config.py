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
    preferred_tier: str | None = Field(
        default=None,
        description=(
            "Pin this trigger to a specific routing tier, bypassing signal threshold. "
            "'premium' or 'economy'. None = use signal routing (REQ-325–329)."
        ),
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
    split_delay_seconds: int = Field(default=2, ge=0, le=15)
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
    Phase 7: Adds optional ``providers`` list for the pluggable context pipeline.
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
        default=50, ge=0, le=50, description="Maximum chat messages in prompt"
    )

    # Deduplication settings for reconnection protection
    enable_enhanced_deduplication: bool = Field(
        default=True, description="Enable enhanced deduplication using correlation IDs"
    )
    reconnection_grace_period: int = Field(
        default=120,
        ge=30,
        le=300,
        description="Seconds to ignore replayed events after reconnection",
    )
    correlation_id_cache_size: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Maximum correlation IDs to cache for deduplication",
    )

    # Phase 7: Pluggable provider list.
    # When absent the pipeline defaults to [video, chat_history] (REQ-007).
    providers: list[dict] | None = Field(
        default=None,
        description=(
            "Ordered list of context provider configs. "
            "Each entry must have 'type' and 'enabled' keys. "
            "When absent, defaults to [video, chat_history] (backwards-compatible)."
        ),
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
    rate_limit_delay: float = Field(
        default=60.0,
        ge=1.0,
        le=600.0,
        description=(
            "Minimum wait in seconds after a 429 rate-limit response. "
            "Overridden upward by the Retry-After header when present."
        ),
    )


# ============================================================================
# Phase 7f: LLM-Driven Fact Extractor Configuration
# ============================================================================


class ExtractorLLMConfig(BaseModel):
    """Dedicated LLM connection for the fact extractor (REQ-001, REQ-002).

    Structurally isolated from the response-generation ``llm_providers`` /
    ``default_provider`` — the extractor gets its own provider map and priority
    list, loaded into a *separate* ``LLMManager`` instance. There is no code
    path where a missing extractor config borrows message-generation credentials.
    """

    providers: dict[str, LLMProvider] = Field(
        description="Dedicated extractor provider map (never llm_providers)"
    )
    provider_priority: list[str] = Field(
        default_factory=list, description="Extractor provider priority order"
    )
    retry_strategy: RetryStrategy = Field(
        default_factory=RetryStrategy, description="Retry/backoff strategy for extractor calls"
    )


class StructuredOutputConfig(BaseModel):
    """Structured-output mode for the extractor LLM (REQ-014)."""

    mode: str = Field(
        default="auto",
        description="auto | json_schema | prompt",
    )


class AttributionConfig(BaseModel):
    """Attribution look-back window + confidence gate (REQ-023, REQ-030)."""

    lookback_messages: int = Field(
        default=8, ge=1, le=100, description="Messages of context for attribution"
    )
    min_confidence: float = Field(
        default=0.6, ge=0.0, le=1.0, description="Drop facts below this attribution confidence"
    )


class SentimentConfig(BaseModel):
    """Sentiment scoring toggle (REQ-031 — metadata only)."""

    enabled: bool = Field(default=True, description="Store sentiment as fact metadata")


class ScoringConfig(BaseModel):
    """Novelty / importance scoring thresholds (REQ-033 to REQ-036)."""

    dedup_novelty_max: float = Field(
        default=0.08,
        ge=0.0,
        le=1.0,
        description="novelty <= this => merge (same fact), no insert",
    )
    importance_increment_below: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="novelty <= this (and > dedup) => insert new + bump neighbour",
    )
    importance_cap: int = Field(
        default=10000, ge=1, description="Upper bound on the importance counter"
    )


class CadenceConfig(BaseModel):
    """Per-user extraction batching cadence (REQ-015, REQ-021)."""

    batch_max_size: int = Field(
        default=6, ge=1, le=100, description="Flush batch when this many messages buffered"
    )
    batch_idle_seconds: float = Field(
        default=20.0, ge=0.0, description="Flush batch after this idle gap"
    )
    max_facts_per_batch: int = Field(
        default=5, ge=1, le=50, description="Cap on facts extracted per batch"
    )
    max_inflight_batches_per_user: int = Field(
        default=2, ge=1, le=20, description="Bound concurrent extraction batches per user (CON-004)"
    )


class RetrievalBoostConfig(BaseModel):
    """Importance + recency + confidence blend applied to retrieval ranking (REQ-037, REQ-295)."""

    importance_weight: float = Field(
        default=0.2, ge=0.0, le=1.0, description="Weight of normalised log-importance"
    )
    recency_weight: float = Field(
        default=0.1, ge=0.0, le=1.0, description="Weight of the recency factor"
    )
    recency_half_life_days: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Exponential recency half-life in days (Sprint 20, REQ-405). "
            "0 = legacy hyperbolic formula. 90 = recommended starting value."
        ),
    )
    confidence_weight: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Weight of the fact confidence score (Sprint 13, Sortie 4, REQ-297). "
            "0.0 = current behaviour (no confidence weighting)."
        ),
    )


class ExtractorConfig(BaseModel):
    """Fact-extractor configuration (Phase 7f).

    ``type: heuristic`` (default) reproduces Phase 7 behaviour exactly; the
    ``llm`` subtree and all scoring/cadence fields are only read when
    ``type == "llm"`` (CON-002). Omitting ``extractor`` entirely is equivalent
    to ``{"type": "heuristic"}``.
    """

    type: str = Field(default="heuristic", description="heuristic | llm")
    heuristic_pregate: bool = Field(
        default=True, description="Run the cheap safety+candidate gate before the LLM (REQ-020)"
    )
    llm: ExtractorLLMConfig | None = Field(
        default=None, description="Dedicated extractor LLM connection (required when type==llm)"
    )
    structured_output: StructuredOutputConfig = Field(default_factory=StructuredOutputConfig)
    attribution: AttributionConfig = Field(default_factory=AttributionConfig)
    sentiment: SentimentConfig = Field(default_factory=SentimentConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    cadence: CadenceConfig = Field(default_factory=CadenceConfig)
    retrieval_boost: RetrievalBoostConfig = Field(default_factory=RetrievalBoostConfig)


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

    # Sprint 11: Adaptive engagement (REQ-220–249)
    eagerness: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum engagement score required to speak on an auto-participation turn. "
            "0.0 = current behavior (count-threshold only). "
            "Raise gradually; monitor fire-rate vs. signal metrics (REQ-241)."
        ),
    )
    force_interval: int = Field(
        default=0,
        ge=0,
        description=(
            "Force a speak after this many consecutive score-misses to prevent permanent silence "
            "(REQ-243). 0 = disabled."
        ),
    )

    class EngagementWeightsConfig(BaseModel):
        """Per-component weights for the engagement score (REQ-225)."""

        novelty: float = Field(default=0.5, ge=0.0, le=1.0, description="Weight for novelty signal")
        topical: float = Field(
            default=0.3, ge=0.0, le=1.0, description="Weight for topical-memory similarity"
        )
        mood: float = Field(
            default=0.1, ge=0.0, le=1.0, description="Weight for ambient-mood cosine"
        )
        importance: float = Field(
            default=0.1, ge=0.0, le=1.0, description="Weight for max speaker-fact importance"
        )
        max_bias: float = Field(
            default=1.0,
            ge=1.0,
            le=5.0,
            description=(
                "Multiplicative bias ceiling for users the bot knows well (REQ-247). "
                "1.0 = no bias. Start at 1.2–1.5 if enabling."
            ),
        )

    class PrecheckConfig(BaseModel):
        """Silent-path pre-check thresholds (REQ-230–235)."""

        enabled: bool = Field(
            default=False,
            description=(
                "Enable cheap two-signal pre-check on the auto-participation path. "
                "Default off = current behavior."
            ),
        )
        min_novelty: float = Field(
            default=0.0,
            ge=0.0,
            le=1.0,
            description=(
                "Minimum novelty (1 − top-1 similarity) to pass pre-check. " "0.0 = signal ignored."
            ),
        )
        min_mood_cosine: float = Field(
            default=0.0,
            ge=0.0,
            le=1.0,
            description="Minimum ambient mood cosine to pass pre-check. 0.0 = signal ignored.",
        )

    engagement: EngagementWeightsConfig = Field(
        default_factory=EngagementWeightsConfig,
        description="Engagement score component weights (Sprint 11)",
    )
    precheck: PrecheckConfig = Field(
        default_factory=PrecheckConfig,
        description="Silent-path pre-check configuration (Sprint 11)",
    )


class MediaChangeConfig(BaseModel):
    """Configuration for media change triggers."""

    enabled: bool = Field(default=False, description="Enable media change triggers")
    min_duration_minutes: int = Field(
        default=10, ge=1, le=240, description="Minimum duration in minutes for triggering"
    )
    chat_context_depth: int = Field(
        default=10, ge=1, le=50, description="Number of chat messages to include in context"
    )
    transition_explanation: str = Field(
        default="The media has just changed.",
        max_length=200,
        description="Explanation text for the transition",
    )


class TemplatesConfig(BaseModel):
    """Jinja2 template configuration."""

    dir: str = Field(default="templates", description="Directory containing template files")
    system: str = Field(default="system.j2", description="System prompt template")
    default_trigger: str = Field(default="trigger.j2", description="Default user trigger template")
    media_change: str = Field(default="media_change.j2", description="Media change prompt template")


# ============================================================================
# Sprint 10: Memory Privacy & Governance
# ============================================================================


# ============================================================================
# Sprint 18: Temporal Confidence Drift
# ============================================================================


class ConfidenceDriftConfig(BaseModel):
    """Temporal confidence drift sweeper configuration (Sprint 18, REQ-380\u2013384).

    When enabled, a background sweep periodically nudges confidence downward for
    facts whose ``last_seen`` timestamp is older than ``drift_after_days``, by
    ``drift_rate_per_day * dormant_days``.  Floored at ``confidence_floor``.

    Default off (\u201cenabled: false\u201d) so existing deployments are unaffected.
    """

    enabled: bool = Field(
        default=False, description="Enable temporal confidence drift (default off)"
    )
    drift_after_days: float = Field(
        default=30.0,
        ge=1.0,
        description="Confidence drift starts after this many dormant days",
    )
    drift_rate_per_day: float = Field(
        default=0.001,
        ge=0.0,
        le=0.1,
        description="Confidence reduction per dormant day (e.g. 0.001 = 0.1%/day)",
    )
    confidence_floor: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Minimum confidence after drift (same floor as contradiction decay)",
    )
    interval_hours: float = Field(
        default=24.0,
        ge=0.1,
        description="Drift sweep interval in hours",
    )


# ============================================================================
# Sprint 19: Semantic Fact Compaction
# ============================================================================


class CompactionConfig(BaseModel):
    """Semantic fact compaction sweeper configuration (Sprint 19, REQ-395–399).

    When enabled, a background sweep periodically merges near-duplicate facts
    (cosine similarity ≥ ``merge_threshold``) into a single canonical fact.

    Default off (``enabled: false``) so existing deployments are unaffected.
    """

    enabled: bool = Field(default=False, description="Enable compaction sweeper (default off)")
    interval_hours: float = Field(
        default=24.0, ge=0.1, description="Compaction sweep interval in hours"
    )
    min_facts_to_compact: int = Field(
        default=10, ge=1, description="Skip users with fewer than this many facts"
    )
    merge_threshold: float = Field(
        default=0.85,
        ge=0.5,
        le=1.0,
        description="Cosine similarity threshold for merging (0.85 = conservative)",
    )
    importance_cap: int = Field(default=10000, ge=1, description="Maximum merged importance value")


# ============================================================================
# Sprint 15: Memory-Aware Model Routing
# ============================================================================


class SignalWeightsConfig(BaseModel):
    """Per-component weights for ContextSignal computation (Sprint 15, REQ-313).

    Weights need not sum to 1; compute_signal normalises by total weight.
    Default weights give fragment_count the most influence, with the other
    three components equally weighted.
    """

    fragment_count: float = Field(
        default=0.4, ge=0.0, le=1.0, description="Weight for normalised memory fragment count"
    )
    budget_fraction: float = Field(
        default=0.2, ge=0.0, le=1.0, description="Weight for context budget fraction used"
    )
    avg_confidence: float = Field(
        default=0.2, ge=0.0, le=1.0, description="Weight for average fact confidence proxy"
    )
    trigger_priority: float = Field(
        default=0.2, ge=0.0, le=1.0, description="Weight for normalised trigger priority"
    )
    fragment_count_max: int = Field(
        default=8, ge=1, description="Fragment count cap for normalisation"
    )


class RoutingConfig(BaseModel):
    """Memory-aware model routing configuration (Sprint 15, REQ-310–329).

    When ``enabled = False`` (default) or ``tiers`` is empty, routing is a
    no-op and the existing ``default_provider_priority`` order is used.
    Raise ``signal_threshold`` after observing the signal distribution in
    production via ``llm_routing_signal`` histogram.
    """

    enabled: bool = Field(default=False, description="Enable signal-based routing (default off)")
    signal_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Signal value at or above which the 'premium' tier is used. "
            "0.0 = single-tier (current behaviour, REQ-316/319)."
        ),
    )
    tiers: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "Tier name → provider priority list. Recognised names: 'economy', 'premium'. "
            "Empty = single tier (current behaviour, REQ-319)."
        ),
    )
    signal: SignalWeightsConfig = Field(
        default_factory=SignalWeightsConfig,
        description="Per-component signal weights (REQ-313)",
    )


class RetentionConfig(BaseModel):
    """Retention sweeper configuration (Sprint 10, Sortie 2, REQ-180–186).

    When enabled, a background task periodically expires facts that are both
    old (age > max_age_days) and low-value (importance <= expire_below_importance).
    Defaults to disabled so existing deployments are unaffected.
    """

    enabled: bool = Field(default=False, description="Enable retention sweeper (default off)")
    interval_hours: float = Field(default=24.0, ge=0.1, description="Sweep interval in hours")
    max_age_days: int = Field(
        default=180, ge=1, description="Maximum fact age in days before expiry eligibility"
    )
    expire_below_importance: int = Field(
        default=0,
        ge=0,
        description=(
            "Expire facts with importance <= this value. "
            "0 = age-only expiry (importance criterion disabled)."
        ),
    )
    batch_size: int = Field(default=500, ge=1, description="Maximum IDs to delete per batch")


class MemoryCommandsConfig(BaseModel):
    """Runtime memory command authorisation (Sprint 10, Sorties 1 & 5, REQ-170–179, 210–215).

    Controls who may issue ``forget.user`` and ``inspect.user`` on
    ``kryten.llm.command``.
    """

    forget_min_rank: int = Field(
        default=2,
        ge=0,
        description="Minimum caller rank to forget another user (2 = moderator)",
    )
    inspect_limit: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Maximum facts returned by inspect.user",
    )


class SelfServiceConfig(BaseModel):
    """In-chat self-service memory access (Sprint 10, Sorties 4 & 5, REQ-200–213).

    Feature-flagged; default off.  When enabled, users may trigger
    ``forget me`` or ``what do you know about me`` in chat to manage their
    own stored facts without requiring shell or NATS access.
    """

    enabled: bool = Field(
        default=False, description="Enable self-service forget/inspect phrases (default off)"
    )
    phrase: str = Field(
        default="forget me",
        description="Phrase (case-insensitive substring) triggering self-service forget",
    )
    inspect_phrase: str = Field(
        default="what do you know about me",
        description="Phrase triggering self-service inspection",
    )
    cooldown_seconds: int = Field(
        default=300,
        ge=0,
        description="Minimum seconds between self-service operations per user",
    )


class LLMConfig(KrytenConfig):
    """Extended configuration for kryten-llm service.

    Inherits NATS and channel configuration from KrytenConfig.
    Adds LLM-specific settings for personality, providers, triggers, etc.

    Phase 3 enhancements: Multi-provider support with fallback, retry strategy,
    and default provider priority order (REQ-002, REQ-003, REQ-021).
    """

    # LLM-specific configuration
    templates: TemplatesConfig = Field(
        default_factory=TemplatesConfig, description="Template settings"
    )
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
    ignored_users: list[str] = Field(
        default_factory=list,
        description=(
            "Usernames to completely ignore — messages are dropped before any processing. "
            "Use for economy bots, game bots, or other non-human accounts."
        ),
    )

    # Sprint 10: Memory Privacy & Governance
    retention: RetentionConfig = Field(
        default_factory=RetentionConfig,
        description="Memory retention sweeper configuration (Sprint 10)",
    )

    # Sprint 15: Memory-Aware Model Routing
    routing: RoutingConfig = Field(
        default_factory=RoutingConfig,
        description="Memory-aware model routing configuration (Sprint 15)",
    )

    # Sprint 18: Temporal Confidence Drift
    confidence_drift: "ConfidenceDriftConfig" = Field(
        default_factory=lambda: ConfidenceDriftConfig(),
        description="Temporal confidence drift sweeper configuration (Sprint 18)",
    )

    # Sprint 19: Semantic Fact Compaction
    compaction: CompactionConfig = Field(
        default_factory=CompactionConfig,
        description="Semantic fact compaction sweeper configuration (Sprint 19)",
    )

    memory_commands: MemoryCommandsConfig = Field(
        default_factory=MemoryCommandsConfig,
        description="Memory command authorisation settings (Sprint 10)",
    )
    self_service: SelfServiceConfig = Field(
        default_factory=SelfServiceConfig,
        description="Self-service in-chat memory access (Sprint 10)",
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
