"""Moderation gate — a TTL-cached view of currently-silenced users.

Sprint 8, Sortie 0 (REQ-040, REQ-042, REQ-045).

Cross-user memory retrieval (topical / room / ambient) must never surface facts
belonging to a user who is *currently* silenced — otherwise the bot would give a
shadow-muted (or muted/banned) user a voice by proxy, defeating the moderation
action.

This gate obtains the silenced-user set from kryten-moderator's **published
command contract** (``kryten.moderator.command`` / ``entry.list``) via
``KrytenClient.nats_request`` rather than reading the moderator's KV buckets
directly. Using the service's public interface keeps kryten-llm decoupled from
the moderator's internal storage and bucket-name normalisation.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)

#: Actions that cause a user's facts to be withheld from cross-user recall.
DEFAULT_SILENCE_ACTIONS: frozenset[str] = frozenset({"ban", "smute", "mute"})

#: kryten-moderator command subject (COMMAND_PROTOCOL).
MODERATOR_COMMAND_SUBJECT = "kryten.moderator.command"


class _CommandClient(Protocol):
    """Minimal client surface the gate depends on (satisfied by KrytenClient)."""

    async def nats_request(
        self, subject: str, request: dict[str, Any], timeout: float
    ) -> dict[str, Any]: ...


class ModerationGate:
    """Answers *"which users are currently silenced?"*, TTL-cached.

    ``silenced_users`` returns ``None`` when the moderator cannot be reached or
    replies with failure, so the caller can apply its fail-closed policy (skip
    the cross-user fragment) rather than risk surfacing a silenced user.
    """

    def __init__(
        self,
        client: _CommandClient,
        domain: str,
        channel: str,
        *,
        silence_actions: frozenset[str] = DEFAULT_SILENCE_ACTIONS,
        cache_ttl_s: float = 10.0,
        request_timeout_s: float = 2.0,
    ) -> None:
        self._client = client
        self._domain = domain
        self._channel = channel
        self._silence_actions = frozenset(a.lower() for a in silence_actions)
        self._cache_ttl_s = cache_ttl_s
        self._request_timeout_s = request_timeout_s
        self._cache: frozenset[str] | None = None
        self._cache_at: float = 0.0

    async def silenced_users(self) -> frozenset[str] | None:
        """Return lowercased silenced usernames, or ``None`` on failure.

        A successful result is cached for ``cache_ttl_s`` seconds (REQ-045).
        Failures are not cached, so the next call re-queries the moderator.
        """
        now = time.monotonic()
        if self._cache is not None and (now - self._cache_at) < self._cache_ttl_s:
            return self._cache

        result = await self._fetch()
        if result is not None:
            self._cache = result
            self._cache_at = now
        return result

    async def _fetch(self) -> frozenset[str] | None:
        try:
            resp = await self._client.nats_request(
                MODERATOR_COMMAND_SUBJECT,
                {
                    "service": "moderator",
                    "command": "entry.list",
                    "domain": self._domain,
                    "channel": self._channel,
                },
                timeout=self._request_timeout_s,
            )
        except Exception as exc:  # timeout, connection error, decode error, ...
            logger.warning(f"ModerationGate: entry.list request failed: {exc}")
            return None

        if not isinstance(resp, dict) or not resp.get("success"):
            logger.warning(f"ModerationGate: entry.list returned failure: {resp!r}")
            return None

        data = resp.get("data") or {}
        entries = data.get("entries") or []
        silenced = {
            str(e.get("username", "")).lower()
            for e in entries
            if isinstance(e, dict)
            and e.get("username")
            and str(e.get("action", "")).lower() in self._silence_actions
        }
        return frozenset(silenced)
