"""Tests for topic-scoped cross-user recall (Sprint 8, Sortie 1 — REQ-050..057).

Uses in-memory fakes; no embedder model, store, or NATS required.
"""

from __future__ import annotations

from typing import Any

from kryten_llm.components.context.base import ContextRequest
from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider


class _FakeEmbedder:
    id = "fake"
    dimension = 3

    def __init__(self, mapping: dict[str, list[float]]):
        self.mapping = mapping

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.mapping.get(t, [9.0, 9.0, 9.0]) for t in texts]


def _l2(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


class _FakeStore:
    """Store that honours ``{"user": scalar | {"$ne": v}}`` and ``None`` filters."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    async def upsert(self, ids, vectors, metadatas, documents) -> None:
        for i, v, m, d in zip(ids, vectors, metadatas, documents):
            self.records[i] = {"vector": list(v), "metadata": dict(m), "document": d}

    def _matches(self, user: str, where: dict[str, Any] | None) -> bool:
        if not where or "user" not in where:
            return True
        cond = where["user"]
        if isinstance(cond, dict):
            if "$ne" in cond and user == cond["$ne"]:
                return False
            if "$in" in cond and user not in cond["$in"]:
                return False
            return True
        return user == cond

    async def query(self, vector, k, where=None):
        items = []
        for rid, rec in self.records.items():
            if not self._matches(rec["metadata"].get("user"), where):
                continue
            items.append(
                {
                    "id": rid,
                    "document": rec["document"],
                    "metadata": dict(rec["metadata"]),
                    "distance": _l2(vector, rec["vector"]),
                }
            )
        items.sort(key=lambda r: r["distance"])
        return items[:k]


class _FakeGate:
    def __init__(self, silenced):
        self._silenced = silenced

    async def silenced_users(self):
        return self._silenced


SYNTH = [1.0, 0.0, 0.0]
PLEX = [0.0, 1.0, 0.0]


def _provider(store, *, cross=True, gate=None, exclude_speaker=True, fail_closed=True):
    embedder = _FakeEmbedder({"tell me about synthwave": SYNTH})
    return LongTermMemoryProvider(
        embedder=embedder,
        vector_store=store,
        extractor=None,
        extractor_cfg=None,
        cross_user_enabled=cross,
        moderation_gate=gate,
        gate_fail_closed=fail_closed,
        topical_cfg={
            "enabled": True,
            "fire_on": ["auto_participation"],
            "top_k": 4,
            "min_similarity": 0.30,
            "exclude_speaker": exclude_speaker,
            "priority": 38,
        },
    )


async def _seed(store, fid, user, vector, doc):
    await store.upsert(
        ids=[fid],
        vectors=[vector],
        metadatas=[{"user": user, "category": "preference"}],
        documents=[doc],
    )


def _req(trigger_type="auto_participation", user="dave"):
    return ContextRequest(
        username=user,
        message="tell me about synthwave",
        trigger={"type": trigger_type},
        channel="lounge",
    )


def _topical(fragments):
    return next((f for f in fragments if f.name == "topical_memory"), None)


class TestTopicalRecall:
    async def test_fires_on_auto_participation(self):
        store = _FakeStore()
        await _seed(store, "a1", "alice", SYNTH, "loves synthwave")
        frags = await _provider(store).provide(_req("auto_participation"))
        frag = _topical(frags)
        assert frag is not None
        assert "[alice] loves synthwave" in frag.text

    async def test_does_not_fire_on_mention(self):
        store = _FakeStore()
        await _seed(store, "a1", "alice", SYNTH, "loves synthwave")
        frags = await _provider(store).provide(_req("mention"))
        assert _topical(frags) is None

    async def test_excludes_silenced_user(self):
        store = _FakeStore()
        await _seed(store, "a1", "alice", SYNTH, "loves synthwave")
        await _seed(store, "c1", "carol", SYNTH, "also loves synthwave")
        gate = _FakeGate(frozenset({"carol"}))
        frag = _topical(await _provider(store, gate=gate).provide(_req()))
        assert frag is not None
        assert "alice" in frag.text
        assert "carol" not in frag.text

    async def test_gate_failure_fail_closed_withholds(self):
        store = _FakeStore()
        await _seed(store, "a1", "alice", SYNTH, "loves synthwave")
        gate = _FakeGate(None)  # gate unavailable
        frags = await _provider(store, gate=gate, fail_closed=True).provide(_req())
        assert _topical(frags) is None

    async def test_gate_failure_fail_open_allows(self):
        store = _FakeStore()
        await _seed(store, "a1", "alice", SYNTH, "loves synthwave")
        gate = _FakeGate(None)
        frag = _topical(await _provider(store, gate=gate, fail_closed=False).provide(_req()))
        assert frag is not None
        assert "alice" in frag.text

    async def test_excludes_speaker_facts(self):
        store = _FakeStore()
        await _seed(store, "d1", "dave", SYNTH, "dave likes synthwave")
        await _seed(store, "a1", "alice", SYNTH, "alice likes synthwave")
        frag = _topical(await _provider(store, exclude_speaker=True).provide(_req()))
        assert frag is not None
        assert "dave" not in frag.text
        assert "alice" in frag.text

    async def test_off_by_default(self):
        store = _FakeStore()
        await _seed(store, "a1", "alice", SYNTH, "loves synthwave")
        frags = await _provider(store, cross=False).provide(_req())
        assert _topical(frags) is None

    async def test_dedup_against_speaker_fragment(self):
        # exclude_speaker=False so dave's fact is a topical candidate; it must be
        # removed because it already surfaced in the speaker (user_memory) scope.
        store = _FakeStore()
        await _seed(store, "d1", "dave", SYNTH, "dave likes synthwave")
        frags = await _provider(store, exclude_speaker=False).provide(_req())
        speaker = next((f for f in frags if f.name == "user_memory"), None)
        assert speaker is not None and "dave likes synthwave" in speaker.text
        assert _topical(frags) is None  # only candidate was the deduped speaker fact


# ---------------------------------------------------------------------------
# from_config gate wiring (Sortie 0, REQ-046)
# ---------------------------------------------------------------------------

import types  # noqa: E402

from kryten_llm.components.context.providers import long_term_memory as _ltm  # noqa: E402


def _config_with_channel():
    return types.SimpleNamespace(
        channels=[types.SimpleNamespace(domain="cytu.be", channel="lounge")]
    )


def _patch_builders(monkeypatch):
    monkeypatch.setattr(_ltm, "build_embedder", lambda cfg: _FakeEmbedder({}))
    monkeypatch.setattr(
        _ltm, "build_vector_store", lambda cfg, embedder_id="", dimension=0: _FakeStore()
    )


class TestFromConfigGateWiring:
    def test_gate_built_when_cross_user_enabled(self, monkeypatch):
        _patch_builders(monkeypatch)
        pcfg = {
            "type": "long_term_memory",
            "extractor": {"type": "heuristic"},
            "cross_user": {"enabled": True},
            "moderation_gate": {"enabled": True, "silence_actions": ["smute"]},
            "topical": {"enabled": True},
        }
        provider = _ltm.LongTermMemoryProvider.from_config(
            pcfg, _config_with_channel(), {"client": object()}
        )
        assert provider._cross_user_enabled is True
        assert provider._mod_gate is not None
        assert provider._mod_gate._domain == "cytu.be"
        assert provider._mod_gate._channel == "lounge"
        assert provider._topical_enabled is True

    def test_no_client_disables_cross_user(self, monkeypatch):
        _patch_builders(monkeypatch)
        pcfg = {
            "type": "long_term_memory",
            "extractor": {"type": "heuristic"},
            "cross_user": {"enabled": True},
            "topical": {"enabled": True},
        }
        provider = _ltm.LongTermMemoryProvider.from_config(pcfg, _config_with_channel(), {})
        assert provider._cross_user_enabled is False
        assert provider._mod_gate is None

    def test_disabled_by_default(self, monkeypatch):
        _patch_builders(monkeypatch)
        provider = _ltm.LongTermMemoryProvider.from_config(
            {"type": "long_term_memory", "extractor": {"type": "heuristic"}},
            _config_with_channel(),
            {"client": object()},
        )
        assert provider._cross_user_enabled is False
        assert provider._mod_gate is None
