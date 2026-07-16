"""Tests for the LLMFactExtractor (Phase 7f — REQ-010 to REQ-015).

Pure-transform tests against a fake manager (no live LLM).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from kryten_llm.components.memory.extractor import ExtractedFact
from kryten_llm.components.memory.llm_extractor import LLMFactExtractor
from kryten_llm.models.config import ExtractorConfig


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class _FakeManager:
    """Returns canned response contents in order; records requests."""

    def __init__(self, responses: list[Any]):
        self._responses = list(responses)
        self.calls: list[Any] = []
        self.providers = {"x": SimpleNamespace(temperature=0.1, max_tokens=800)}

    def _get_provider_priority(self, preferred: str | None) -> list[str]:
        return ["x"]

    async def generate_response(self, request: Any) -> Any:
        self.calls.append(request)
        if not self._responses:
            return None
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        if r is None:
            return None
        return _FakeResponse(r)


def _cfg(mode: str = "prompt", **overrides: Any) -> ExtractorConfig:
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
            },
            "provider_priority": ["x"],
        },
        "structured_output": {"mode": mode},
    }
    base.update(overrides)
    return ExtractorConfig.model_validate(base)


def _valid_payload(user: str = "Alice") -> str:
    return json.dumps(
        {
            "facts": [
                {
                    "target_user": user,
                    "category": "preference",
                    "summary": "Loves the film Aliens (1986)",
                    "confidence": 0.86,
                    "sentiment": 0.92,
                    "evidence_message_index": 1,
                }
            ]
        }
    )


_WINDOW = [
    {"username": "Bob", "message": "what's everyone watching"},
    {"username": "Alice", "message": "i absolutely love the movie Aliens"},
]


# ---------------------------------------------------------------------------
# JSON contract / parsing
# ---------------------------------------------------------------------------


class TestExtractHappyPath:
    async def test_valid_json_returns_scored_fact(self):
        mgr = _FakeManager([_valid_payload()])
        ex = LLMFactExtractor(mgr, _cfg())
        facts = await ex.extract(_WINDOW, "Alice")
        assert len(facts) == 1
        f = facts[0]
        assert isinstance(f, ExtractedFact)
        assert f.target_user == "Alice"
        assert f.category == "preference"
        assert f.summary == "Loves the film Aliens (1986)"
        assert f.confidence == pytest.approx(0.86)
        assert f.sentiment == pytest.approx(0.92)
        assert f.evidence["index"] == 1
        assert "Aliens" in f.evidence["message"]
        assert len(mgr.calls) == 1

    async def test_prompt_mode_sends_no_response_format(self):
        mgr = _FakeManager([_valid_payload()])
        ex = LLMFactExtractor(mgr, _cfg(mode="prompt"))
        await ex.extract(_WINDOW, "Alice")
        assert mgr.calls[0].response_format is None

    async def test_json_schema_mode_sends_response_format(self):
        mgr = _FakeManager([_valid_payload()])
        ex = LLMFactExtractor(mgr, _cfg(mode="json_schema"))
        await ex.extract(_WINDOW, "Alice")
        assert mgr.calls[0].response_format is not None
        assert mgr.calls[0].response_format["type"] == "json_schema"

    async def test_json_wrapped_in_prose_is_sliced(self):
        content = "Sure! Here you go:\n" + _valid_payload() + "\nHope that helps."
        mgr = _FakeManager([content])
        ex = LLMFactExtractor(mgr, _cfg())
        facts = await ex.extract(_WINDOW, "Alice")
        assert len(facts) == 1


class TestExtractValidation:
    async def test_focus_user_filter_drops_other_authors(self):
        mgr = _FakeManager([_valid_payload(user="Charlie")])
        ex = LLMFactExtractor(mgr, _cfg())
        facts = await ex.extract(_WINDOW, "Alice")
        assert facts == []

    async def test_missing_fields_dropped(self):
        payload = json.dumps(
            {
                "facts": [
                    {"target_user": "Alice", "category": "misc", "summary": "",
                     "confidence": 0.9, "sentiment": 0.5, "evidence_message_index": 0},
                    {"target_user": "", "category": "misc", "summary": "x",
                     "confidence": 0.9, "sentiment": 0.5, "evidence_message_index": 0},
                ]
            }
        )
        mgr = _FakeManager([payload])
        ex = LLMFactExtractor(mgr, _cfg())
        facts = await ex.extract(_WINDOW, "Alice")
        assert facts == []

    async def test_unknown_category_becomes_misc(self):
        payload = json.dumps(
            {
                "facts": [
                    {"target_user": "Alice", "category": "bogus", "summary": "likes cats",
                     "confidence": 0.9, "sentiment": 0.5, "evidence_message_index": 0}
                ]
            }
        )
        mgr = _FakeManager([payload])
        ex = LLMFactExtractor(mgr, _cfg())
        facts = await ex.extract(_WINDOW, "Alice")
        assert facts[0].category == "misc"

    async def test_confidence_and_sentiment_clamped(self):
        payload = json.dumps(
            {
                "facts": [
                    {"target_user": "Alice", "category": "misc", "summary": "likes cats",
                     "confidence": 5.0, "sentiment": -3.0, "evidence_message_index": 0}
                ]
            }
        )
        mgr = _FakeManager([payload])
        ex = LLMFactExtractor(mgr, _cfg())
        facts = await ex.extract(_WINDOW, "Alice")
        assert facts[0].confidence == 1.0
        assert facts[0].sentiment == 0.0

    async def test_max_facts_per_batch_cap(self):
        many = {
            "facts": [
                {"target_user": "Alice", "category": "misc", "summary": f"fact {i}",
                 "confidence": 0.9, "sentiment": 0.5, "evidence_message_index": 0}
                for i in range(10)
            ]
        }
        mgr = _FakeManager([json.dumps(many)])
        ex = LLMFactExtractor(mgr, _cfg(cadence={"max_facts_per_batch": 3}))
        facts = await ex.extract(_WINDOW, "Alice")
        assert len(facts) == 3


class TestRepairAndDrop:
    async def test_malformed_then_repaired(self):
        mgr = _FakeManager(["this is not json", _valid_payload()])
        ex = LLMFactExtractor(mgr, _cfg())
        facts = await ex.extract(_WINDOW, "Alice")
        assert len(facts) == 1
        assert len(mgr.calls) == 2  # initial + one repair

    async def test_unrepairable_drops_batch(self):
        mgr = _FakeManager(["nope", "still nope"])
        ex = LLMFactExtractor(mgr, _cfg())
        facts = await ex.extract(_WINDOW, "Alice")
        assert facts == []
        assert len(mgr.calls) == 2  # exactly one repair attempt

    async def test_no_response_drops_batch(self):
        mgr = _FakeManager([None])
        ex = LLMFactExtractor(mgr, _cfg(mode="prompt"))
        facts = await ex.extract(_WINDOW, "Alice")
        assert facts == []

    async def test_call_exception_never_raises(self):
        mgr = _FakeManager([RuntimeError("boom")])
        ex = LLMFactExtractor(mgr, _cfg(mode="prompt"))
        facts = await ex.extract(_WINDOW, "Alice")
        assert facts == []


class TestAutoDowngrade:
    async def test_auto_downgrades_to_prompt_on_failure(self):
        # First (schema) call yields nothing; auto downgrades to prompt and retries.
        mgr = _FakeManager([None, _valid_payload()])
        ex = LLMFactExtractor(mgr, _cfg(mode="auto"))
        facts = await ex.extract(_WINDOW, "Alice")
        assert len(facts) == 1
        assert ex._downgraded is True
        assert mgr.calls[0].response_format is not None  # schema attempt
        assert mgr.calls[1].response_format is None  # downgraded retry

    async def test_downgrade_persists_across_batches(self):
        mgr = _FakeManager([None, _valid_payload(), _valid_payload()])
        ex = LLMFactExtractor(mgr, _cfg(mode="auto"))
        await ex.extract(_WINDOW, "Alice")
        mgr2_start = len(mgr.calls)
        await ex.extract(_WINDOW, "Alice")
        # Second batch should not re-attempt schema mode.
        assert mgr.calls[mgr2_start].response_format is None
