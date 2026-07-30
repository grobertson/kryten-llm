"""Tests for memory observability (Sprint 9, Sortie 5 — REQ-160..166)."""

from __future__ import annotations

import logging
from unittest.mock import Mock

from kryten_llm.components.context.base import ContextRequest
from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider
from kryten_llm.components.health_monitor import ServiceHealthMonitor
from kryten_llm.components.metrics_server import MetricsServer
from kryten_llm.models.config import ServiceMetadata


def _hm():
    return ServiceHealthMonitor(
        ServiceMetadata(service_name="t", service_version="0"), Mock(spec=logging.Logger)
    )


class _FakeEmbedder:
    id = "fake"
    dimension = 3

    async def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class _FakeStore:
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


class _FakeGate:
    def __init__(self, silenced):
        self._silenced = silenced

    async def silenced_users(self):
        return self._silenced


def _row(fid, user, doc):
    return {
        "id": fid,
        "document": doc,
        "metadata": {"user": user, "category": "preference"},
        "distance": 0.0,
    }


# ---------------------------------------------------------------------------
# HealthMonitor counters
# ---------------------------------------------------------------------------


class TestHealthMonitorMemoryCounters:
    def test_counters_increment(self):
        hm = _hm()
        hm.record_memory_fragment("topical_memory")
        hm.record_memory_fragment("topical_memory")
        hm.record_memory_gate_fail_closed()
        hm.record_memory_silenced_excluded(3)
        hm.record_memory_presence_fallback()
        hm.record_memory_retrieval_time(0.012)

        assert hm._memory_fragment_counts["topical_memory"] == 2
        assert hm._memory_gate_fail_closed == 1
        assert hm._memory_silenced_excluded == 3
        assert hm._memory_presence_fallback == 1
        assert list(hm._memory_retrieval_times) == [0.012]


# ---------------------------------------------------------------------------
# Metrics exposition
# ---------------------------------------------------------------------------


class TestMetricsExposition:
    def test_emits_memory_series(self):
        hm = _hm()
        hm.record_memory_fragment("user_memory")
        hm.record_memory_gate_fail_closed()
        hm.record_memory_silenced_excluded(2)
        hm.record_memory_retrieval_time(0.02)

        lines: list[str] = []
        MetricsServer._emit_memory_metrics(None, lines, hm)  # self unused
        blob = "\n".join(lines)

        assert 'llm_memory_fragment_emitted_total{type="user_memory"} 1' in blob
        assert "llm_memory_gate_fail_closed_total 1" in blob
        assert "llm_memory_silenced_excluded_total 2" in blob
        assert "llm_memory_retrieval_seconds_count 1" in blob


# ---------------------------------------------------------------------------
# Provider integration
# ---------------------------------------------------------------------------


class TestProviderMetrics:
    async def test_records_fragment_and_latency(self):
        hm = _hm()
        store = _FakeStore([_row("a1", "alice", "loves synthwave")])
        provider = LongTermMemoryProvider(
            embedder=_FakeEmbedder(),
            vector_store=store,
            extractor=None,
            extractor_cfg=None,
            min_similarity=0.0,
            health_monitor=hm,
        )
        req = ContextRequest(username="alice", message="hi", trigger=None, channel="lounge")
        frags = await provider.provide(req)

        assert any(f.name == "user_memory" for f in frags)
        assert hm._memory_fragment_counts["user_memory"] == 1
        assert len(hm._memory_retrieval_times) == 1

    async def test_records_silenced_exclusion(self):
        hm = _hm()
        store = _FakeStore(
            [_row("a1", "alice", "loves synthwave"), _row("c1", "carol", "loves synthwave")]
        )
        provider = LongTermMemoryProvider(
            embedder=_FakeEmbedder(),
            vector_store=store,
            extractor=None,
            extractor_cfg=None,
            min_similarity=0.0,
            cross_user_enabled=True,
            moderation_gate=_FakeGate(frozenset({"carol"})),
            topical_cfg={"enabled": True, "fire_on": ["auto_participation"], "min_similarity": 0.0},
            health_monitor=hm,
        )
        req = ContextRequest(
            username="dave", message="hi", trigger={"type": "auto_participation"}, channel="lounge"
        )
        await provider.provide(req)
        assert hm._memory_silenced_excluded == 1

    async def test_records_gate_fail_closed(self):
        hm = _hm()
        store = _FakeStore([_row("a1", "alice", "loves synthwave")])
        provider = LongTermMemoryProvider(
            embedder=_FakeEmbedder(),
            vector_store=store,
            extractor=None,
            extractor_cfg=None,
            min_similarity=0.0,
            cross_user_enabled=True,
            moderation_gate=_FakeGate(None),  # gate unavailable
            gate_fail_closed=True,
            topical_cfg={"enabled": True, "fire_on": ["auto_participation"], "min_similarity": 0.0},
            health_monitor=hm,
        )
        req = ContextRequest(
            username="dave", message="hi", trigger={"type": "auto_participation"}, channel="lounge"
        )
        await provider.provide(req)
        assert hm._memory_gate_fail_closed == 1


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------


class TestTrace:
    async def _provider(self, **trace):
        return LongTermMemoryProvider(
            embedder=_FakeEmbedder(),
            vector_store=_FakeStore([_row("a1", "alice", "SECRETFACT")]),
            extractor=None,
            extractor_cfg=None,
            min_similarity=0.0,
            trace_cfg=trace,
        )

    async def test_trace_disabled_no_log(self, caplog):
        provider = await self._provider(enabled=False)
        req = ContextRequest(username="alice", message="hi", trigger=None, channel="lounge")
        with caplog.at_level(logging.DEBUG):
            await provider.provide(req)
        assert "LTM trace" not in caplog.text

    async def test_trace_enabled_no_content_by_default(self, caplog):
        provider = await self._provider(enabled=True)
        req = ContextRequest(username="alice", message="hi", trigger=None, channel="lounge")
        with caplog.at_level(logging.DEBUG):
            await provider.provide(req)
        assert "LTM trace" in caplog.text
        assert "user_memory" in caplog.text
        assert "SECRETFACT" not in caplog.text  # content withheld by default
