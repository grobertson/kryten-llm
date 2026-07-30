from dataclasses import dataclass


@dataclass
class TriggerResult:
    """Result of trigger detection."""

    triggered: bool
    trigger_type: str | None = None
    trigger_name: str | None = None
    cleaned_message: str | None = None
    context: str | dict | None = None
    priority: int = 5
    history: list[dict] | None = None
    preferred_provider: str | None = None
    """Preferred LLM provider for this trigger (Phase 3, REQ-004)."""
    preferred_tier: str | None = None
    """Routing tier override for this trigger (Sprint 15, REQ-325–329)."""

    def __bool__(self) -> bool:
        return self.triggered
