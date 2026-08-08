"""Memory-quality evaluation harness (Sprint 12, Sortie 1, REQ-250–254).

Provides:
- ``EvalScenario`` — typed fixture record.
- ``FixtureLoader`` — JSONL reader/validator.
- ``FakeEmbedder`` / ``FakeStore`` — deterministic in-memory fakes used by all eval tests.
- ``seed_store`` — populate a FakeStore with fixture facts.
- ``make_provider`` — build a minimal LongTermMemoryProvider wired to a FakeStore.
- ``StaticModerationGate`` — deterministic gate for disclosure tests (Sortie 4).

Design note: facts are embedded with ``FakeEmbedder``, a keyword-hash embedder that returns
stable 8-dimensional vectors.  Each dimension corresponds to a keyword group; a text that
contains keywords from group *k* gets a high value at position *k*.  This makes retrieval
deterministic without any real ONNX model.  Fixture texts are designed so that
"matching" query/fact pairs share keywords and therefore get similar vectors.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Scenario data model (REQ-250)
# ---------------------------------------------------------------------------


@dataclass
class EvalFact:
    """One fact in a fixture scenario."""

    user: str
    summary: str
    category: str
    importance: int = 1
    created_at: str = "2024-01-01T00:00:00+00:00"


@dataclass
class EvalScenario:
    """One eval scenario: seed facts + query + expected result ids + tags."""

    label: str
    facts: list[EvalFact]
    query: str
    expected_ids: list[str]
    # silenced_users may be None (from JSON null) to signal a gate-failure scenario (REQ-268).
    silenced_users: list[str] | None = field(default_factory=list)  # type: ignore[assignment]
    tags: list[str] = field(default_factory=list)
    # Contradiction-specific fields (optional)
    message: str = ""
    fact_text: str = ""
    contradicts: bool = False
    method: str = "heuristic"
    # Disclosure-specific lists (optional, override facts/silenced_users for clarity)
    facts_silenced: list[EvalFact] = field(default_factory=list)
    facts_normal: list[EvalFact] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fixture loader (REQ-251)
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {"label"}


class FixtureLoader:
    """Load and validate JSONL eval fixtures (REQ-251)."""

    @staticmethod
    def load(path: Path) -> list[EvalScenario]:
        """Read *path* (JSONL) and return a list of ``EvalScenario`` objects.

        Raises ``ValueError`` with a descriptive message on schema errors (REQ-251).
        """
        scenarios: list[EvalScenario] = []
        with path.open(encoding="utf-8") as f:
            for lineno, raw in enumerate(f, 1):
                raw = raw.strip()
                if not raw or raw.startswith("#"):
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{lineno}: invalid JSON — {exc}") from exc
                if not isinstance(obj, dict):
                    raise ValueError(f"{path}:{lineno}: expected JSON object, got {type(obj)}")
                missing = _REQUIRED_KEYS - obj.keys()
                if missing:
                    raise ValueError(f"{path}:{lineno}: missing required fields {missing!r}")
                scenarios.append(FixtureLoader._parse(obj, lineno, path))
        return scenarios

    @staticmethod
    def _parse(obj: dict, lineno: int, path: Path) -> EvalScenario:  # noqa: ARG004
        def _fact(d: dict) -> EvalFact:
            return EvalFact(
                user=str(d.get("user", "")),
                summary=str(d.get("summary", "")),
                category=str(d.get("category", "general")),
                importance=int(d.get("importance", 1)),
                created_at=str(d.get("created_at", "2024-01-01T00:00:00+00:00")),
            )

        return EvalScenario(
            label=str(obj.get("label", "")),
            facts=[_fact(f) for f in obj.get("facts", [])],
            query=str(obj.get("query", "")),
            expected_ids=list(obj.get("expected_ids") or []),
            # silenced_users may be null (JSON null) to signal a gate-failure scenario.
            silenced_users=obj.get("silenced_users"),  # type: ignore[arg-type]
            tags=list(obj.get("tags") or []),
            message=str(obj.get("message", "")),
            fact_text=str(obj.get("fact_text", "")),
            contradicts=bool(obj.get("contradicts", False)),
            method=str(obj.get("method", "heuristic")),
            facts_silenced=[_fact(f) for f in (obj.get("facts_silenced") or [])],
            facts_normal=[_fact(f) for f in (obj.get("facts_normal") or [])],
        )


# ---------------------------------------------------------------------------
# Deterministic fake embedder
# ---------------------------------------------------------------------------

# 8 keyword groups used to build the embedding space.
# A text's vector dimension k = (sum of keyword matches in group k) / normaliser.
_KEYWORD_GROUPS: list[list[str]] = [
    ["movie", "film", "cinema", "watch", "action", "martial"],
    ["sport", "game", "football", "basketball", "score", "play"],
    ["food", "eat", "cook", "restaurant", "taste", "pizza"],
    ["music", "song", "band", "listen", "guitar", "concert"],
    ["travel", "trip", "city", "visit", "hotel", "country"],
    ["tech", "computer", "code", "software", "program", "debug"],
    ["alice", "bob", "carol", "dave", "eve", "frank"],  # user name dimension
    ["silenced", "banned", "muted", "hidden"],  # moderation dimension
]


class FakeEmbedder:
    """Keyword-hash embedder — deterministic, no ONNX required (REQ-259).

    Dimension ``k`` of the output vector is proportional to the number of
    words in *text* that appear in keyword group *k*.  Vectors are L2-normalised.
    Texts sharing keywords get close vectors; texts with no shared keywords get
    orthogonal vectors.
    """

    id: str = "fake-keyword-8d"
    dimension: int = 8

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    @staticmethod
    def _vec(text: str) -> list[float]:
        words = text.lower().split()
        v = [0.0] * len(_KEYWORD_GROUPS)
        for i, group in enumerate(_KEYWORD_GROUPS):
            v[i] = sum(1.0 for w in words if any(kw in w for kw in group))
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]


# ---------------------------------------------------------------------------
# In-memory fake store (extended from test_topical_recall.py pattern)
# ---------------------------------------------------------------------------


class FakeStore:
    """Minimal in-memory store matching the VectorStore protocol.

    Supports: ``upsert``, ``query`` (cosine distance), ``delete``, ``delete_ids``,
    ``count``, ``get_all``, ``get_metadata``, ``update_metadata``.
    """

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    async def upsert(
        self,
        ids: list[str],
        vectors: list[list[float]],
        metadatas: list[dict],
        documents: list[str],
    ) -> None:
        for rid, vec, meta, doc in zip(ids, vectors, metadatas, documents):
            self.records[rid] = {
                "vector": list(vec),
                "metadata": dict(meta),
                "document": doc,
            }

    def _cosine_dist(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 1.0
        return 1.0 - dot / (na * nb)

    def _matches(self, meta: dict, where: dict | None) -> bool:
        if not where:
            return True
        for k, cond in where.items():
            val = meta.get(k, "")
            if isinstance(cond, dict):
                if "$ne" in cond and val == cond["$ne"]:
                    return False
                if "$in" in cond and val not in cond["$in"]:
                    return False
            elif val != cond:
                return False
        return True

    async def query(self, vector: list[float], k: int, where: dict | None = None) -> list[dict]:
        results = []
        for rid, rec in self.records.items():
            if not self._matches(rec["metadata"], where):
                continue
            dist = self._cosine_dist(vector, rec["vector"])
            results.append(
                {
                    "id": rid,
                    "document": rec["document"],
                    "metadata": dict(rec["metadata"]),
                    "distance": dist,
                }
            )
        results.sort(key=lambda r: r["distance"])
        return results[:k]

    async def delete(self, where: dict) -> None:
        to_del = [rid for rid, rec in self.records.items() if self._matches(rec["metadata"], where)]
        for rid in to_del:
            del self.records[rid]

    async def delete_ids(self, ids: list[str]) -> None:
        for rid in ids:
            self.records.pop(rid, None)

    async def count(self, where: dict | None = None) -> int:
        if not where:
            return len(self.records)
        return sum(1 for rec in self.records.values() if self._matches(rec["metadata"], where))

    async def get_all(self, where: dict | None = None) -> list[dict]:
        return [
            {"id": rid, "document": rec["document"], "metadata": dict(rec["metadata"])}
            for rid, rec in self.records.items()
            if self._matches(rec["metadata"], where)
        ]

    async def get_metadata(self, ids: list[str]) -> list[dict | None]:
        return [dict(self.records[rid]["metadata"]) if rid in self.records else None for rid in ids]

    async def update_metadata(self, ids: list[str], metadatas: list[dict]) -> None:
        for rid, meta in zip(ids, metadatas):
            if rid in self.records:
                self.records[rid]["metadata"] = dict(meta)

    async def reset(self) -> None:
        """Clear all records (Sprint 20.5, memory reset CLI support)."""
        self.records.clear()

    @property
    def store_mode(self) -> str:
        """Store-mode tag for observability tests (Sprint 17, REQ-345)."""
        return "fake"


# ---------------------------------------------------------------------------
# Seeding helpers (REQ-252, REQ-253)
# ---------------------------------------------------------------------------


async def seed_store(store: FakeStore, facts: list[EvalFact], embedder: FakeEmbedder) -> None:
    """Upsert *facts* into *store* using stable IDs (REQ-252, REQ-253).

    Uses the same ``stable_fact_id`` function as the live provider so IDs are
    consistent with what the provider would generate, making re-seeding idempotent.
    """
    from kryten_llm.components.memory.heuristic_extractor import stable_fact_id

    vectors = await embedder.embed([f.summary for f in facts])
    ids = [stable_fact_id(f.user, f.summary) for f in facts]
    metadatas = [
        {
            "user": f.user,
            "category": f.category,
            "importance": f.importance,
            "created_at": f.created_at,
            "score": 50.0,
            # Sprint 13, Sortie 1 (REQ-284): include confidence so eval harness
            # can exercise confidence-aware scoring offline.
            "confidence": min(1.0, f.importance / 10.0),
        }
        for f in facts
    ]
    documents = [f.summary for f in facts]
    await store.upsert(ids=ids, vectors=vectors, metadatas=metadatas, documents=documents)


def make_provider(store: FakeStore, embedder: FakeEmbedder) -> Any:
    """Build a minimal LongTermMemoryProvider with fake embedder + store (no ONNX needed)."""
    from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider
    from kryten_llm.components.memory.heuristic_extractor import HeuristicFactExtractor

    extractor = HeuristicFactExtractor(min_score=10.0)
    provider = LongTermMemoryProvider(
        embedder=embedder,
        vector_store=store,
        extractor=extractor,
        top_k=5,
        min_similarity=0.0,  # accept all results for eval
        cross_user_enabled=True,
        gate_fail_closed=False,  # no gate in eval by default
    )
    return provider


# ---------------------------------------------------------------------------
# StaticModerationGate for disclosure tests (REQ-266)
# ---------------------------------------------------------------------------


class StaticModerationGate:
    """A deterministic gate that returns a fixed silenced-user set (REQ-266).

    Pass ``silenced=None`` to simulate a gate failure (returns ``None``), which
    triggers the fail-closed path when ``gate_fail_closed=True`` (REQ-268).
    """

    def __init__(self, silenced: set[str] | None):
        self._silenced = silenced

    async def silenced_users(self) -> frozenset[str] | None:
        if self._silenced is None:
            return None  # gate failure
        return frozenset(s.lower() for s in self._silenced)
