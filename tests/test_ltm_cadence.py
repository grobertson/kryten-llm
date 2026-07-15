"""Cadence / batching tests for LongTermMemoryProvider (Phase 7f).

Covers REQ-020 (heuristic pre-gate), REQ-021 (size + idle flush),
REQ-022 (off critical path).
"""

from __future__ import annotations

import asyncio
from typing import Any

from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider
from kryten_llm.models.config import ExtractorConfig


class _RecordingExtractor:
    id = "llm"

    def __init__(self) -> None:
        self.calls: list[tuple[list[dict[str, Any]], str]] = []
        self.block = asyncio.Event()
        self.block.set()

    async def extract(self, messages, user):
        await self.block.wait()
        self.calls.append((list(messages), user))
        return []


class _NoopEmbedder:
    id = "noop"
    dimension = 3

    async def embed(self, texts):
        return [[0.0, 0.0, 0.0] for _ in texts]


class _NoopStore:
    async def upsert(self, ids, vectors, metadatas, documents):
        pass

    async def query(self, vector, k, where=None):
        return []

    async def count(self, where=None):
        return 0

    async def delete(self, where):
        pass


def _cfg(**cadence: Any) -> ExtractorConfig:
    return ExtractorConfig.model_validate(
        {
            "type": "llm",
            "llm": {
                "providers": {
                    "x": {
                        "name": "x",
                        "type": "openai_compatible",
                        "base_url": "http://localhost:1/v1",
                        "api_key": "k",
                        "model": "m",
                    }
                }
            },
            "cadence": cadence or {"batch_max_size": 3, "batch_idle_seconds": 10},
        }
    )


def _provider(extractor, cfg):
    return LongTermMemoryProvider(
        embedder=_NoopEmbedder(),
        vector_store=_NoopStore(),
        extractor=extractor,
        extractor_cfg=cfg,
    )


_QUALIFYING = "i really enjoy watching classic kung fu movies"


class TestPreGate:
    async def test_non_candidate_never_batched(self):
        ex = _RecordingExtractor()
        p = _provider(ex, _cfg(batch_max_size=1))
        await p.observe("Alice", "lol")  # reaction — fails is_candidate
        await asyncio.sleep(0.01)
        assert ex.calls == []

    async def test_pii_never_batched(self):
        ex = _RecordingExtractor()
        p = _provider(ex, _cfg(batch_max_size=1))
        await p.observe("Alice", "reach me at alice@example.com any time please")
        await asyncio.sleep(0.01)
        assert ex.calls == []


class TestFlush:
    async def test_flush_on_size(self):
        ex = _RecordingExtractor()
        p = _provider(ex, _cfg(batch_max_size=3, batch_idle_seconds=100))
        for _ in range(3):
            await p.observe("Alice", _QUALIFYING)
        await asyncio.sleep(0.02)
        assert len(ex.calls) == 1
        _window, user = ex.calls[0]
        assert user == "Alice"

    async def test_flush_on_idle(self):
        ex = _RecordingExtractor()
        p = _provider(ex, _cfg(batch_max_size=100, batch_idle_seconds=0.05))
        await p.observe("Alice", _QUALIFYING)
        await p.observe("Alice", _QUALIFYING)
        assert ex.calls == []  # not yet flushed
        await asyncio.sleep(0.12)
        assert len(ex.calls) == 1

    async def test_lookback_window_includes_other_authors(self):
        ex = _RecordingExtractor()
        p = _provider(ex, _cfg(batch_max_size=1))
        await p.observe("Bob", "hey what's up")  # context, not a fact candidate necessarily
        await p.observe("Alice", _QUALIFYING)
        await asyncio.sleep(0.02)
        assert len(ex.calls) == 1
        window, _user = ex.calls[0]
        authors = {m["username"] for m in window}
        assert "Bob" in authors and "Alice" in authors


class TestOffCriticalPath:
    async def test_observe_returns_while_extractor_blocks(self):
        ex = _RecordingExtractor()
        ex.block.clear()  # extractor will hang
        p = _provider(ex, _cfg(batch_max_size=1))
        # observe must return promptly even though extraction is blocked.
        await asyncio.wait_for(p.observe("Alice", _QUALIFYING), timeout=0.5)
        await asyncio.sleep(0.02)
        assert ex.calls == []  # still blocked
        ex.block.set()
        await asyncio.sleep(0.02)
        assert len(ex.calls) == 1
