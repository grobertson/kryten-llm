"""Tests for userlist-based presence (Sprint 9, Sortie 2 — REQ-130..135)."""

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

    async def query(self, vector, k, where=None):
        out = []
        for r in self.rows:
            user = r["metadata"].get("user")
            if where and "user" in where:
                cond = where["user"]
                if isinstance(cond, dict):
                    if "$in" in cond and user not in cond["$in"]:
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


class _FakeClient:
    def __init__(self, users, *, raise_exc=None):
        self._users = users
        self._raise = raise_exc
        self.calls = 0

    async def kv_get(self, bucket, key, default=None, parse_json=False):
        self.calls += 1
        if self._raise:
            raise self._raise
        return self._users


class _Monitor:
    def __init__(self):
        self.presence_fallback = 0

    def record_memory_presence_fallback(self):
        self.presence_fallback += 1

    def record_memory_fragment(self, name):
        pass

    def record_memory_retrieval_time(self, s):
        pass

    def record_memory_silenced_excluded(self, n=1):
        pass

    def record_memory_gate_fail_closed(self):
        pass


def _row(fid, user):
    return {
        "id": fid,
        "document": f"{user} fact",
        "metadata": {"user": user, "category": "preference"},
        "distance": 0.0,
    }


ROWS = [_row("a1", "alice"), _row("b1", "bob"), _row("e1", "eve")]


def _provider(client, cm_users, *, monitor=None, source="userlist"):
    return LongTermMemoryProvider(
        embedder=_FakeEmbedder(),
        vector_store=_FakeStore(ROWS),
        extractor=None,
        extractor_cfg=None,
        min_similarity=0.0,
        cross_user_enabled=True,
        context_manager=_CM(cm_users),
        client=client,
        domain="cytu.be",
        channel="lounge",
        bot_name="cynthbot",
        health_monitor=monitor,
        room_cfg={
            "enabled": True,
            "fire_on": ["auto_participation"],
            "max_users": 4,
            "facts_per_user": 1,
            "min_similarity": 0.0,
            "presence_source": source,
            "presence_cache_ttl_s": 1000,
        },
    )


def _req(user="dave"):
    return ContextRequest(
        username=user, message="hi", trigger={"type": "auto_participation"}, channel="lounge"
    )


def _room(frags):
    return next((f for f in frags if f.name == "room_memory"), None)


class TestUserlistPresence:
    async def test_uses_userlist_when_available(self):
        # userlist has alice + eve (who never chatted); recent chat has only bob
        client = _FakeClient([{"name": "alice"}, {"name": "eve"}, {"name": "dave"}])
        frag = _room(await _provider(client, ["bob"]).provide(_req("dave")))
        assert frag is not None
        assert "alice" in frag.text and "eve" in frag.text
        assert "dave" not in frag.text  # speaker excluded

    async def test_falls_back_on_kv_error(self):
        client = _FakeClient(None, raise_exc=RuntimeError("kv down"))
        monitor = _Monitor()
        # recent chat has bob → fallback should surface bob
        frag = _room(await _provider(client, ["bob"], monitor=monitor).provide(_req("dave")))
        assert frag is not None
        assert "bob" in frag.text
        assert monitor.presence_fallback == 1

    async def test_empty_userlist_falls_back(self):
        client = _FakeClient([])  # empty userlist
        monitor = _Monitor()
        frag = _room(await _provider(client, ["bob"], monitor=monitor).provide(_req("dave")))
        assert frag is not None
        assert "bob" in frag.text
        assert monitor.presence_fallback == 1

    async def test_ttl_cache_avoids_second_read(self):
        client = _FakeClient([{"name": "alice"}])
        provider = _provider(client, ["bob"])
        await provider.provide(_req("dave"))
        await provider.provide(_req("dave"))
        assert client.calls == 1  # cached within TTL

    async def test_recent_activity_source_ignores_userlist(self):
        client = _FakeClient([{"name": "alice"}])
        frag = _room(
            await _provider(client, ["bob"], source="recent_activity").provide(_req("dave"))
        )
        assert frag is not None
        assert "bob" in frag.text
        assert client.calls == 0  # userlist never read
