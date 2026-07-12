"""Tests for the ContextPipeline (Phase 7a — REQ-002 to REQ-007)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from kryten_llm.components.context.base import (
    PROVIDER_REGISTRY,
    ContextFragment,
    ContextRequest,
)
from kryten_llm.components.context.pipeline import ContextPipeline


# ---------------------------------------------------------------------------
# Helpers / Stub providers
# ---------------------------------------------------------------------------


class _StubProvider:
    """Simple always-succeeds read-only provider for testing."""

    reads = True
    writes = False

    def __init__(self, fragment_id: str, priority: int, text: str):
        self.id = fragment_id
        self._priority = priority
        self._text = text

    async def observe(self, username: str, message: str) -> None:
        pass

    async def provide(self, req: ContextRequest) -> list[ContextFragment]:
        return [
            ContextFragment(
                name=self.id,
                priority=self._priority,
                text=self._text,
                est_chars=len(self._text),
            )
        ]


class _ErrorProvider:
    """Provider that always raises on provide() — tests fail-open."""

    id = "error_provider"
    reads = True
    writes = False

    async def observe(self, username: str, message: str) -> None:
        pass

    async def provide(self, req: ContextRequest) -> list[ContextFragment]:
        raise RuntimeError("intentional test error")


class _WriteProvider:
    """Provider that tracks observe() calls."""

    id = "write_provider"
    reads = False
    writes = True

    def __init__(self):
        self.observed: list[tuple[str, str]] = []

    async def observe(self, username: str, message: str) -> None:
        self.observed.append((username, message))

    async def provide(self, req: ContextRequest) -> list[ContextFragment]:
        return []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestContextPipeline:
    def _make_req(self, username="testuser", message="test message"):
        return ContextRequest(
            username=username,
            message=message,
            trigger=None,
            channel="test",
        )

    # --- REQ-004: Fail-open ---

    @pytest.mark.asyncio
    async def test_error_provider_does_not_block_others(self):
        """A failing provider must not block the rest (REQ-004)."""
        good = _StubProvider("good", priority=50, text="good context")
        bad = _ErrorProvider()

        pipeline = ContextPipeline(providers=[good, bad], context_window_chars=10_000)
        ctx = await pipeline.build(self._make_req())

        # Good provider's fragment should still be in context
        assert ctx.get("good") == "good context"

    # --- REQ-005: Budget trimming ---

    @pytest.mark.asyncio
    async def test_budget_trims_low_priority_first(self):
        """Low-priority fragments should be dropped when budget is exceeded (REQ-005)."""
        high = _StubProvider("high_prio", priority=90, text="H" * 50)
        low = _StubProvider("low_prio", priority=10, text="L" * 50)

        # Budget can fit exactly one 50-char fragment
        pipeline = ContextPipeline(providers=[low, high], context_window_chars=50)
        ctx = await pipeline.build(self._make_req())

        assert "high_prio" in ctx
        assert "low_prio" not in ctx

    @pytest.mark.asyncio
    async def test_budget_keeps_all_if_fits(self):
        """Both fragments kept if they fit within budget."""
        a = _StubProvider("a", priority=80, text="A" * 50)
        b = _StubProvider("b", priority=40, text="B" * 50)

        pipeline = ContextPipeline(providers=[a, b], context_window_chars=200)
        ctx = await pipeline.build(self._make_req())

        assert "a" in ctx
        assert "b" in ctx

    # --- REQ-006: Write routing ---

    @pytest.mark.asyncio
    async def test_observe_routes_to_write_providers(self):
        """observe() should call write providers only (REQ-006)."""
        wp = _WriteProvider()
        ro = _StubProvider("read_only", priority=50, text="context")

        pipeline = ContextPipeline(providers=[wp, ro], context_window_chars=10_000)
        await pipeline.observe("alice", "hello world")

        assert ("alice", "hello world") in wp.observed

    @pytest.mark.asyncio
    async def test_observe_does_not_call_read_only(self):
        """Read-only provider's observe() should not be called meaningfully."""
        ro = _StubProvider("read_only", priority=50, text="context")
        observe_called = []

        original_observe = ro.observe

        async def spy_observe(u, m):
            observe_called.append((u, m))
            return await original_observe(u, m)

        ro.observe = spy_observe

        pipeline = ContextPipeline(providers=[ro], context_window_chars=10_000)
        # _StubProvider has writes=False, so the pipeline should skip it
        await pipeline.observe("alice", "hello world")
        assert observe_called == []

    # --- REQ-007: Default providers ---

    def test_from_config_defaults_to_video_and_chat(self, llm_config):
        """Without context.providers, pipeline must default to video+chat_history (REQ-007)."""
        # llm_config has no providers list configured
        from kryten_llm.components.context_manager import ContextManager

        cm = ContextManager(llm_config)
        pipeline = ContextPipeline.from_config(
            llm_config, deps={"context_manager": cm}
        )

        provider_ids = {p.id for p in pipeline.providers}
        assert "video" in provider_ids
        assert "chat_history" in provider_ids

    # --- Backwards-compat output shape ---

    @pytest.mark.asyncio
    async def test_merge_fragments_contains_defaults(self):
        """Empty pipeline still returns backward-compatible context keys."""
        pipeline = ContextPipeline(providers=[], context_window_chars=10_000)
        ctx = await pipeline.build(self._make_req())

        # Legacy keys must always be present
        assert "current_video" in ctx
        assert "next_video" in ctx
        assert "recent_messages" in ctx
        assert "channel_users" in ctx
        assert "active_users" in ctx
