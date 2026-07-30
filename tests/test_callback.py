"""Tests for callback / long-tail resurfacing (Sprint 8, Sortie 5 — REQ-090..097)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from kryten_llm.components.context.base import ContextRequest
from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider


class _FakeEmbedder:
    id = "fake"
    dimension = 3

    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    async def embed(self, texts):
        return [self.mapping.get(t, [0.0, 1.0, 0.0]) for t in texts]


class _FakeStore:
    def __init__(self, rows):
        self.rows = rows

    async def query(self, vector, k, where=None):
        return []  # no speaker facts surface; focus on callbacks

    async def get_all(self, where=None):
        return [dict(r) for r in self.rows]


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _row(fid, doc, importance, days_ago, user="alice"):
    return {
        "id": fid,
        "document": doc,
        "metadata": {
            "user": user,
            "category": "history",
            "importance": importance,
            "created_at": _iso(days_ago),
        },
    }


def _provider(rows, embedder=None, **cb):
    cfg = {
        "enabled": True,
        "probability": 1.0,
        "min_importance": 3,
        "min_age_days": 14,
        "max_similarity_to_topic": 1.0,
        "cooldown_turns": 20,
    }
    cfg.update(cb)
    return LongTermMemoryProvider(
        embedder=embedder or _FakeEmbedder(),
        vector_store=_FakeStore(rows),
        extractor=None,
        extractor_cfg=None,
        min_similarity=0.0,
        callback_cfg=cfg,
    )


def _req(msg="anything", channel="lounge"):
    return ContextRequest(username="alice", message=msg, trigger=None, channel=channel)


def _cb(frags):
    return next((f for f in frags if f.name == "callback_memory"), None)


class TestCallback:
    async def test_resurfaces_old_important_fact(self):
        rows = [_row("h1", "ran the old channel movie nights", importance=4, days_ago=60)]
        frag = _cb(await _provider(rows).provide(_req()))
        assert frag is not None
        assert "You also remember" in frag.text
        assert "movie nights" in frag.text

    async def test_recent_fact_excluded(self):
        rows = [_row("h1", "recent thing", importance=5, days_ago=2)]  # too recent
        assert _cb(await _provider(rows).provide(_req())) is None

    async def test_low_importance_excluded(self):
        rows = [_row("h1", "trivial old thing", importance=1, days_ago=90)]
        assert _cb(await _provider(rows).provide(_req())) is None

    async def test_probability_zero_never_fires(self):
        rows = [_row("h1", "old important", importance=5, days_ago=90)]
        assert _cb(await _provider(rows, probability=0.0).provide(_req())) is None

    async def test_topic_similar_fact_skipped(self):
        # candidate doc embeds identical to the query -> similarity 1.0 > 0.6 threshold
        emb = _FakeEmbedder({"kung fu": [1.0, 0.0, 0.0], "old kung fu memory": [1.0, 0.0, 0.0]})
        rows = [_row("h1", "old kung fu memory", importance=5, days_ago=90)]
        provider = _provider(rows, embedder=emb, max_similarity_to_topic=0.6)
        assert _cb(await provider.provide(_req(msg="kung fu"))) is None

    async def test_cooldown_suppresses_second_call(self):
        rows = [_row("h1", "old important", importance=5, days_ago=90)]
        provider = _provider(rows, cooldown_turns=5)
        first = _cb(await provider.provide(_req()))
        second = _cb(await provider.provide(_req()))
        assert first is not None
        assert second is None  # cooldown active

    async def test_disabled_by_default(self):
        provider = LongTermMemoryProvider(
            embedder=_FakeEmbedder(),
            vector_store=_FakeStore([_row("h1", "x", 5, 90)]),
            extractor=None,
            extractor_cfg=None,
            min_similarity=0.0,
        )
        assert _cb(await provider.provide(_req())) is None
