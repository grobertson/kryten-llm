"""Tests for cross-user boost ranking (Sprint 9, Sortie 1 — REQ-120..124)."""

from __future__ import annotations

from kryten_llm.components.context.base import ContextRequest
from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider
from kryten_llm.models.config import ExtractorConfig


class _FakeEmbedder:
    id = "fake"
    dimension = 3

    async def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class _FakeStore:
    """Returns seeded rows in insertion order (honours $ne user filter)."""

    def __init__(self, rows):
        self.rows = rows

    async def query(self, vector, k, where=None):
        out = []
        for r in self.rows:
            user = r["metadata"].get("user")
            if where and "user" in where:
                cond = where["user"]
                if isinstance(cond, dict):
                    if "$ne" in cond and user == cond["$ne"]:
                        continue
                elif user != cond:
                    continue
            out.append(dict(r))
        return out[:k]


def _llm_cfg() -> ExtractorConfig:
    return ExtractorConfig.model_validate(
        {
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
        }
    )


def _row(fid, user, importance):
    return {
        "id": fid,
        "document": f"{user} fact",
        "metadata": {"user": user, "category": "preference", "importance": importance},
        "distance": 0.0,  # equal similarity for all
    }


def _provider(rows, *, boost=True):
    return LongTermMemoryProvider(
        embedder=_FakeEmbedder(),
        vector_store=_FakeStore(rows),
        extractor=None,
        extractor_cfg=_llm_cfg(),  # LLM mode → boost available
        min_similarity=0.0,
        cross_user_enabled=True,
        topical_cfg={
            "enabled": True,
            "fire_on": ["auto_participation"],
            "top_k": 1,
            "min_similarity": 0.0,
            "exclude_speaker": True,
            "boost_ranking": boost,
        },
    )


def _req():
    return ContextRequest(
        username="dave", message="hi", trigger={"type": "auto_participation"}, channel="lounge"
    )


def _topical(frags):
    return next((f for f in frags if f.name == "topical_memory"), None)


# Store order: alice first, bob second; equal similarity; bob far more important.
ROWS = [_row("a1", "alice", importance=1), _row("b1", "bob", importance=8)]


class TestCrossUserBoost:
    async def test_boost_surfaces_higher_importance(self):
        frag = _topical(await _provider(ROWS, boost=True).provide(_req()))
        assert frag is not None
        # top_k=1: the boosted (more important) bob wins over the earlier alice
        assert "bob" in frag.text
        assert "alice" not in frag.text

    async def test_without_boost_keeps_store_order(self):
        frag = _topical(await _provider(ROWS, boost=False).provide(_req()))
        assert frag is not None
        # top_k=1 with no boost: store order → alice (first) is kept
        assert "alice" in frag.text
        assert "bob" not in frag.text
