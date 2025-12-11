from dataclasses import dataclass


@dataclass
class TriggerResult:
    """Result of trigger detection."""
    
    triggered: bool
    trigger_type: str | None = None
    trigger_name: str | None = None
    cleaned_message: str | None = None
    context: str | None = None
    priority: int = 5
    
    def __bool__(self) -> bool:
        return self.triggered
