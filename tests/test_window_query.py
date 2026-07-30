"""Tests for the windowed query vector (Sprint 8, Sortie 3 — REQ-070..075)."""

from __future__ import annotations

from kryten_llm.components.context.base import ContextRequest
from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider


class _RecordingEmbedder:
    id = "rec"
    dimension = 3

    def __init__(self, mapping):
        self.mapping = mapping
        self.last_texts: list[str] | None = None

    async def embed(self, texts):
        self.last_texts = list(texts)
        return [self.mapping.get(t, [0.0, 0.0, 0.0]) for t in texts]


class _Msg:
    def __init__(self, username, message):
        self.username = username
        self.message = message


class _CM:
    def __init__(self, messages):
        self.chat_history = [_Msg(u, m) for u, m in messages]


def _provider(embedder, *, query_mode="message", window_size=6, recency=0.0, cm=None):
    return LongTermMemoryProvider(
        embedder=embedder,
        vector_store=None,
        extractor=None,
        extractor_cfg=None,
        context_manager=cm,
        query_mode=query_mode,
        window_size=window_size,
        window_recency_weight=recency,
    )


def _req(msg="last line"):
    return ContextRequest(username="dave", message=msg, trigger=None, channel="lounge")


class TestPooling:
    def test_pool_plain_mean(self):
        pooled = LongTermMemoryProvider._pool([[0.0, 0.0, 0.0], [2.0, 4.0, 6.0]], 0.0)
        assert pooled == [1.0, 2.0, 3.0]

    def test_pool_single_vector(self):
        assert LongTermMemoryProvider._pool([[1.0, 2.0, 3.0]], 0.5) == [1.0, 2.0, 3.0]

    def test_pool_recency_weight_favours_newest(self):
        # newest (last) vector should dominate with a positive recency weight
        pooled = LongTermMemoryProvider._pool([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], 0.5)
        assert pooled[0] > 0.5


class TestWindowQueryVector:
    async def test_message_mode_embeds_single_message(self):
        emb = _RecordingEmbedder({"last line": [1.0, 0.0, 0.0]})
        provider = _provider(emb, query_mode="message")
        vec = await provider._message_query_vector(_req("last line"))
        assert vec == [1.0, 0.0, 0.0]
        assert emb.last_texts == ["last line"]

    async def test_window_mode_pools_recent_messages(self):
        emb = _RecordingEmbedder(
            {"kung fu movies rule": [1.0, 0.0, 0.0], ":thumbsup:": [0.0, 0.0, 1.0]}
        )
        cm = _CM([("alice", "kung fu movies rule"), ("dave", ":thumbsup:")])
        provider = _provider(emb, query_mode="window", window_size=6, cm=cm)
        vec = await provider._message_query_vector(_req(":thumbsup:"))
        # Pooled over both messages, so the kung-fu signal is retained even though
        # the last literal line was a bare emote.
        assert vec == [0.5, 0.0, 0.5]
        assert emb.last_texts == ["kung fu movies rule", ":thumbsup:"]

    async def test_window_mode_empty_history_falls_back_to_message(self):
        emb = _RecordingEmbedder({"solo": [0.2, 0.2, 0.2]})
        provider = _provider(emb, query_mode="window", cm=_CM([]))
        vec = await provider._message_query_vector(_req("solo"))
        assert vec == [0.2, 0.2, 0.2]
        assert emb.last_texts == ["solo"]

    async def test_window_respects_window_size(self):
        emb = _RecordingEmbedder({})
        cm = _CM([("u", f"m{i}") for i in range(10)])
        provider = _provider(emb, query_mode="window", window_size=3, cm=cm)
        await provider._message_query_vector(_req("m9"))
        assert emb.last_texts == ["m7", "m8", "m9"]  # only the last 3
