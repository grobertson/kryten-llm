"""Tests for attention-weighted pooling (Sprint 9, Sortie 4 — REQ-150..155)."""

from __future__ import annotations

from kryten_llm.components.context.base import ContextRequest
from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider


class _RecordingEmbedder:
    id = "rec"
    dimension = 3

    def __init__(self, mapping):
        self.mapping = mapping

    async def embed(self, texts):
        return [self.mapping.get(t, [0.0, 0.0, 0.0]) for t in texts]


class _Msg:
    def __init__(self, message):
        self.username = "u"
        self.message = message


class _CM:
    def __init__(self, messages):
        self.chat_history = [_Msg(m) for m in messages]


def _req(msg="last"):
    return ContextRequest(username="dave", message=msg, trigger=None, channel="lounge")


class TestSalience:
    def test_longer_message_more_salient(self):
        short = LongTermMemoryProvider._salience(":thumbsup:", 0, 2)
        long = LongTermMemoryProvider._salience("this is a much longer substantive sentence", 1, 2)
        assert long > short

    def test_empty_text_zero_salience(self):
        assert LongTermMemoryProvider._salience("", 0, 1) == 0.0


class TestAttentionPool:
    async def test_attention_downweights_low_signal_line(self):
        # A substantive kung-fu message + a bare emote; attention should keep the
        # kung-fu signal dominant despite the emote being newest.
        emb = _RecordingEmbedder(
            {
                "kung fu movies are the best action cinema ever made": [1.0, 0.0, 0.0],
                ":thumbsup:": [0.0, 0.0, 1.0],
            }
        )
        provider = LongTermMemoryProvider(
            embedder=emb,
            vector_store=None,
            extractor=None,
            extractor_cfg=None,
            query_mode="window",
            window_size=6,
            window_pooling="attention",
            context_manager=_CM(
                ["kung fu movies are the best action cinema ever made", ":thumbsup:"]
            ),
        )
        vec = await provider._message_query_vector(_req(":thumbsup:"))
        assert vec is not None
        # kung-fu axis (x) dominates the emote axis (z)
        assert vec[0] > vec[2]

    async def test_mean_strategy_matches_plain_mean(self):
        emb = _RecordingEmbedder({"a": [2.0, 0.0, 0.0], "b": [0.0, 2.0, 0.0]})
        provider = LongTermMemoryProvider(
            embedder=emb,
            vector_store=None,
            extractor=None,
            extractor_cfg=None,
            query_mode="window",
            window_size=6,
            window_pooling="mean",
            context_manager=_CM(["a", "b"]),
        )
        vec = await provider._message_query_vector(_req("b"))
        assert vec == [1.0, 1.0, 0.0]  # plain centroid, recency weight ignored

    async def test_attention_single_vector(self):
        p = _dummy_provider()
        assert p._attention_pool([[1.0, 2.0, 3.0]], ["solo"], 0.0) == [1.0, 2.0, 3.0]


def _dummy_provider():
    return LongTermMemoryProvider(
        embedder=_RecordingEmbedder({}),
        vector_store=None,
        extractor=None,
        extractor_cfg=None,
    )
