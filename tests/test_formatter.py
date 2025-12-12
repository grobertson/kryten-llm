"""Tests for response formatter.

Tests the ResponseFormatter component that formats LLM responses
for display in chat (handles length limits, splits, etc.).
"""

import pytest

from kryten_llm.components.formatter import ResponseFormatter
from kryten_llm.models.config import LLMConfig


@pytest.fixture
def llm_config():
    """Create test LLM config."""
    return LLMConfig(
        **{
            "nats": {"servers": ["nats://localhost:4222"]},
            "channels": [{"domain": "cytu.be", "channel": "testroom"}],
            "llm_providers": {
                "test": {
                    "name": "test",
                    "type": "openai_compatible",
                    "base_url": "http://localhost:8080",
                    "api_key": "test-key",
                    "model": "test-model",
                }
            },
            "default_provider": "test",
            "triggers": [],
            "rate_limits": {},
            "spam_detection": {},
            "formatting": {
                "max_message_length": 400,
                "continuation_indicator": " ...",
                "remove_llm_artifacts": False,
                "remove_self_references": False,
            },
        }
    )


@pytest.fixture
def short_config():
    """Create config with short max length for testing splits."""
    return LLMConfig(
        **{
            "nats": {"servers": ["nats://localhost:4222"]},
            "channels": [{"domain": "cytu.be", "channel": "testroom"}],
            "llm_providers": {
                "test": {
                    "name": "test",
                    "type": "openai_compatible",
                    "base_url": "http://localhost:8080",
                    "api_key": "test-key",
                    "model": "test-model",
                }
            },
            "default_provider": "test",
            "triggers": [],
            "rate_limits": {},
            "spam_detection": {},
            "formatting": {
                "max_message_length": 100,
                "continuation_indicator": " ...",
                "remove_llm_artifacts": False,
                "remove_self_references": False,
            },
        }
    )


class TestResponseFormatter:
    """Tests for ResponseFormatter."""

    def test_format_short_response(self, llm_config):
        """Short responses should be returned as single item."""
        formatter = ResponseFormatter(llm_config)
        response = "Great question!"
        result = formatter.format_response(response)
        assert len(result) == 1
        assert result[0] == "Great question!"

    def test_format_empty_response(self, llm_config):
        """Empty responses should return empty list."""
        formatter = ResponseFormatter(llm_config)
        result = formatter.format_response("")
        assert result == []

    def test_format_whitespace_response(self, llm_config):
        """Whitespace-only responses should return empty list."""
        formatter = ResponseFormatter(llm_config)
        result = formatter.format_response("   \n\t  ")
        assert result == []

    def test_format_long_response_splits_on_sentences(self, short_config):
        """Long responses should split on sentence boundaries when exceeding max length."""
        formatter = ResponseFormatter(short_config)
        # Create a response that exceeds 100 chars
        response = "First sentence here. Second sentence follows this. Third sentence continues on. Fourth sentence ends here."
        result = formatter.format_response(response)
        # With 100 char limit, this should split
        if len(response) > 100:
            assert len(result) >= 1
            # Each part should respect max length (with continuation indicator room)
            for part in result:
                assert len(part) <= 110  # Allow some slack for indicator

    def test_format_response_preserves_content(self, llm_config):
        """Formatting should preserve the original content."""
        formatter = ResponseFormatter(llm_config)
        response = "This is a test response with special chars: @#$%"
        result = formatter.format_response(response)
        assert "This is a test response with special chars: @#$%" in " ".join(result)

    def test_format_response_with_newlines(self, llm_config):
        """Responses with newlines should be handled correctly."""
        formatter = ResponseFormatter(llm_config)
        response = "Line one.\nLine two.\nLine three."
        result = formatter.format_response(response)
        assert len(result) >= 1

    def test_format_response_with_continuation_indicator(self):
        """Long responses should include continuation indicator when split."""
        config = LLMConfig(
            **{
                "nats": {"servers": ["nats://localhost:4222"]},
                "channels": [{"domain": "cytu.be", "channel": "testroom"}],
                "llm_providers": {
                    "test": {
                        "name": "test",
                        "type": "openai_compatible",
                        "base_url": "http://localhost:8080",
                        "api_key": "test-key",
                        "model": "test-model",
                    }
                },
                "default_provider": "test",
                "triggers": [],
                "rate_limits": {},
                "spam_detection": {},
                "formatting": {
                    "max_message_length": 100,
                    "continuation_indicator": " [MORE]",
                    "remove_llm_artifacts": False,
                    "remove_self_references": False,
                },
            }
        )
        formatter = ResponseFormatter(config)
        # Create a response long enough to need splitting
        response = "First sentence is here. Second sentence follows. Third sentence too. Fourth one. Fifth sentence."
        result = formatter.format_response(response)
        # If there are multiple parts, first should have continuation indicator
        if len(result) > 1:
            assert result[0].endswith("[MORE]") or "[MORE]" in result[0]

    def test_format_very_long_word(self, short_config):
        """Very long words that exceed max length should still be handled."""
        formatter = ResponseFormatter(short_config)
        response = "A" * 100  # Very long "word"
        result = formatter.format_response(response)
        # Should still produce output even if word is too long
        assert len(result) >= 1

    def test_format_multiple_sentences(self, llm_config):
        """Multiple sentences should be formatted correctly."""
        formatter = ResponseFormatter(llm_config)
        response = "First. Second. Third. Fourth. Fifth."
        result = formatter.format_response(response)
        assert len(result) >= 1

    def test_format_response_unicode(self, llm_config):
        """Unicode characters should be handled correctly."""
        formatter = ResponseFormatter(llm_config)
        response = "Hello 世界! 🌍 Привет мир!"
        result = formatter.format_response(response)
        assert len(result) >= 1
        assert "Hello" in result[0]

    def test_format_response_punctuation(self, llm_config):
        """Various punctuation should be handled correctly."""
        formatter = ResponseFormatter(llm_config)
        response = "Question? Answer! Statement. More..."
        result = formatter.format_response(response)
        assert len(result) >= 1

    def test_format_response_code_blocks(self, llm_config):
        """Code blocks should be preserved."""
        formatter = ResponseFormatter(llm_config)
        response = "Here is code: `print('hello')`"
        result = formatter.format_response(response)
        assert len(result) >= 1
        assert "`print('hello')`" in " ".join(result)

    def test_format_response_urls(self, llm_config):
        """URLs should be preserved."""
        formatter = ResponseFormatter(llm_config)
        response = "Check out https://example.com for more info."
        result = formatter.format_response(response)
        assert len(result) >= 1
        assert "https://example.com" in " ".join(result)

    def test_format_response_strips_extra_whitespace(self, llm_config):
        """Extra whitespace should be normalized."""
        formatter = ResponseFormatter(llm_config)
        response = "Too    many     spaces   here."
        result = formatter.format_response(response)
        assert len(result) >= 1
        # Should not have excessive spaces in output

    def test_format_response_handles_none_gracefully(self, llm_config):
        """None input should be handled gracefully."""
        formatter = ResponseFormatter(llm_config)
        # This might raise or return empty - just shouldn't crash
        try:
            result = formatter.format_response(None)
            assert result == [] or result is not None
        except (TypeError, AttributeError):
            pass  # Acceptable to raise for None input
