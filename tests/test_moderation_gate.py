"""Tests for ModerationGate (Sprint 8, Sortie 0 — REQ-040/042/045).

The gate obtains currently-silenced users from kryten-moderator's published
command contract (``kryten.moderator.command`` / ``entry.list``) via
``nats_request``. These tests use a fake client so no NATS is required.
"""

from __future__ import annotations

from typing import Any

from kryten_llm.components.memory.moderation_gate import ModerationGate


class _FakeClient:
    """Minimal client exposing ``nats_request`` with a scripted response."""

    def __init__(self, response: Any = None, *, raise_exc: Exception | None = None):
        self._response = response
        self._raise = raise_exc
        self.calls: list[dict[str, Any]] = []

    async def nats_request(
        self, subject: str, request: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        self.calls.append({"subject": subject, "request": request, "timeout": timeout})
        if self._raise is not None:
            raise self._raise
        return self._response


def _list_response(*entries: tuple[str, str]) -> dict[str, Any]:
    """Build an entry.list success reply from (username, action) pairs."""
    return {
        "service": "moderator",
        "command": "entry.list",
        "success": True,
        "data": {
            "count": len(entries),
            "entries": [{"username": u, "action": a} for u, a in entries],
        },
    }


class TestModerationGate:
    async def test_success_builds_silenced_set(self):
        client = _FakeClient(_list_response(("Alice", "smute"), ("Bob", "ban"), ("Carol", "mute")))
        gate = ModerationGate(client, "cytu.be", "lounge")

        silenced = await gate.silenced_users()

        assert silenced == frozenset({"alice", "bob", "carol"})
        # Uses the moderator command contract, not KV.
        assert client.calls[0]["subject"] == "kryten.moderator.command"
        assert client.calls[0]["request"]["command"] == "entry.list"

    async def test_silence_actions_filter(self):
        client = _FakeClient(_list_response(("Alice", "smute"), ("Bob", "mute")))
        gate = ModerationGate(client, "cytu.be", "lounge", silence_actions=frozenset({"smute"}))

        silenced = await gate.silenced_users()

        assert silenced == frozenset({"alice"})  # Bob's 'mute' not in the set

    async def test_request_failure_returns_none(self):
        gate = ModerationGate(_FakeClient(raise_exc=TimeoutError("no moderator")), "d", "c")
        assert await gate.silenced_users() is None

    async def test_unsuccessful_reply_returns_none(self):
        gate = ModerationGate(
            _FakeClient({"service": "moderator", "success": False, "error": "boom"}), "d", "c"
        )
        assert await gate.silenced_users() is None

    async def test_ttl_cache_avoids_second_request(self):
        client = _FakeClient(_list_response(("Alice", "smute")))
        gate = ModerationGate(client, "d", "c", cache_ttl_s=1000)

        first = await gate.silenced_users()
        second = await gate.silenced_users()

        assert first == second == frozenset({"alice"})
        assert len(client.calls) == 1  # cached; not re-requested within TTL

    async def test_failure_is_not_cached(self):
        client = _FakeClient(raise_exc=RuntimeError("down"))
        gate = ModerationGate(client, "d", "c", cache_ttl_s=1000)

        assert await gate.silenced_users() is None
        assert await gate.silenced_users() is None
        assert len(client.calls) == 2  # re-queried after failure
