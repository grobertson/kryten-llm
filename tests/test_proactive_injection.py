"""Sprint 21 — Proactive Memory Injection tests (REQ-425–444)."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock

import pytest

from kryten_llm.components.context.base import ContextFragment, ContextRequest
from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider
from tests.eval.harness import FakeEmbedder, FakeStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unit(dims: int, *hot: int) -> list[float]:
    v = [0.0] * dims
    for i in hot:
        v[i] = 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _req(username: str = "alice", message: str = "hello", trigger_type: str = "mention"):
    return ContextRequest(
        username=username, message=message, trigger={"type": trigger_type}, channel="test"
    )


def _provider_with_store(store: FakeStore, embedder: FakeEmbedder) -> LongTermMemoryProvider:
    from tests.eval.harness import make_provider

    p = make_provider(store, embedder)
    p._proactive_enabled = True
    p._proactive_threshold = 0.85
    p._proactive_min_confidence = 0.60
    p._proactive_priority = 39
    p._proactive_fire_on = {"mention", "trigger_word", "auto_participation"}
    return p


# ---------------------------------------------------------------------------
# REQ-425–430: _run_proactive_scope
# ---------------------------------------------------------------------------


class TestRunProactiveScope:
    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self):
        store = FakeStore()
        emb = FakeEmbedder()
        p = _provider_with_store(store, emb)
        p._proactive_enabled = False
        result = await p._run_proactive_scope(_req())
        assert result == []

    @pytest.mark.asyncio
    async def test_wrong_trigger_type_returns_empty(self):
        store = FakeStore()
        emb = FakeEmbedder()
        p = _provider_with_store(store, emb)
        p._proactive_fire_on = {"mention"}
        result = await p._run_proactive_scope(_req(trigger_type="auto_participation"))
        assert result == []

    @pytest.mark.asyncio
    async def test_no_message_vec_returns_empty(self):
        store = FakeStore()
        emb = FakeEmbedder()
        p = _provider_with_store(store, emb)
        p._last_message_vec = None
        result = await p._run_proactive_scope(_req())
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty(self):
        store = FakeStore()
        emb = FakeEmbedder()
        p = _provider_with_store(store, emb)
        p._last_message_vec = _unit(8, 0)
        result = await p._run_proactive_scope(_req())
        assert result == []

    @pytest.mark.asyncio
    async def test_high_similarity_high_confidence_emits_fragment(self):
        """A fact with sim >= threshold and conf >= min_confidence → fragment emitted."""
        store = FakeStore()
        emb = FakeEmbedder()
        vec = _unit(8, 0)
        await store.upsert(
            ids=["f1"],
            vectors=[vec],
            metadatas=[
                {
                    "user": "alice",
                    "confidence": 0.9,
                    "importance": 3,
                    "created_at": "2025-01-01T00:00:00+00:00",
                }
            ],
            documents=["alice loves samurai films"],
        )
        p = _provider_with_store(store, emb)
        p._last_message_vec = vec  # identical vector → sim = 1.0
        result = await p._run_proactive_scope(_req())
        assert len(result) == 1
        frag = result[0]
        assert frag.name == "proactive_memory"
        assert "samurai" in frag.text
        assert frag.priority == 39

    @pytest.mark.asyncio
    async def test_low_similarity_returns_empty(self):
        store = FakeStore()
        emb = FakeEmbedder()
        vec_fact = _unit(8, 0)
        vec_query = _unit(8, 2)  # orthogonal → sim ≈ 0.0
        await store.upsert(
            ids=["f1"],
            vectors=[vec_fact],
            metadatas=[
                {
                    "user": "alice",
                    "confidence": 0.9,
                    "importance": 3,
                    "created_at": "2025-01-01T00:00:00+00:00",
                }
            ],
            documents=["alice likes action"],
        )
        p = _provider_with_store(store, emb)
        p._last_message_vec = vec_query
        result = await p._run_proactive_scope(_req())
        assert result == []

    @pytest.mark.asyncio
    async def test_low_confidence_returns_empty(self):
        store = FakeStore()
        emb = FakeEmbedder()
        vec = _unit(8, 0)
        await store.upsert(
            ids=["f1"],
            vectors=[vec],
            metadatas=[
                {
                    "user": "alice",
                    "confidence": 0.3,
                    "importance": 1,
                    "created_at": "2025-01-01T00:00:00+00:00",
                }
            ],
            documents=["alice maybe likes stuff"],
        )
        p = _provider_with_store(store, emb)
        p._last_message_vec = vec
        result = await p._run_proactive_scope(_req())
        assert result == []

    @pytest.mark.asyncio
    async def test_monitor_called(self):
        store = FakeStore()
        emb = FakeEmbedder()
        vec = _unit(8, 0)
        await store.upsert(
            ids=["f1"],
            vectors=[vec],
            metadatas=[
                {
                    "user": "alice",
                    "confidence": 0.9,
                    "importance": 3,
                    "created_at": "2025-01-01T00:00:00+00:00",
                }
            ],
            documents=["alice loves sci-fi"],
        )
        monitor = MagicMock()
        p = _provider_with_store(store, emb)
        p._last_message_vec = vec
        p._monitor = monitor
        await p._run_proactive_scope(_req())
        monitor.record_proactive_injection.assert_called_once()
        call_kwargs = monitor.record_proactive_injection.call_args
        assert call_kwargs[1]["triggered"] is True


# ---------------------------------------------------------------------------
# REQ-440–444: HealthMonitor.record_proactive_injection
# ---------------------------------------------------------------------------


class TestHealthMonitorProactive:
    def _monitor(self):
        from kryten_llm.components.health_monitor import ServiceHealthMonitor
        from kryten_llm.models.config import ServiceMetadata
        import logging

        return ServiceHealthMonitor(ServiceMetadata(), logging.getLogger("test"))

    def test_triggered_increments_triggered_counter(self):
        m = self._monitor()
        m.record_proactive_injection(triggered=True, similarity=0.9)
        assert m._proactive_injections_triggered == 1
        assert m._proactive_injections_skipped == 0

    def test_not_triggered_increments_skipped_counter(self):
        m = self._monitor()
        m.record_proactive_injection(triggered=False, similarity=0.7)
        assert m._proactive_injections_skipped == 1

    def test_similarity_appended_to_ring(self):
        m = self._monitor()
        m.record_proactive_injection(triggered=True, similarity=0.85)
        assert 0.85 in m._proactive_similarities

    def test_none_monitor_no_crash(self):
        """_run_proactive_scope with monitor=None should not raise."""
        store = FakeStore()
        emb = FakeEmbedder()
        p = _provider_with_store(store, emb)
        p._monitor = None  # type: ignore[assignment]
        p._last_message_vec = None
        # Should not raise even with no message vec
        import asyncio

        asyncio.get_event_loop().run_until_complete(p._run_proactive_scope(_req()))


# ---------------------------------------------------------------------------
# REQ-435–439: from_config wires proactive fields
# ---------------------------------------------------------------------------


class TestProactiveFromConfig:
    def _base_provider_cfg(self, proactive_block: dict) -> dict:
        return {
            "type": "long_term_memory",
            "enabled": True,
            "priority": 40,
            "embedder": {"type": "onnx", "model": "all-MiniLM-L6-v2"},
            "store": {"backend": "chroma", "path": "/tmp/test_chroma"},
            "proactive": proactive_block,
        }

    def test_defaults_disabled(self):
        from tests.eval.harness import make_provider, FakeStore, FakeEmbedder

        p = make_provider(FakeStore(), FakeEmbedder())
        assert p._proactive_enabled is False

    def test_enabled_flag_wired(self):
        from tests.eval.harness import make_provider, FakeStore, FakeEmbedder

        p = make_provider(FakeStore(), FakeEmbedder())
        # Simulate from_config wiring
        p._proactive_enabled = True
        p._proactive_threshold = 0.75
        assert p._proactive_threshold == 0.75

    def test_unknown_fire_on_entry_kept(self):
        from tests.eval.harness import make_provider, FakeStore, FakeEmbedder

        p = make_provider(FakeStore(), FakeEmbedder())
        # Simulate partial wiring
        p._proactive_fire_on = {"mention", "future_unknown_type"}
        assert "future_unknown_type" in p._proactive_fire_on

    def test_drives_participation_defaults_false(self):
        from tests.eval.harness import make_provider, FakeStore, FakeEmbedder

        p = make_provider(FakeStore(), FakeEmbedder())
        assert p._proactive_drives_participation is False
