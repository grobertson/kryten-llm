"""Scoring & persistence tests for LongTermMemoryProvider (Phase 7f).

Covers REQ-030 (confidence gate), REQ-032 (mechanical novelty), REQ-033 (merge),
REQ-034 (related-mention), REQ-035/036 (novel insert + importance cap),
REQ-037 (retrieval boost), CON-003 (safety re-check).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider
from kryten_llm.components.memory.extractor import ExtractedFact
from kryten_llm.models.config import ExtractorConfig


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeEmbedder:
    id = "fake-embedder"
    dimension = 3

    def __init__(self, mapping: dict[str, list[float]] | None = None):
        self.mapping = mapping or {}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.mapping.get(t, [float(len(t)), 0.0, 0.0]) for t in texts]


def _l2(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


class _FakeStore:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    async def upsert(self, ids, vectors, metadatas, documents) -> None:
        for i, v, m, d in zip(ids, vectors, metadatas, documents):
            self.records[i] = {"vector": list(v), "metadata": dict(m), "document": d}

    async def query(self, vector, k, where=None):
        items = []
        for rid, rec in self.records.items():
            if where and rec["metadata"].get("user") != where.get("user"):
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

    async def get_metadata(self, ids):
        return [dict(self.records[i]["metadata"]) for i in ids if i in self.records]

    async def update_metadata(self, ids, metadatas):
        for i, m in zip(ids, metadatas):
            if i in self.records:
                self.records[i]["metadata"] = dict(m)

    async def count(self, where=None):
        if where:
            return sum(
                1 for r in self.records.values() if r["metadata"].get("user") == where.get("user")
            )
        return len(self.records)

    async def delete(self, where) -> None:  # pragma: no cover - unused here
        pass


def _cfg(**overrides: Any) -> ExtractorConfig:
    base: dict[str, Any] = {
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
    base.update(overrides)
    return ExtractorConfig.model_validate(base)


def _provider(embedder: _FakeEmbedder, store: _FakeStore, cfg: ExtractorConfig):
    return LongTermMemoryProvider(
        embedder=embedder,
        vector_store=store,
        extractor=None,
        extractor_cfg=cfg,
    )


def _ef(summary: str, user: str = "u", confidence: float = 0.9, sentiment: float = 0.7):
    return ExtractedFact(
        target_user=user,
        category="preference",
        summary=summary,
        confidence=confidence,
        sentiment=sentiment,
        evidence={"index": 0, "time": "", "message": summary},
    )


async def _seed(store: _FakeStore, fid: str, user: str, vector: list[float], importance: int = 1):
    await store.upsert(
        ids=[fid],
        vectors=[vector],
        metadatas=[{"user": user, "category": "preference", "importance": importance}],
        documents=["seed"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConfidenceAndSafety:
    async def test_low_confidence_dropped(self):
        store = _FakeStore()
        emb = _FakeEmbedder({"likes jazz": [0.5, 0, 0]})
        p = _provider(emb, store, _cfg())
        await p._persist(_ef("likes jazz", confidence=0.3))
        assert await store.count() == 0

    async def test_pii_summary_dropped(self):
        store = _FakeStore()
        emb = _FakeEmbedder({"email me at a@b.com": [0.5, 0, 0]})
        p = _provider(emb, store, _cfg())
        await p._persist(_ef("email me at a@b.com"))
        assert await store.count() == 0


class TestNoveltyDecisions:
    async def test_novel_fact_seeds_importance_one(self):
        store = _FakeStore()
        emb = _FakeEmbedder({"loves noir films": [0.5, 0, 0]})
        p = _provider(emb, store, _cfg())
        await p._persist(_ef("loves noir films"))
        assert await store.count() == 1
        (rec,) = store.records.values()
        assert rec["metadata"]["importance"] == 1
        assert rec["metadata"]["confidence"] == 0.9
        assert rec["metadata"]["sentiment"] == 0.7
        assert rec["metadata"]["embedder_id"] == "fake-embedder"
        assert "novelty_at_write" in rec["metadata"]

    async def test_duplicate_merges_and_bumps_importance(self):
        store = _FakeStore()
        await _seed(store, "seed1", "u", [0.0, 0.0, 0.0], importance=1)
        emb = _FakeEmbedder({"same fact": [0.0, 0.0, 0.0]})  # distance 0 -> novelty 0
        p = _provider(emb, store, _cfg())
        await p._persist(_ef("same fact"))
        assert await store.count() == 1  # no new record
        assert store.records["seed1"]["metadata"]["importance"] == 2

    async def test_related_mention_inserts_and_bumps_neighbour(self):
        store = _FakeStore()
        await _seed(store, "seed1", "u", [0.0, 0.0, 0.0], importance=1)
        # distance 0.12 -> dedup(0.08) < novelty <= importance_increment_below(0.15)
        emb = _FakeEmbedder({"closely related fact": [0.12, 0.0, 0.0]})
        p = _provider(emb, store, _cfg())
        await p._persist(_ef("closely related fact"))
        assert await store.count() == 2  # new record inserted
        assert store.records["seed1"]["metadata"]["importance"] == 2  # neighbour bumped

    async def test_importance_capped(self):
        store = _FakeStore()
        await _seed(store, "seed1", "u", [0.0, 0.0, 0.0], importance=2)
        emb = _FakeEmbedder({"same fact": [0.0, 0.0, 0.0]})
        p = _provider(emb, store, _cfg(scoring={"importance_cap": 2}))
        await p._persist(_ef("same fact"))
        assert store.records["seed1"]["metadata"]["importance"] == 2  # capped


class TestRetrievalBoost:
    def _results(self, importance_a: int, importance_b: int, dist_a: float, dist_b: float):
        now = datetime.now(timezone.utc).isoformat()
        return [
            {
                "id": "a",
                "document": "fact a",
                "distance": dist_a,
                "metadata": {"category": "misc", "importance": importance_a, "last_seen": now},
            },
            {
                "id": "b",
                "document": "fact b",
                "distance": dist_b,
                "metadata": {"category": "misc", "importance": importance_b, "last_seen": now},
            },
        ]

    async def test_higher_importance_wins_on_equal_similarity(self):
        store = _FakeStore()
        emb = _FakeEmbedder()
        p = _provider(emb, store, _cfg())
        ranked = p._rank_with_boost(self._results(100, 1, 0.2, 0.2))
        assert ranked[0]["id"] == "a"

    async def test_importance_does_not_override_much_better_similarity(self):
        store = _FakeStore()
        emb = _FakeEmbedder()
        p = _provider(emb, store, _cfg())
        # b is far more similar (tiny distance) though low importance.
        ranked = p._rank_with_boost(self._results(100, 1, 0.9, 0.01))
        assert ranked[0]["id"] == "b"

    async def test_recency_factor_prefers_recent(self):
        store = _FakeStore()
        emb = _FakeEmbedder()
        p = _provider(emb, store, _cfg())
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=30)).isoformat()
        results = [
            {"id": "old", "document": "x", "distance": 0.2,
             "metadata": {"importance": 1, "last_seen": old}},
            {"id": "new", "document": "y", "distance": 0.2,
             "metadata": {"importance": 1, "last_seen": now.isoformat()}},
        ]
        ranked = p._rank_with_boost(results)
        assert ranked[0]["id"] == "new"
