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


class TestSameEvidenceGuard:
    """Importance bumps must NOT fire when the new fact's evidence message is
    identical to the one already stored (re-processed overlapping window).
    They MUST fire when the evidence is new (genuine corroboration).
    """

    async def _seed_ev(
        self, store: _FakeStore, fid: str, vec: list[float], evidence_msg: str
    ) -> None:
        """Seed a record that already has an evidence string in its metadata."""
        await store.upsert(
            ids=[fid],
            vectors=[vec],
            metadatas=[{
                "user": "u",
                "category": "preference",
                "importance": 1,
                "evidence": evidence_msg[:200],
            }],
            documents=["seed"],
        )

    def _ef_msg(self, summary: str, evidence_msg: str) -> "ExtractedFact":
        return ExtractedFact(
            target_user="u",
            category="preference",
            summary=summary,
            confidence=0.9,
            sentiment=0.7,
            evidence={"index": 0, "time": "", "message": evidence_msg},
        )

    # -- DEDUP branch ---------------------------------------------------

    async def test_dedup_same_evidence_skips_bump(self):
        """Re-processing the same source message must not bump importance."""
        ev = "I always found Species to be a total POS."
        store = _FakeStore()
        await self._seed_ev(store, "f1", [0.0, 0.0, 0.0], ev)
        emb = _FakeEmbedder({"dislikes Species": [0.0, 0.0, 0.0]})
        p = _provider(emb, store, _cfg())
        await p._persist(self._ef_msg("dislikes Species", ev))
        assert store.records["f1"]["metadata"]["importance"] == 1  # no bump

    async def test_dedup_different_evidence_bumps(self):
        """A new message corroborating the same fact must still bump importance."""
        store = _FakeStore()
        await self._seed_ev(store, "f1", [0.0, 0.0, 0.0], "original evidence message")
        emb = _FakeEmbedder({"dislikes Species": [0.0, 0.0, 0.0]})
        p = _provider(emb, store, _cfg())
        await p._persist(self._ef_msg("dislikes Species", "I still hate Species tbh"))
        assert store.records["f1"]["metadata"]["importance"] == 2  # genuine corroboration

    async def test_dedup_no_stored_evidence_still_bumps(self):
        """If stored evidence is empty (legacy records), bump as normal."""
        store = _FakeStore()
        # Legacy seed — no evidence field
        await _seed(store, "f1", "u", [0.0, 0.0, 0.0], importance=1)
        emb = _FakeEmbedder({"same fact": [0.0, 0.0, 0.0]})
        p = _provider(emb, store, _cfg())
        await p._persist(_ef("same fact"))
        assert store.records["f1"]["metadata"]["importance"] == 2

    # -- RELATED branch -------------------------------------------------

    async def test_related_same_evidence_skips_bump_inserts_new(self):
        """Same source message in a related hit: skip neighbour bump, still insert."""
        ev = "I watch Species every year"
        store = _FakeStore()
        await self._seed_ev(store, "f1", [0.0, 0.0, 0.0], ev)
        # distance 0.12 falls in RELATED zone (dedup_max=0.08 < 0.12 <= increment_below=0.15)
        emb = _FakeEmbedder({"dislikes but rewatches Species": [0.12, 0.0, 0.0]})
        p = _provider(emb, store, _cfg())
        await p._persist(self._ef_msg("dislikes but rewatches Species", ev))
        assert store.records["f1"]["metadata"]["importance"] == 1  # no bump
        assert await store.count() == 2  # new fact still inserted

    async def test_related_different_evidence_bumps_and_inserts(self):
        """New related message: bump neighbour AND insert new fact."""
        store = _FakeStore()
        await self._seed_ev(store, "f1", [0.0, 0.0, 0.0], "first mention")
        emb = _FakeEmbedder({"dislikes but rewatches Species": [0.12, 0.0, 0.0]})
        p = _provider(emb, store, _cfg())
        await p._persist(self._ef_msg("dislikes but rewatches Species", "second mention"))
        assert store.records["f1"]["metadata"]["importance"] == 2  # bumped
        assert await store.count() == 2  # new fact inserted


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
            {
                "id": "old",
                "document": "x",
                "distance": 0.2,
                "metadata": {"importance": 1, "last_seen": old},
            },
            {
                "id": "new",
                "document": "y",
                "distance": 0.2,
                "metadata": {"importance": 1, "last_seen": now.isoformat()},
            },
        ]
        ranked = p._rank_with_boost(results)
        assert ranked[0]["id"] == "new"


# ---------------------------------------------------------------------------
# Eviction key / _enforce_cap
# ---------------------------------------------------------------------------


