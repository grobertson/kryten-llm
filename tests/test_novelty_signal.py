"""Tests for the novelty / contradiction signal (Sprint 8, Sortie 6 — REQ-100..105)."""

from __future__ import annotations

from kryten_llm.components.context.base import ContextRequest
from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider


class _FakeEmbedder:
    id = "fake"
    dimension = 3

    async def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class _FakeStore:
    def __init__(self, rows):
        self.rows = rows
        self.query_calls = 0

    async def query(self, vector, k, where=None):
        self.query_calls += 1
        return [dict(r) for r in self.rows][:k]


def _row(fid, doc, distance):
    return {
        "id": fid,
        "document": doc,
        "metadata": {"user": "alice", "category": "preference"},
        "distance": distance,
    }


def _provider(rows, **novelty):
    cfg = {"enabled": True}
    cfg.update(novelty)
    return LongTermMemoryProvider(
        embedder=_FakeEmbedder(),
        vector_store=_FakeStore(rows),
        extractor=None,
        extractor_cfg=None,
        min_similarity=0.0,
        novelty_cfg=cfg,
    )


def _req(msg="I play guitar now"):
    return ContextRequest(username="alice", message=msg, trigger=None, channel="lounge")


def _signal(frags):
    return next((f for f in frags if f.name == "memory_signal"), None)


class TestNoveltySignal:
    async def test_novel_when_nearest_is_far(self):
        # distance 0.9 -> similarity 0.1 < novelty_max_similarity 0.35
        provider = _provider([_row("a", "loves horror movies", 0.9)])
        frag = _signal(await provider.provide(_req("I play guitar now")))
        assert frag is not None
        assert "seems new for alice" in frag.text

    async def test_contradiction_when_close_and_opposite(self):
        # distance 0.1 -> similarity 0.9 > 0.80, and polarity differs (message negates)
        provider = _provider([_row("a", "loves horror movies", 0.1)])
        frag = _signal(await provider.provide(_req("I do not love horror anymore")))
        assert frag is not None
        assert "update what you knew" in frag.text

    async def test_no_signal_for_routine_on_topic(self):
        # close (sim 0.9) but same polarity -> neither novel nor contradiction
        provider = _provider([_row("a", "loves horror movies", 0.1)])
        assert _signal(await provider.provide(_req("I love horror movies"))) is None

    async def test_no_extra_store_query(self):
        store = _FakeStore([_row("a", "loves horror", 0.9)])
        provider = LongTermMemoryProvider(
            embedder=_FakeEmbedder(),
            vector_store=store,
            extractor=None,
            extractor_cfg=None,
            min_similarity=0.0,
            novelty_cfg={"enabled": True},
        )
        await provider.provide(_req())
        assert store.query_calls == 1  # signal reuses the speaker query

    async def test_disabled_by_default(self):
        provider = LongTermMemoryProvider(
            embedder=_FakeEmbedder(),
            vector_store=_FakeStore([_row("a", "loves horror", 0.9)]),
            extractor=None,
            extractor_cfg=None,
            min_similarity=0.0,
        )
        assert _signal(await provider.provide(_req())) is None

    async def test_polarity_helper(self):
        assert LongTermMemoryProvider._polarity_differs("I do not like it", "likes it")
        assert not LongTermMemoryProvider._polarity_differs("likes it", "loves it")
