"""Tests for Sprint 10 Memory Privacy features.

Covers:
* forget.user command: authorized delete, unauthorized denied, idempotent, disabled provider
* inspect.user command: self-inspection, moderator inspection, unauthorized denied, capped output
* RetentionSweeper: eligible expiry, non-eligible retained, batch size, fail-safe loop
* Self-service: forget phrase, inspect phrase, cooldown, scope locked to requester
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kryten_llm.components.command_handler import CommandHandler
from kryten_llm.components.memory.retention import RetentionSweeper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(records: list[dict]) -> MagicMock:
    """Return a mock VectorStore returning *records* from get_all()."""
    store = MagicMock()
    store.get_all = AsyncMock(return_value=records)
    store.delete_ids = AsyncMock()
    store.delete = AsyncMock()
    store.count = AsyncMock(return_value=len(records))
    return store


def _make_provider(deleted: int = 2) -> MagicMock:
    """Return a mock LongTermMemoryProvider."""
    provider = MagicMock()
    provider.forget_user = AsyncMock(return_value=deleted)
    provider._store = _make_store([])
    return provider


def _make_handler(memory_provider=None, min_rank: int = 2) -> CommandHandler:
    """Return a CommandHandler with a mock KrytenClient, optionally wired to a provider."""
    client = MagicMock()
    client.subscribe_request_reply = AsyncMock()

    cfg = MagicMock()
    cfg.memory_commands.forget_min_rank = min_rank
    cfg.memory_commands.inspect_limit = 50

    handler = CommandHandler(
        client=client,
        service_name="llm",
        get_config=lambda: cfg,
    )
    if memory_provider is not None:
        handler.set_memory_provider(memory_provider)
    return handler


# ---------------------------------------------------------------------------
# Sortie 1: forget.user command
# ---------------------------------------------------------------------------


class TestForgetUserCommand:
    """REQ-170 through REQ-176."""

    async def test_authorized_forget_returns_count(self):
        provider = _make_provider(deleted=5)
        handler = _make_handler(memory_provider=provider)
        request = {
            "command": "forget.user",
            "username": "alice",
            "meta": {"rank": 3, "username": "mod1"},
        }
        reply = await handler._handle_forget_user(request)
        assert reply["success"] is True
        assert reply["data"]["deleted"] == 5
        provider.forget_user.assert_awaited_once_with("alice")

    async def test_unauthorized_request_denied(self):
        provider = _make_provider()
        handler = _make_handler(memory_provider=provider)
        request = {
            "command": "forget.user",
            "username": "alice",
            "meta": {"rank": 1},  # below min_rank=2
        }
        reply = await handler._handle_forget_user(request)
        assert reply["success"] is False
        assert reply["error"] == "unauthorized"
        provider.forget_user.assert_not_awaited()

    async def test_idempotent_unknown_user(self):
        provider = _make_provider(deleted=0)  # no facts to delete
        handler = _make_handler(memory_provider=provider)
        request = {
            "command": "forget.user",
            "username": "nobody",
            "meta": {"rank": 5},
        }
        reply = await handler._handle_forget_user(request)
        assert reply["success"] is True
        assert reply["data"]["deleted"] == 0

    async def test_no_provider_returns_error(self):
        handler = _make_handler(memory_provider=None)
        request = {
            "command": "forget.user",
            "username": "alice",
            "meta": {"rank": 5},
        }
        reply = await handler._handle_forget_user(request)
        assert reply["success"] is False
        assert "memory provider not available" in reply["error"]

    async def test_missing_username_returns_error(self):
        handler = _make_handler(memory_provider=_make_provider())
        request = {"command": "forget.user", "meta": {"rank": 5}}
        reply = await handler._handle_forget_user(request)
        assert reply["success"] is False
        assert "username" in reply["error"].lower()

    async def test_audit_log_emitted(self, caplog):
        import logging

        provider = _make_provider(deleted=3)
        handler = _make_handler(memory_provider=provider)
        request = {
            "command": "forget.user",
            "username": "bob",
            "meta": {"rank": 3, "username": "mod_x"},
        }
        with caplog.at_level(logging.INFO):
            await handler._handle_forget_user(request)
        assert any("audit" in r.message and "bob" in r.message for r in caplog.records)

    async def test_dispatch_via_handle_command(self):
        provider = _make_provider(deleted=1)
        handler = _make_handler(memory_provider=provider)
        request = {
            "command": "forget.user",
            "username": "carol",
            "meta": {"rank": 4},
        }
        reply = await handler._handle_command(request)
        assert reply["success"] is True
        assert reply["command"] == "forget.user"


# ---------------------------------------------------------------------------
# Sortie 5: inspect.user command
# ---------------------------------------------------------------------------


class TestInspectUserCommand:
    """REQ-210 through REQ-215."""

    def _records(self) -> list[dict]:
        return [
            {
                "id": f"fact{i}",
                "document": f"Fact number {i}",
                "metadata": {"category": "preference", "created_at": "2024-01-01", "importance": i},
            }
            for i in range(1, 6)
        ]

    async def test_self_inspection_allowed(self):
        store = _make_store(self._records())
        provider = MagicMock()
        provider._store = store
        handler = _make_handler(memory_provider=provider)
        request = {
            "command": "inspect.user",
            "username": "alice",
            "meta": {"rank": 0, "username": "alice"},  # low rank but self
        }
        reply = await handler._handle_inspect_user(request)
        assert reply["success"] is True
        assert reply["data"]["username"] == "alice"
        assert len(reply["data"]["facts"]) == 5

    async def test_moderator_can_inspect_other(self):
        store = _make_store(self._records())
        provider = MagicMock()
        provider._store = store
        handler = _make_handler(memory_provider=provider)
        request = {
            "command": "inspect.user",
            "username": "alice",
            "meta": {"rank": 3, "username": "mod1"},
        }
        reply = await handler._handle_inspect_user(request)
        assert reply["success"] is True

    async def test_unauthorized_cannot_inspect_other(self):
        handler = _make_handler(memory_provider=_make_provider())
        request = {
            "command": "inspect.user",
            "username": "alice",
            "meta": {"rank": 0, "username": "mallory"},
        }
        reply = await handler._handle_inspect_user(request)
        assert reply["success"] is False
        assert reply["error"] == "unauthorized"

    async def test_output_capped_at_limit(self):
        # Make 100 records but limit is 50
        many_records = [
            {"id": f"f{i}", "document": f"fact {i}", "metadata": {"importance": 1}}
            for i in range(100)
        ]
        store = _make_store(many_records)
        provider = MagicMock()
        provider._store = store
        handler = _make_handler(memory_provider=provider)
        request = {
            "command": "inspect.user",
            "username": "alice",
            "meta": {"rank": 5, "username": "mod"},
        }
        reply = await handler._handle_inspect_user(request)
        assert reply["success"] is True
        assert reply["data"]["returned"] == 50
        assert reply["data"]["total"] == 100

    async def test_no_embeddings_in_output(self):
        records = [
            {
                "id": "f1",
                "document": "kung fu fan",
                "embedding": [0.1] * 384,  # should be stripped
                "metadata": {"category": "pref", "importance": 2, "created_at": "2024-01-01"},
            }
        ]
        store = _make_store(records)
        provider = MagicMock()
        provider._store = store
        handler = _make_handler(memory_provider=provider)
        request = {
            "command": "inspect.user",
            "username": "u",
            "meta": {"rank": 5},
        }
        reply = await handler._handle_inspect_user(request)
        assert reply["success"] is True
        for fact in reply["data"]["facts"]:
            assert "embedding" not in fact

    async def test_read_only_no_mutation(self):
        store = _make_store(self._records())
        provider = MagicMock()
        provider._store = store
        handler = _make_handler(memory_provider=provider)
        request = {
            "command": "inspect.user",
            "username": "alice",
            "meta": {"rank": 5},
        }
        await handler._handle_inspect_user(request)
        store.delete.assert_not_called()
        store.delete_ids.assert_not_called()

    async def test_no_provider_returns_error(self):
        handler = _make_handler(memory_provider=None)
        request = {"command": "inspect.user", "username": "u", "meta": {"rank": 5}}
        reply = await handler._handle_inspect_user(request)
        assert reply["success"] is False


# ---------------------------------------------------------------------------
# Sortie 2: RetentionSweeper
# ---------------------------------------------------------------------------


class TestRetentionSweeper:
    """REQ-180 through REQ-186."""

    def _old_meta(self, importance: int = 1, days_ago: int = 200) -> dict:
        dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return {"importance": importance, "created_at": dt.isoformat()}

    def _recent_meta(self, importance: int = 1) -> dict:
        dt = datetime.now(timezone.utc) - timedelta(days=10)
        return {"importance": importance, "created_at": dt.isoformat()}

    async def test_old_low_importance_expired(self):
        records = [{"id": "old1", "metadata": self._old_meta(importance=1, days_ago=200)}]
        store = _make_store(records)
        sweeper = RetentionSweeper(
            store, interval_hours=24, max_age_days=90, expire_below_importance=2
        )
        deleted = await sweeper.sweep()
        assert deleted == 1
        store.delete_ids.assert_awaited_once_with(["old1"])

    async def test_recent_fact_retained(self):
        records = [{"id": "recent1", "metadata": self._recent_meta(importance=1)}]
        store = _make_store(records)
        sweeper = RetentionSweeper(
            store, interval_hours=24, max_age_days=90, expire_below_importance=2
        )
        deleted = await sweeper.sweep()
        assert deleted == 0
        store.delete_ids.assert_not_awaited()

    async def test_high_importance_retained(self):
        records = [{"id": "imp5", "metadata": self._old_meta(importance=5, days_ago=200)}]
        store = _make_store(records)
        sweeper = RetentionSweeper(
            store, interval_hours=24, max_age_days=90, expire_below_importance=2
        )
        deleted = await sweeper.sweep()
        assert deleted == 0

    async def test_age_only_mode(self):
        """expire_below_importance=0 means age is the only criterion."""
        records = [
            {"id": "old_hi", "metadata": self._old_meta(importance=99, days_ago=200)},
            {"id": "recent", "metadata": self._recent_meta(importance=1)},
        ]
        store = _make_store(records)
        sweeper = RetentionSweeper(
            store, interval_hours=24, max_age_days=90, expire_below_importance=0
        )
        deleted = await sweeper.sweep()
        assert deleted == 1
        store.delete_ids.assert_awaited_once_with(["old_hi"])

    async def test_batch_size_respected(self):
        records = [
            {"id": f"old{i}", "metadata": self._old_meta(importance=1, days_ago=200)}
            for i in range(10)
        ]
        store = _make_store(records)
        sweeper = RetentionSweeper(
            store,
            interval_hours=24,
            max_age_days=90,
            expire_below_importance=2,
            batch_size=3,
        )
        deleted = await sweeper.sweep()
        assert deleted == 10
        # Should have called delete_ids 4 times: 3+3+3+1
        assert store.delete_ids.await_count == 4

    async def test_sweep_error_caught_returns_zero(self):
        store = MagicMock()
        store.get_all = AsyncMock(side_effect=RuntimeError("db down"))
        store.delete_ids = AsyncMock()
        sweeper = RetentionSweeper(store, interval_hours=24, max_age_days=90)
        deleted = await sweeper.sweep()
        assert deleted == 0  # fail-safe

    async def test_delete_ids_error_is_caught(self):
        records = [{"id": "bad", "metadata": self._old_meta(importance=1, days_ago=200)}]
        store = _make_store(records)
        store.delete_ids = AsyncMock(side_effect=RuntimeError("delete failed"))
        sweeper = RetentionSweeper(
            store, interval_hours=24, max_age_days=90, expire_below_importance=2
        )
        deleted = await sweeper.sweep()
        assert deleted == 0  # batch failed but no exception propagated

    async def test_metric_recorded(self):
        records = [{"id": "old1", "metadata": self._old_meta(importance=1, days_ago=200)}]
        store = _make_store(records)
        monitor = MagicMock()
        sweeper = RetentionSweeper(
            store,
            interval_hours=24,
            max_age_days=90,
            expire_below_importance=2,
            health_monitor=monitor,
        )
        await sweeper.sweep()
        monitor.record_memory_facts_expired.assert_called_once_with(1)

    async def test_no_delete_ids_support_skips(self):
        records = [{"id": "old1", "metadata": self._old_meta(importance=1, days_ago=200)}]
        store = MagicMock()
        store.get_all = AsyncMock(return_value=records)
        del store.delete_ids  # remove the attribute
        sweeper = RetentionSweeper(
            store, interval_hours=24, max_age_days=90, expire_below_importance=2
        )
        deleted = await sweeper.sweep()
        assert deleted == 0

    async def test_start_stop_lifecycle(self):
        store = _make_store([])
        sweeper = RetentionSweeper(store, interval_hours=1000)
        sweeper.start()
        assert sweeper._task is not None
        await sweeper.stop()
        assert sweeper._task.done()


# ---------------------------------------------------------------------------
# Sortie 4: Self-service forget / inspect
# ---------------------------------------------------------------------------


class TestSelfServiceForget:
    """REQ-200–213.  Tests via _check_self_service on LLMService directly."""

    def _make_service(
        self,
        enabled: bool = True,
        phrase: str = "forget me",
        provider=None,
    ):
        """Return a minimal LLMService-like object with the method under test."""
        from kryten_llm.service import LLMService

        config = MagicMock()
        config.self_service.enabled = enabled
        config.self_service.phrase = phrase
        config.self_service.inspect_phrase = "what do you know about me"
        config.self_service.cooldown_seconds = 60
        config.memory_commands.inspect_limit = 50
        config.channels = [MagicMock(channel="testroom", domain="cytu.be")]
        config.testing.dry_run = True  # don't actually send chat

        svc = object.__new__(LLMService)
        svc.config = config
        svc._self_service_cooldown = {}
        svc.client = MagicMock()
        svc.client.send_chat = AsyncMock()

        # Build a fake pipeline whose providers contain our mock
        if provider is not None:
            fake_pipeline = MagicMock()
            fake_pipeline.providers = [provider]
            svc._context_pipeline = fake_pipeline
        else:
            svc._context_pipeline = None
        return svc

    async def test_forget_phrase_deletes_requester_facts(self):
        """Matching phrase triggers forget_user for the event username (REQ-200–202)."""
        from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider

        provider = _make_provider(deleted=7)
        provider._store = _make_store([])

        # Make isinstance(provider, LongTermMemoryProvider) return True
        with patch("kryten_llm.service.isinstance", side_effect=lambda obj, cls: True):
            svc = self._make_service(provider=provider)
            filtered = {"username": "alice", "msg": "please forget me now"}
            consumed = await svc._check_self_service(filtered)

        assert consumed is True
        provider.forget_user.assert_awaited_once_with("alice")

    async def test_phrase_only_affects_requester(self):
        """The forget scope is the event username — never a name from message body (REQ-202)."""
        provider = _make_provider(deleted=3)
        provider._store = _make_store([])

        with patch("kryten_llm.service.isinstance", side_effect=lambda obj, cls: True):
            svc = self._make_service(provider=provider)
            filtered = {"username": "alice", "msg": "forget me and also forget bob"}
            await svc._check_self_service(filtered)

        provider.forget_user.assert_awaited_once_with("alice")

    async def test_disabled_flag_phrase_ignored(self):
        """Self-service disabled → phrase not consumed, no deletion (REQ-205)."""
        provider = _make_provider()
        svc = self._make_service(enabled=False, provider=provider)

        filtered = {"username": "alice", "msg": "forget me"}
        consumed = await svc._check_self_service(filtered)

        assert consumed is False
        provider.forget_user.assert_not_awaited()

    async def test_cooldown_suppresses_rapid_repeat(self):
        """Second request within cooldown window is not processed (REQ-206)."""
        provider = _make_provider(deleted=1)
        provider._store = _make_store([])

        with patch("kryten_llm.service.isinstance", side_effect=lambda obj, cls: True):
            svc = self._make_service(provider=provider)
            filtered = {"username": "alice", "msg": "forget me"}
            # First call: consumed
            await svc._check_self_service(filtered)
            # Second call within cooldown: not consumed
            consumed2 = await svc._check_self_service(filtered)

        assert consumed2 is False
        assert provider.forget_user.await_count == 1

    async def test_no_provider_returns_true_gracefully(self):
        """Phrase matches but pipeline has no memory provider → consumed but no crash (REQ-200)."""
        svc = self._make_service(enabled=True)
        svc._context_pipeline = None
        filtered = {"username": "alice", "msg": "forget me"}
        consumed = await svc._check_self_service(filtered)
        assert consumed is True

    async def test_non_matching_message_not_consumed(self):
        """Regular message that doesn't match the phrase is not consumed."""
        svc = self._make_service()
        filtered = {"username": "alice", "msg": "I love kung fu movies"}
        consumed = await svc._check_self_service(filtered)
        assert consumed is False
