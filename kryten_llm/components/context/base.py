"""Base interfaces for the context provider framework.

Phase 7a: REQ-001 through REQ-007.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class ContextRequest:
    """Encapsulates everything a provider needs to produce context.

    Passed to every provider's :meth:`provide` call.
    """

    username: str
    message: str
    trigger: dict[str, Any] | None
    channel: str


@dataclass
class ContextFragment:
    """A single named, prioritised piece of context produced by a provider.

    The pipeline collects all fragments, sorts by ``priority`` (descending),
    and trims lowest-priority fragments first when the global character budget
    is exceeded (REQ-005).
    """

    name: str
    """Stable identifier, e.g. ``"user_memory"`` or ``"recent_chat"``."""

    priority: int
    """Higher value = kept first under budget pressure."""

    text: str | None = None
    """Pre-rendered text for injection into the prompt."""

    data: Any = None
    """Optional structured payload (e.g. for Jinja2 templates that prefer dicts)."""

    est_chars: int = 0
    """Estimated character cost for budget accounting.

    If zero, the pipeline estimates it from ``len(text)`` at trim time.
    """


@runtime_checkable
class ContextProvider(Protocol):
    """Protocol that every context provider must satisfy.

    REQ-001: Defines the uniform interface.
    REQ-006: Providers declare *reads* and/or *writes* so the pipeline can
    route correctly:

    * ``reads=True``  → ``provide()`` is called during prompt build.
    * ``writes=True`` → ``observe()`` is called for every qualifying inbound
                         message (off the critical response path).
    """

    id: str
    reads: bool
    writes: bool

    async def observe(self, username: str, message: str) -> None:
        """Ingest an inbound message (WRITE path).

        No-op for read-only providers.  Implementations MUST NOT raise — they
        should log and swallow errors so the pipeline's fail-open guarantee
        (REQ-004) holds end-to-end.
        """
        ...

    async def provide(self, req: ContextRequest) -> list[ContextFragment]:
        """Produce zero or more context fragments (READ path).

        Implementations MUST NOT raise (REQ-004).  Return an empty list on
        error after logging.
        """
        ...


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

#: Maps config ``type`` strings → provider classes.
PROVIDER_REGISTRY: dict[str, type] = {}


def register_provider(type_key: str):
    """Class decorator that registers a provider under *type_key*."""

    def _decorator(cls):
        PROVIDER_REGISTRY[type_key] = cls
        return cls

    return _decorator