class _CapStore(_FakeStore):
    """Extended fake store that supports get_all / delete_ids for cap tests."""

    async def get_all(self, where=None):
        results = []
        for rid, rec in self.records.items():
            if where and rec["metadata"].get("user") != where.get("user"):
                continue
            results.append(
                {"id": rid, "document": rec["document"], "metadata": dict(rec["metadata"])}
            )
        return results

    async def delete_ids(self, ids: list[str]) -> None:
        for i in ids:
            self.records.pop(i, None)


def _cap_fact(
    fid: str,
    user: str = "u",
    score: float | None = None,
    confidence: float = 0.5,
    importance: int = 1,
    created_at: str = "2026-01-01T00:00:00+00:00",
) -> tuple[str, dict]:
    """Return (id, metadata) for a cap-test record."""
    meta: dict = {
        "user": user,
        "category": "misc",
        "confidence": confidence,
        "importance": importance,
        "created_at": created_at,
    }
    if score is not None:
        meta["score"] = score
    return fid, meta


async def _seed_cap(store: _CapStore, *facts: tuple[str, dict]) -> None:
    for fid, meta in facts:
        await store.upsert(
            ids=[fid], vectors=[[0.1, 0.0, 0.0]], metadatas=[meta], documents=[fid]
        )


class TestEnforceCap:
    """_enforce_cap eviction: quality scoring and importance weighting."""

    def _provider_with_cap(self, store: _CapStore, cap: int = 3) -> LongTermMemoryProvider:
        return LongTermMemoryProvider(
            embedder=_FakeEmbedder(),
            vector_store=store,
            extractor=None,
            per_user_fact_cap=cap,
        )

    async def test_score_zero_stored_uses_confidence_not_zero(self):
        """Bug: score=0.0 stored in metadata must not override confidence.

        A fact with score=0 (heuristic default) but confidence=0.93 + importance=7
        should not be evicted before a genuinely low-quality fact (confidence=0.1).
        """
        store = _CapStore()
        # Well-corroborated fact — score=0 was stored by heuristic path but
        # confidence was bumped to 0.93 over 7 corroborations.
        fid_good, meta_good = _cap_fact("fargo", score=0.0, confidence=0.93, importance=7)
        # Low-quality uncorroborated fact.
        fid_bad, meta_bad = _cap_fact("junk", score=0.0, confidence=0.1, importance=1)
        # Filler to make count > cap.
        fid_fill, meta_fill = _cap_fact("fill", confidence=0.6, importance=1)
        await _seed_cap(store, (fid_good, meta_good), (fid_bad, meta_bad), (fid_fill, meta_fill))

        p = self._provider_with_cap(store, cap=2)
        await p._enforce_cap("u")

        # The junk fact (low confidence) must be evicted, not the Fargo fact.
        assert "junk" not in store.records, "low-quality fact should have been evicted"
        assert "fargo" in store.records, "corroborated fact must survive"

    async def test_llm_fact_no_score_field_uses_confidence(self):
        """LLM-path facts have no 'score' key; confidence×100 is used as quality."""
        store = _CapStore()
        # LLM fact: high confidence, no score stored.
        fid_llm, meta_llm = _cap_fact("llm_fact", confidence=0.9, importance=1)
        # Heuristic fact with low explicit score (and matching low confidence).
        fid_h, meta_h = _cap_fact("heuristic", score=5.0, confidence=0.05, importance=1)
        fid_fill, meta_fill = _cap_fact("fill", confidence=0.5, importance=1)
        await _seed_cap(store, (fid_llm, meta_llm), (fid_h, meta_h), (fid_fill, meta_fill))

        p = self._provider_with_cap(store, cap=2)
        await p._enforce_cap("u")

        assert "heuristic" not in store.records, "low-score heuristic fact should be evicted"
        assert "llm_fact" in store.records, "high-confidence LLM fact must survive"

    async def test_higher_importance_survives_equal_quality(self):
        """Among facts with the same quality, higher importance must be kept."""
        store = _CapStore()
        fid_hi, meta_hi = _cap_fact("hi_imp", confidence=0.8, importance=10)
        fid_lo, meta_lo = _cap_fact("lo_imp", confidence=0.8, importance=1)
        fid_fill, meta_fill = _cap_fact("fill", confidence=0.8, importance=1)
        await _seed_cap(store, (fid_hi, meta_hi), (fid_lo, meta_lo), (fid_fill, meta_fill))

        p = self._provider_with_cap(store, cap=2)
        await p._enforce_cap("u")

        assert "hi_imp" in store.records, "high-importance fact must survive"

    async def test_no_eviction_when_under_cap(self):
        """No records deleted when count ≤ cap."""
        store = _CapStore()
        await _seed_cap(store, *[_cap_fact(f"f{i}") for i in range(3)])
        p = self._provider_with_cap(store, cap=3)
        await p._enforce_cap("u")
        assert await store.count(where={"user": "u"}) == 3
