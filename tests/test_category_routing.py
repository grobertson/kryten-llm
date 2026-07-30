"""Tests for category-routed speaker recall (Sprint 8, Sortie 4 — REQ-080..086)."""

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
        self._rows = rows

    async def query(self, vector, k, where=None):
        # Speaker scope only; return seeded rows (already "for this user").
        return [dict(r) for r in self._rows][:k]


def _row(fid, category, doc):
    return {
        "id": fid,
        "document": doc,
        "metadata": {"user": "alice", "category": category},
        "distance": 0.0,
    }


def _provider(rows, cat_cfg, *, top_k=10):
    return LongTermMemoryProvider(
        embedder=_FakeEmbedder(),
        vector_store=_FakeStore(rows),
        extractor=None,
        extractor_cfg=None,
        top_k=top_k,
        min_similarity=0.0,
        category_routing_cfg=cat_cfg,
    )


def _req():
    return ContextRequest(username="alice", message="hi", trigger=None, channel="lounge")


def _frag(frags, name):
    return next((f for f in frags if f.name == name), None)


ROWS = [
    _row("p1", "preference", "loves synthwave"),
    _row("p2", "preference", "hates jump-scares"),
    _row("s1", "skill", "runs a Plex server"),
    _row("h1", "history", "modded the old channel"),
]


class TestCategoryRouting:
    async def test_disabled_is_flat(self):
        provider = _provider(ROWS, {"enabled": False})
        frags = await provider.provide(_req())
        frag = _frag(frags, "user_memory")
        assert frag is not None
        assert frag.text.startswith("Known facts about alice:")

    async def test_sections_mode_labels_and_order(self):
        cfg = {
            "enabled": True,
            "mode": "sections",
            "order": ["preference", "skill", "history"],
            "labels": {"preference": "Preferences", "skill": "Skills", "history": "History"},
            "per_category_top_k": {"default": 2},
        }
        frag = _frag(await _provider(ROWS, cfg).provide(_req()), "user_memory")
        assert frag is not None
        assert "Known about alice:" in frag.text
        # order preserved: Preferences before Skills before History
        assert (
            frag.text.index("Preferences") < frag.text.index("Skills") < frag.text.index("History")
        )
        assert "loves synthwave · hates jump-scares" in frag.text

    async def test_per_category_cap(self):
        cfg = {
            "enabled": True,
            "mode": "sections",
            "order": ["preference"],
            "per_category_top_k": {"default": 1},
        }
        frag = _frag(await _provider(ROWS, cfg).provide(_req()), "user_memory")
        assert frag is not None
        assert "loves synthwave" in frag.text
        assert "hates jump-scares" not in frag.text  # capped at 1

    async def test_fragments_mode_emits_per_category(self):
        cfg = {
            "enabled": True,
            "mode": "fragments",
            "order": ["preference", "skill", "history"],
            "priority": {"preference": 42, "history": 36, "default": 34},
        }
        frags = await _provider(ROWS, cfg).provide(_req())
        pref = _frag(frags, "user_memory_preference")
        skill = _frag(frags, "user_memory_skill")
        hist = _frag(frags, "user_memory_history")
        assert pref is not None and skill is not None and hist is not None
        assert pref.priority == 42
        assert hist.priority == 36
        assert skill.priority == 34  # falls back to default

    async def test_unknown_category_gets_default_label(self):
        rows = [_row("m1", "misc", "likes weird stuff")]
        cfg = {
            "enabled": True,
            "mode": "sections",
            "order": [],
            "per_category_top_k": {"default": 2},
        }
        frag = _frag(await _provider(rows, cfg).provide(_req()), "user_memory")
        assert frag is not None
        assert "Misc: likes weird stuff" in frag.text
