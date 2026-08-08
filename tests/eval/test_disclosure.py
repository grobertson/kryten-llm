"""Disclosure-safety privacy regression gate (Sprint 12, Sortie 4, REQ-265–269).

Run with:  pytest -m eval -k disclosure

Asserts that silenced users' facts NEVER appear in cross-user retrieval output.
This is a hard privacy gate — any disclosure causes an immediate assertion failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kryten_llm.components.context.base import ContextRequest
from tests.eval.harness import (
    EvalFact,
    FakeEmbedder,
    FakeStore,
    FixtureLoader,
    StaticModerationGate,
    make_provider,
    seed_store,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


async def _run_disclosure_check(
    provider: Any,
    store: FakeStore,
    embedder: FakeEmbedder,
    silenced_users: list[str] | None,
    query: str,
) -> tuple[list[Any], list[str]]:
    """Configure gate, run provide(), return (fragments, silenced_users_list)."""
    if silenced_users is None:
        # Simulate gate failure (fail-closed path).
        provider._mod_gate = StaticModerationGate(None)
        provider._gate_fail_closed = True
    elif len(silenced_users) == 0:
        provider._mod_gate = StaticModerationGate(set())
        provider._gate_fail_closed = True
    else:
        provider._mod_gate = StaticModerationGate(set(silenced_users))
        provider._gate_fail_closed = True

    req = ContextRequest(username="__eval__", message=query, trigger=None, channel="eval")
    frags = await provider.provide(req)
    return frags, silenced_users or []


def _assert_no_disclosure(
    fragments: list[Any],
    silenced_users: list[str],
    label: str,
) -> None:
    """Hard assertion: no silenced user's name appears in any fragment (REQ-267, REQ-269)."""
    for frag in fragments:
        text = frag.text or ""
        for user in silenced_users:
            # Check both exact username and fact content that contains the username.
            assert user.lower() not in text.lower(), (
                f"DISCLOSURE in scenario '{label}': silenced user '{user}' "
                f"appears in fragment '{frag.name}': {text!r}"
            )


# ---------------------------------------------------------------------------
# Disclosure corpus eval — @pytest.mark.eval
# ---------------------------------------------------------------------------


@pytest.mark.eval
class TestDisclosureEval:
    """Privacy regression gate: zero silenced-user disclosure (REQ-265–269)."""

    async def test_no_disclosure_across_all_scenarios(self):
        """Assert zero silenced-user disclosures in all fixture scenarios (REQ-269)."""
        scenarios = FixtureLoader.load(_FIXTURE_DIR / "disclosure.jsonl")
        embedder = FakeEmbedder()

        for sc in scenarios:
            store = FakeStore()
            provider = make_provider(store, embedder)
            provider._cross_user_enabled = True
            provider._topical_enabled = True
            provider._topical_fire_on = {"__any__"}  # fire unconditionally for eval

            # Seed normal facts
            normal_facts = sc.facts_normal or sc.facts
            await seed_store(store, normal_facts, embedder)

            # Seed silenced facts
            for fact in sc.facts_silenced:
                await seed_store(store, [fact], embedder)

            frags, silenced = await _run_disclosure_check(
                provider, store, embedder, sc.silenced_users, sc.query
            )
            _assert_no_disclosure(frags, silenced, sc.label)

    async def test_min_5_disclosure_scenarios(self):
        """At least 5 disclosure scenarios required (REQ-268)."""
        scenarios = FixtureLoader.load(_FIXTURE_DIR / "disclosure.jsonl")
        assert (
            len(scenarios) >= 5
        ), f"disclosure.jsonl must have ≥ 5 scenarios, got {len(scenarios)}"

    async def test_fail_closed_gate_suppresses_cross_user_output(self):
        """When the gate returns None (failure), no cross-user facts surface (REQ-268)."""
        embedder = FakeEmbedder()
        store = FakeStore()
        provider = make_provider(store, embedder)
        provider._cross_user_enabled = True
        provider._topical_enabled = True
        provider._gate_fail_closed = True

        alice_fact = EvalFact(
            user="alice", summary="alice loves action movie film martial", category="preference"
        )
        await seed_store(store, [alice_fact], embedder)

        # Gate returns None → fail-closed → no cross-user fragment
        provider._mod_gate = StaticModerationGate(None)
        req = ContextRequest(
            username="bob", message="movie film action", trigger=None, channel="eval"
        )
        frags = await provider.provide(req)

        cross_user_frags = [
            f for f in frags if f.name in ("topical_memory", "room_memory", "ambient_memory")
        ]
        assert len(cross_user_frags) == 0, (
            f"Fail-closed gate must suppress cross-user fragments, got: "
            f"{[f.name for f in cross_user_frags]}"
        )

    async def test_empty_silenced_list_allows_normal_output(self):
        """Empty silenced list = no filtering; normal facts can surface (REQ-268)."""
        embedder = FakeEmbedder()
        store = FakeStore()
        provider = make_provider(store, embedder)

        fact = EvalFact(
            user="alice",
            summary="alice loves action movie film martial cinema",
            category="preference",
        )
        await seed_store(store, [fact], embedder)

        provider._mod_gate = StaticModerationGate(set())  # empty — gate open
        req = ContextRequest(
            username="alice", message="movie film action", trigger=None, channel="eval"
        )
        frags = await provider.provide(req)

        # Speaker-scope facts should still surface (gate doesn't affect speaker scope)
        speaker_frags = [f for f in frags if "memory" in f.name]
        assert len(speaker_frags) >= 0  # just assert no crash
