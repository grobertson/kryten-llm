"""Tests for Sprint 17: Multi-Instance Shared Memory (REQ-340 – REQ-345).

Validates that two LongTermMemoryProvider instances sharing a single VectorStore:
  - See each other's facts immediately (REQ-340)
  - Maintain per-user isolation (REQ-341)
  - Propagate forget_user erasure (REQ-342)
  - Handle concurrent asyncio writes without data loss (REQ-343)
  - Report the correct store_mode for observability (REQ-345)

All tests use FakeStore + FakeEmbedder — no ONNX, no Chroma server, no network.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from tests.eval.harness import EvalFact, FakeEmbedder, FakeStore, make_provider, seed_store
from kryten_llm.components.context.base import ContextRequest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _req(username: str, message: str) -> ContextRequest:
    return ContextRequest(username=username, message=message, trigger=None, channel="")


def _text(frags) -> str:
    return " ".join(f.text or "" for f in frags)


# ─────────────────────────────────────────────────────────────────────────────
# Sortie 1: Shared-store semantics (REQ-340 – REQ-343)
# ─────────────────────────────────────────────────────────────────────────────


class TestSharedStoreSemantics:
    """REQ-340: Facts written via one provider are visible via the other."""

    async def test_shared_store_visibility(self):
        shared = FakeStore()
        embedder = FakeEmbedder()
        primary = make_provider(shared, embedder)
        secondary = make_provider(shared, embedder)

        await seed_store(
            shared,
            [EvalFact(user="alice", summary="loves action film cinema", category="preference")],
            embedder,
        )

        # Both providers point at the same store — count visible from either.
        assert await primary._store.count({"user": "alice"}) == 1
        assert await secondary._store.count({"user": "alice"}) == 1

        # Secondary can retrieve Alice's fact in a provide() call.
        frags = await secondary.provide(_req("alice", "action film"))
        assert any("action" in (f.text or "").lower() for f in frags), (
            f"Expected action-related fact in secondary's response; got: {_text(frags)!r}"
        )

    async def test_primary_write_visible_to_secondary(self):
        """Facts seeded into primary's store appear when secondary queries."""
        shared = FakeStore()
        embedder = FakeEmbedder()
        primary = make_provider(shared, embedder)
        secondary = make_provider(shared, embedder)

        await seed_store(
            shared,
            [EvalFact(user="bob", summary="loves sport basketball game", category="hobby")],
            embedder,
        )

        frags = await secondary.provide(_req("bob", "sport basketball"))
        assert any("basketball" in (f.text or "").lower() for f in frags), (
            f"Secondary should surface bob's basketball fact; got: {_text(frags)!r}"
        )

    async def test_user_isolation(self):
        """REQ-341: Alice's facts don't appear when provider queries for Bob."""
        shared = FakeStore()
        embedder = FakeEmbedder()
        primary = make_provider(shared, embedder)
        secondary = make_provider(shared, embedder)

        await seed_store(
            shared,
            [
                EvalFact(user="alice", summary="loves action film martial cinema", category="preference"),
                EvalFact(user="bob", summary="loves sport basketball game", category="hobby"),
            ],
            embedder,
        )

        # Query alice from secondary: should contain alice's fact, not bob's.
        alice_frags = await secondary.provide(_req("alice", "action film"))
        alice_text = _text(alice_frags).lower()
        assert "martial" in alice_text or "action" in alice_text, (
            f"Alice's fact missing from secondary; got: {alice_text!r}"
        )
        assert "basketball" not in alice_text, (
            f"Bob's fact leaked into alice's query; got: {alice_text!r}"
        )

        # Query bob from primary: should contain bob's fact, not alice's.
        bob_frags = await primary.provide(_req("bob", "basketball sport"))
        bob_text = _text(bob_frags).lower()
        assert "basketball" in bob_text, (
            f"Bob's fact missing from primary; got: {bob_text!r}"
        )
        assert "martial" not in bob_text, (
            f"Alice's fact leaked into bob's query; got: {bob_text!r}"
        )

    async def test_forget_propagates_across_instances(self):
        """REQ-342: forget_user on primary removes facts; secondary sees the deletion."""
        shared = FakeStore()
        embedder = FakeEmbedder()
        primary = make_provider(shared, embedder)
        secondary = make_provider(shared, embedder)

        await seed_store(
            shared,
            [EvalFact(user="alice", summary="loves action film cinema", category="preference")],
            embedder,
        )
        assert await shared.count({"user": "alice"}) == 1

        # Forget via primary.
        deleted = await primary.forget_user("alice")
        assert deleted >= 0  # forget_user returns count deleted

        # The shared store is now empty for alice.
        assert await shared.count({"user": "alice"}) == 0

        # Secondary's next provide() returns no alice facts.
        frags = await secondary.provide(_req("alice", "action film"))
        assert not any("action" in (f.text or "").lower() for f in frags), (
            f"Forgotten facts still visible via secondary; got: {_text(frags)!r}"
        )

    async def test_forget_on_secondary_clears_for_primary(self):
        """REQ-342: forget_user direction-agnostic — works from either instance."""
        shared = FakeStore()
        embedder = FakeEmbedder()
        primary = make_provider(shared, embedder)
        secondary = make_provider(shared, embedder)

        await seed_store(
            shared,
            [EvalFact(user="carol", summary="loves music concert song", category="interest")],
            embedder,
        )

        await secondary.forget_user("carol")
        assert await shared.count({"user": "carol"}) == 0

        frags = await primary.provide(_req("carol", "music concert"))
        assert not any("music" in (f.text or "").lower() for f in frags)

    async def test_concurrent_writes_no_data_loss(self):
        """REQ-343: concurrent asyncio writes from two providers don't lose facts."""
        shared = FakeStore()
        embedder = FakeEmbedder()

        alice_facts = [
            EvalFact(user="alice", summary="loves action film cinema", category="preference"),
            EvalFact(user="alice", summary="watches martial arts movies", category="preference"),
        ]
        bob_facts = [
            EvalFact(user="bob", summary="loves sport basketball game", category="hobby"),
            EvalFact(user="bob", summary="plays football sport", category="hobby"),
        ]

        await asyncio.gather(
            seed_store(shared, alice_facts, embedder),
            seed_store(shared, bob_facts, embedder),
        )

        assert await shared.count({"user": "alice"}) == 2
        assert await shared.count({"user": "bob"}) == 2
        assert await shared.count() == 4

    async def test_silo_baseline_separate_stores_dont_share(self):
        """Sanity check: providers with different stores cannot see each other's facts.

        This proves the shared-store pattern is a deliberate choice, not the default.
        """
        store_a = FakeStore()
        store_b = FakeStore()
        embedder = FakeEmbedder()
        primary = make_provider(store_a, embedder)
        secondary = make_provider(store_b, embedder)

        await seed_store(
            store_a,
            [EvalFact(user="alice", summary="loves action film martial cinema", category="preference")],
            embedder,
        )

        # store_b has nothing for alice.
        assert await store_b.count({"user": "alice"}) == 0

        frags = await secondary.provide(_req("alice", "action film"))
        assert not any("action" in (f.text or "").lower() for f in frags), (
            "Separate-store providers should not share facts — isolation broken."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Sortie 3: Store-mode observability (REQ-345)
# ─────────────────────────────────────────────────────────────────────────────


class TestStoreModeProperty:
    def test_fake_store_mode(self):
        """FakeStore reports mode='fake'."""
        assert FakeStore().store_mode == "fake"

    def test_chroma_embedded_mode(self):
        """ChromaVectorStore without http_host → chroma-embedded."""
        from kryten_llm.components.memory.vector_store import ChromaVectorStore

        store = ChromaVectorStore(path="./data/chroma")
        assert store.store_mode == "chroma-embedded"

    def test_chroma_http_mode(self):
        """ChromaVectorStore with http_host set → chroma-http."""
        from kryten_llm.components.memory.vector_store import ChromaVectorStore

        store = ChromaVectorStore(path="./data/chroma", http_host="localhost", http_port=8000)
        assert store.store_mode == "chroma-http"

    def test_pgvector_mode(self):
        """PgVectorStore always reports mode='pgvector'."""
        from kryten_llm.components.memory.vector_store import PgVectorStore

        store = PgVectorStore(dsn="postgresql://user:pass@localhost/db", dimension=8)
        assert store.store_mode == "pgvector"

    def test_metrics_emit_store_mode(self):
        """MetricsServer._emit_component_metrics includes llm_memory_store_mode."""
        from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider
        from kryten_llm.components.metrics_server import MetricsServer

        # Build a minimal provider with FakeStore.
        shared = FakeStore()
        embedder = FakeEmbedder()
        provider = make_provider(shared, embedder)

        # Wire up the mock app.
        pipeline = MagicMock()
        pipeline.providers = [provider]

        app = MagicMock()
        app._context_pipeline = pipeline
        app.command_handler = None
        app.trigger_engine = None
        app.context_manager = None
        app.config.formatting = None
        app.config.validation = None
        app.config.testing.dry_run = False
        app.config.llm_providers = {}
        app.rate_limiter = None

        # Subclass to satisfy the abstract _get_health_details requirement.
        class _TestMetricsServer(MetricsServer):
            async def _get_health_details(self):
                return {}

        ms = _TestMetricsServer.__new__(_TestMetricsServer)
        ms.app = app
        lines: list[str] = []
        ms._emit_component_metrics(lines)

        combined = "\n".join(lines)
        assert "llm_memory_store_mode" in combined, (
            f"Expected llm_memory_store_mode in metrics output; got:\n{combined}"
        )
        assert 'mode="fake"' in combined, (
            f"Expected mode='fake' for FakeStore; got:\n{combined}"
        )
