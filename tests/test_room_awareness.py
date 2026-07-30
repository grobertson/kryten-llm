"""Tests for room-awareness recall (Sprint 8, Sortie 2 — REQ-060..065)."""

from __future__ import annotations

from kryten_llm.components.context.base import ContextRequest
from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider


class _FakeEmbedder:
    id = "fake"
    dimension = 3

    async def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class _FakeStore:
    """Honours ``{"user": {"$in": [...]}}`` filters."""

    def __init__(self, rows):
        self._rows = rows

    async def query(self, vector, k, where=None):
        out = []
        for r in self._rows:
            user = r["metadata"].get("user")
            if where and "user" in where:
                cond = where["user"]
                if isinstance(cond, dict):
                    if "$in" in cond and user not in cond["$in"]:
                        continue
                    if "$ne" in cond and user == cond["$ne"]:
                        continue
                elif user != cond:
                    continue
            out.append(dict(r))
        return out[:k]


class _Msg:
    def __init__(self, username):
        self.username = username
        self.message = "hi"


class _CM:
    def __init__(self, usernames):
        self.chat_history = [_Msg(u) for u in usernames]


class _FakeGate:
    def __init__(self, silenced):
        self._silenced = silenced

    async def silenced_users(self):
        return self._silenced


def _row(fid, user, doc):
    return {
        "id": fid,
        "document": doc,
        "metadata": {"user": user, "category": "preference"},
        "distance": 0.0,
    }


def _provider(rows, usernames, *, gate=None, max_users=4, facts_per_user=1, bot="cynthbot"):
    return LongTermMemoryProvider(
        embedder=_FakeEmbedder(),
        vector_store=_FakeStore(rows),
        extractor=None,
        extractor_cfg=None,
        min_similarity=0.0,
        cross_user_enabled=True,
        moderation_gate=gate,
        context_manager=_CM(usernames),
        bot_name=bot,
        room_cfg={
            "enabled": True,
            "fire_on": ["auto_participation"],
            "window_messages": 20,
            "max_users": max_users,
            "facts_per_user": facts_per_user,
            "min_similarity": 0.0,
            "priority": 30,
        },
    )


def _req(trigger_type="auto_participation", user="dave"):
    return ContextRequest(
        username=user, message="hi", trigger={"type": trigger_type}, channel="lounge"
    )


def _room(frags):
    return next((f for f in frags if f.name == "room_memory"), None)


ROWS = [
    _row("a1", "alice", "alice loves synthwave"),
    _row("b1", "bob", "bob runs a Plex server"),
    _row("c1", "carol", "carol hates jump-scares"),
    _row("d1", "dave", "dave likes kung fu"),
]


class TestRoomAwareness:
    async def test_surfaces_other_active_users(self):
        # speaker=dave; active alice/bob/carol
        provider = _provider(ROWS, ["alice", "bob", "carol", "dave"])
        frag = _room(await provider.provide(_req(user="dave")))
        assert frag is not None
        assert "alice" in frag.text and "bob" in frag.text and "carol" in frag.text
        assert "dave" not in frag.text  # speaker excluded

    async def test_excludes_bot(self):
        provider = _provider(ROWS, ["alice", "cynthbot", "dave"], bot="cynthbot")
        frag = _room(await provider.provide(_req(user="dave")))
        assert frag is not None
        assert "cynthbot" not in frag.text.lower()

    async def test_silenced_user_excluded(self):
        gate = _FakeGate(frozenset({"carol"}))
        provider = _provider(ROWS, ["alice", "carol", "dave"], gate=gate)
        frag = _room(await provider.provide(_req(user="dave")))
        assert frag is not None
        assert "carol" not in frag.text
        assert "alice" in frag.text

    async def test_max_users_cap(self):
        provider = _provider(ROWS, ["alice", "bob", "carol", "dave"], max_users=1)
        frag = _room(await provider.provide(_req(user="dave")))
        assert frag is not None
        # only the single most-recent other user (carol was last before dave)
        assert frag.text.count("•") == 1

    async def test_does_not_fire_on_mention(self):
        provider = _provider(ROWS, ["alice", "bob", "dave"])
        frags = await provider.provide(_req(trigger_type="mention", user="dave"))
        assert _room(frags) is None

    async def test_off_when_cross_user_disabled(self):
        provider = LongTermMemoryProvider(
            embedder=_FakeEmbedder(),
            vector_store=_FakeStore(ROWS),
            extractor=None,
            extractor_cfg=None,
            min_similarity=0.0,
            cross_user_enabled=False,
            context_manager=_CM(["alice", "bob", "dave"]),
            room_cfg={"enabled": True},
        )
        assert _room(await provider.provide(_req(user="dave"))) is None
