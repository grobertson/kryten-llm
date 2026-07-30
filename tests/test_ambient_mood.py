"""Tests for ambient mood recall (Sprint 8, Sortie 7 — REQ-110..117)."""

from __future__ import annotations

from kryten_llm.components.context.base import ContextRequest
from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider


class _FakeEmbedder:
    id = "fake"
    dimension = 3

    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    async def embed(self, texts):
        return [self.mapping.get(t, [0.0, 0.0, 1.0]) for t in texts]


class _FakeStore:
    def __init__(self, rows):
        self.rows = rows

    async def query(self, vector, k, where=None):
        # Speaker scope passes a scalar user filter → return nothing; ambient
        # passes where=None → return all rows.
        if where and "user" in where:
            return []
        return [dict(r) for r in self.rows][:k]


class _FakeGate:
    def __init__(self, silenced):
        self._silenced = silenced

    async def silenced_users(self):
        return self._silenced


SYNTH = [1.0, 0.0, 0.0]


def _row(fid, user, doc, vec=SYNTH):
    return {
        "id": fid,
        "document": doc,
        "metadata": {"user": user, "category": "preference"},
        "distance": 0.0,
    }


def _provider(rows, *, warmup=2, gate=None, embedder=None):
    return LongTermMemoryProvider(
        embedder=embedder or _FakeEmbedder({"synthwave talk": SYNTH}),
        vector_store=_FakeStore(rows),
        extractor=None,
        extractor_cfg=None,
        min_similarity=0.0,
        cross_user_enabled=True,
        moderation_gate=gate,
        ambient_cfg={
            "enabled": True,
            "alpha": 1.0,
            "warmup_messages": warmup,
            "top_k": 3,
            "min_similarity": 0.0,
            "fire_on": ["auto_participation"],
            "priority": 26,
        },
    )


def _req(user="dave"):
    return ContextRequest(
        username=user, message="hi", trigger={"type": "auto_participation"}, channel="lounge"
    )


def _ambient(frags):
    return next((f for f in frags if f.name == "ambient_memory"), None)


ROWS = [_row("a1", "alice", "loves synthwave"), _row("b1", "bob", "runs plex")]


class TestAmbient:
    async def test_no_fragment_before_warmup(self):
        provider = _provider(ROWS, warmup=3)
        await provider.observe("alice", "synthwave talk")  # only 1 < warmup 3
        assert _ambient(await provider.provide(_req())) is None

    async def test_fires_after_warmup(self):
        provider = _provider(ROWS, warmup=2)
        await provider.observe("alice", "synthwave talk")
        await provider.observe("bob", "synthwave talk")
        frag = _ambient(await provider.provide(_req()))
        assert frag is not None
        assert "alice" in frag.text

    async def test_silenced_user_excluded(self):
        gate = _FakeGate(frozenset({"bob"}))
        provider = _provider(ROWS, warmup=1, gate=gate)
        await provider.observe("alice", "synthwave talk")
        frag = _ambient(await provider.provide(_req()))
        assert frag is not None
        assert "bob" not in frag.text
        assert "alice" in frag.text

    async def test_does_not_fire_on_mention(self):
        provider = _provider(ROWS, warmup=1)
        await provider.observe("alice", "synthwave talk")
        req = ContextRequest(
            username="dave", message="hi", trigger={"type": "mention"}, channel="lounge"
        )
        assert _ambient(await provider.provide(req)) is None

    async def test_off_when_cross_user_disabled(self):
        provider = LongTermMemoryProvider(
            embedder=_FakeEmbedder(),
            vector_store=_FakeStore(ROWS),
            extractor=None,
            extractor_cfg=None,
            min_similarity=0.0,
            cross_user_enabled=False,
            ambient_cfg={"enabled": True, "warmup_messages": 1},
        )
        await provider.observe("alice", "synthwave talk")
        assert _ambient(await provider.provide(_req())) is None
