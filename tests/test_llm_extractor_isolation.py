"""Isolation tests for the Phase 7f extractor connection (REQ-001, REQ-002).

The extractor LLM connection MUST be structurally separate from the
message-generation ``llm_providers`` — there is no code path where a missing
extractor config borrows message-generation credentials/endpoints.
"""

from __future__ import annotations

import pytest

from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider
from kryten_llm.components.llm_manager import LLMManager
from kryten_llm.components.memory.llm_extractor import LLMFactExtractor
from kryten_llm.models.config import LLMProvider


def _extractor_dict() -> dict:
    return {
        "type": "llm",
        "llm": {
            "providers": {
                "extractor_local": {
                    "type": "openai_compatible",
                    "base_url": "http://localhost:9/v1",
                    "api_key": "extractor-key",
                    "model": "extractor-model",
                }
            },
            "provider_priority": ["extractor_local"],
        },
    }


class TestForExtractorFactory:
    def test_builds_isolated_manager(self):
        providers = {
            "ex": LLMProvider(
                name="ex",
                type="openai_compatible",
                base_url="http://localhost:9/v1",
                api_key="k",
                model="m",
            )
        }
        mgr = LLMManager.for_extractor(providers, ["ex"])
        assert set(mgr.providers) == {"ex"}
        assert mgr.config.default_provider_priority == ["ex"]

    def test_factory_does_not_reference_llm_providers(self):
        # A manager built for extraction knows nothing about message-gen providers.
        providers = {
            "ex": LLMProvider(
                name="ex",
                type="openai_compatible",
                base_url="http://localhost:9/v1",
                api_key="k",
                model="m",
            )
        }
        mgr = LLMManager.for_extractor(providers, ["ex"])
        assert "local" not in mgr.providers
        assert "ollama" not in mgr.providers


class TestBuildLLMExtractor:
    def test_requires_dedicated_llm_block(self):
        # REQ-002: no fallback — a missing llm block is a hard error, never a
        # silent borrow of message-generation credentials.
        with pytest.raises(ValueError):
            LongTermMemoryProvider._build_llm_extractor({"type": "llm"})

    def test_requires_providers(self):
        with pytest.raises(ValueError):
            LongTermMemoryProvider._build_llm_extractor(
                {"type": "llm", "llm": {"providers": {}}}
            )

    def test_uses_only_extractor_providers(self):
        extractor, cfg = LongTermMemoryProvider._build_llm_extractor(_extractor_dict())
        assert isinstance(extractor, LLMFactExtractor)
        assert set(extractor._manager.providers) == {"extractor_local"}
        assert cfg.llm is not None
        assert list(cfg.llm.providers) == ["extractor_local"]

    def test_injects_provider_name_from_key(self):
        # The example config omits the redundant inner ``name``; it is injected.
        extractor, _cfg = LongTermMemoryProvider._build_llm_extractor(_extractor_dict())
        assert extractor._manager.providers["extractor_local"].name == "extractor_local"
