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


def _cfg(*, attribution: dict[str, Any] | None = None, **cadence: Any) -> ExtractorConfig:
    body: dict[str, Any] = {
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
    if attribution is not None:
        body["attribution"] = attribution
    return ExtractorConfig.model_validate(body)


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


class TestSafetyPreGate:
    async def test_pii_never_enters_the_lookback_window(self):
        # CON-001: a PII message must not reach the LLM even as context.
        ex = _RecordingExtractor()
        p = _provider(ex, _cfg(batch_max_size=1))
        await p.observe("Bob", "my email is bob@example.com call me")
        await p.observe("Alice", _QUALIFYING)
        await asyncio.sleep(0.02)
        assert len(ex.calls) == 1
        window, _user = ex.calls[0]
        joined = " ".join(m["message"] for m in window)
        assert "bob@example.com" not in joined
        assert all("@" not in m["message"] for m in window)

    async def test_safety_gate_applies_even_without_heuristic_pregate(self):
        ex = _RecordingExtractor()
        p = _provider(ex, _pregate_off_cfg())
        await p.observe("Bob", "reach me at bob@example.com")
        await p.observe("Alice", "the weather today is pleasant and mild outside")
        await asyncio.sleep(0.02)
        assert len(ex.calls) == 1
        window, _user = ex.calls[0]
        joined = " ".join(m["message"] for m in window)
        assert "bob@example.com" not in joined


class TestLookbackTrim:
    async def test_window_trimmed_to_lookback_messages(self):
        ex = _RecordingExtractor()
        # lookback=1 with batch_max_size=1: the deque holds 2 but the window
        # sent to the LLM must be trimmed to the most recent 1.
        p = _provider(ex, _cfg(batch_max_size=1, attribution={"lookback_messages": 1}))
        await p.observe("Alice", _QUALIFYING)
        await p.observe("Alice", _QUALIFYING + " again")
        await asyncio.sleep(0.02)
        assert ex.calls  # at least one flush happened
        last_window, _user = ex.calls[-1]
        assert len(last_window) == 1


class TestBufferBound:
    async def test_buffer_bounded_when_extractor_hangs(self):
        # CON-004: with a hung extractor and in-flight cap 1, the per-user
        # buffer must not grow without bound.
        ex = _RecordingExtractor()
        ex.block.clear()  # never completes -> in-flight stays occupied
        cfg = _cfg(batch_max_size=2, batch_idle_seconds=100, max_inflight_batches_per_user=1)
        p = _provider(ex, cfg)
        for _ in range(12):
            await p.observe("Alice", _QUALIFYING)
            await asyncio.sleep(0)
        max_buf = 2 * 1
        assert len(p._batches["Alice"]) <= max_buf
        # Cleanup: release the extractor and cancel any pending idle timer.
        ex.block.set()
        p._cancel_idle("Alice")
        await asyncio.sleep(0)


def _pregate_off_cfg() -> ExtractorConfig:
    return ExtractorConfig.model_validate(
        {
            "type": "llm",
            "heuristic_pregate": False,
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
            "cadence": {"batch_max_size": 1, "batch_idle_seconds": 100},
        }
    )

