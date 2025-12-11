"""Unit tests for ResponseFormatter component."""

import pytest

from kryten_llm.components.formatter import ResponseFormatter
from kryten_llm.models.config import LLMConfig


@pytest.mark.asyncio
class TestResponseFormatter:
    """Test ResponseFormatter message formatting and splitting."""

    async def test_format_short_response(self, llm_config: LLMConfig):
        """Test that short responses are returned as single item."""
        formatter = ResponseFormatter(llm_config)
        response = "Great question! Enter the Dragon is a classic."
        
        result = await formatter.format_response(response)
        
        assert len(result) == 1
        assert result[0] == response

    async def test_format_long_response_splits(self, llm_config: LLMConfig):
        """Test that long responses are split into multiple parts."""
        formatter = ResponseFormatter(llm_config)
        # Create a response longer than 240 chars
        response = "a" * 300
        
        result = await formatter.format_response(response)
        
        assert len(result) > 1
        # Each part should be <= 240 chars
        for part in result:
            assert len(part) <= 240

    async def test_format_response_at_boundary(self, llm_config: LLMConfig):
        """Test response exactly at max length."""
        formatter = ResponseFormatter(llm_config)
        response = "a" * 240
        
        result = await formatter.format_response(response)
        
        assert len(result) == 1
        assert result[0] == response

    async def test_format_response_one_over_boundary(self, llm_config: LLMConfig):
        """Test response just over max length splits."""
        formatter = ResponseFormatter(llm_config)
        response = "a" * 241
        
        result = await formatter.format_response(response)
        
        assert len(result) == 2

    async def test_format_removes_self_reference_prefix(self, llm_config: LLMConfig):
        """Test that 'As CharacterName,' prefix is removed."""
        formatter = ResponseFormatter(llm_config)
        response = "As CynthiaRothbot, I believe that discipline is key."
        
        result = await formatter.format_response(response)
        
        assert len(result) == 1
        assert not result[0].startswith("As CynthiaRothbot")
        assert "I believe that discipline is key" in result[0]

    async def test_format_removes_self_reference_with_i(self, llm_config: LLMConfig):
        """Test that 'As CharacterName I' prefix is removed."""
        formatter = ResponseFormatter(llm_config)
        response = "As CynthiaRothbot I think martial arts are amazing."
        
        result = await formatter.format_response(response)
        
        assert len(result) == 1
        assert not result[0].startswith("As CynthiaRothbot")
        assert "think martial arts are amazing" in result[0]

    async def test_format_case_insensitive_self_reference(self, llm_config: LLMConfig):
        """Test that self-reference removal is case-insensitive."""
        formatter = ResponseFormatter(llm_config)
        response = "as cynthiarothbot, I believe that's true."
        
        result = await formatter.format_response(response)
        
        assert len(result) == 1
        assert not result[0].lower().startswith("as cynthiarothbot")

    async def test_format_preserves_content(self, llm_config: LLMConfig):
        """Test that actual content is preserved."""
        formatter = ResponseFormatter(llm_config)
        response = "Enter the Dragon changed cinema forever!"
        
        result = await formatter.format_response(response)
        
        assert len(result) == 1
        assert result[0] == response

    async def test_format_strips_whitespace(self, llm_config: LLMConfig):
        """Test that leading/trailing whitespace is removed."""
        formatter = ResponseFormatter(llm_config)
        response = "   Martial arts teach discipline.   "
        
        result = await formatter.format_response(response)
        
        assert len(result) == 1
        assert result[0] == "Martial arts teach discipline."
        assert not result[0].startswith(" ")
        assert not result[0].endswith(" ")

    async def test_format_empty_response(self, llm_config: LLMConfig):
        """Test handling of empty response."""
        formatter = ResponseFormatter(llm_config)
        response = ""
        
        result = await formatter.format_response(response)
        
        assert len(result) == 0

    async def test_format_whitespace_only_response(self, llm_config: LLMConfig):
        """Test handling of whitespace-only response."""
        formatter = ResponseFormatter(llm_config)
        response = "   "
        
        result = await formatter.format_response(response)
        
        assert len(result) == 0

    async def test_split_continuation_indicators(self, llm_config: LLMConfig):
        """Test that split messages include continuation indicators."""
        formatter = ResponseFormatter(llm_config)
        # Create message that needs splitting
        response = "The path of the warrior is not about seeking glory or recognition. It's about discipline, dedication, and the pursuit of excellence in every movement. True mastery comes from within, through countless hours of practice and self-reflection. Every technique must be executed with intention."
        
        result = await formatter.format_response(response)
        
        assert len(result) > 1
        # First part should end with "..."
        assert result[0].endswith("...")
        # Middle/last parts should start with "..."
        for part in result[1:]:
            assert part.startswith("...")

    async def test_split_preserves_all_content(self, llm_config: LLMConfig):
        """Test that splitting preserves all content."""
        formatter = ResponseFormatter(llm_config)
        response = "a" * 500
        
        result = await formatter.format_response(response)
        
        # Reconstruct by removing "..." indicators
        reconstructed = ""
        for i, part in enumerate(result):
            if i == 0:
                # First part: remove trailing "..."
                reconstructed += part.rstrip(".")
            elif i == len(result) - 1:
                # Last part: remove leading "..."
                reconstructed += part.lstrip(".")
            else:
                # Middle parts: remove both
                reconstructed += part.strip(".")
        
        # Should have same number of 'a's (allowing for some "..." chars)
        assert len([c for c in reconstructed if c == 'a']) >= 490  # Close to original

    async def test_format_none_response(self, llm_config: LLMConfig):
        """Test handling of None response."""
        formatter = ResponseFormatter(llm_config)
        
        # None is handled gracefully (treated as empty)
        result = await formatter.format_response(None)
        assert len(result) == 0

    async def test_max_length_from_config(self, llm_config: LLMConfig):
        """Test that max length is read from config."""
        formatter = ResponseFormatter(llm_config)
        
        assert formatter.max_length == llm_config.message_processing.max_message_length
        assert formatter.max_length == 240

    async def test_character_name_from_config(self, llm_config: LLMConfig):
        """Test that character name is read from config."""
        formatter = ResponseFormatter(llm_config)
        
        assert formatter.character_name == llm_config.personality.character_name
        assert formatter.character_name == "CynthiaRothbot"
