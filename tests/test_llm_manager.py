"""Unit tests for LLMManager component.

NOTE: These tests are for the old Phase 1/2 LLMManager API which used
generate_response(prompt, context). The current Phase 3 LLMManager uses
generate_response(LLMRequest) instead. Use test_llm_manager_phase3.py for
testing the current implementation.
"""

import pytest

# Skip all tests - they use the old API signature
pytestmark = pytest.mark.skip(
    reason="Tests use old LLMManager API signature (prompt, context). "
    "See test_llm_manager_phase3.py for current Phase 3 API tests."
)

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp

from kryten_llm.components.llm_manager import LLMManager
from kryten_llm.models.config import LLMConfig


@pytest.mark.asyncio
class TestLLMManager:
    """Test LLMManager API interactions with mocked responses."""

    async def test_generate_response_success(self, llm_config: LLMConfig):
        """Test successful LLM API call."""
        manager = LLMManager(llm_config)
        
        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "choices": [
                {
                    "message": {
                        "content": "Great to hear from you!"
                    }
                }
            ]
        })
        
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock()
        ))
        
        with patch('aiohttp.ClientSession', return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_session),
            __aexit__=AsyncMock()
        )):
            result = await manager.generate_response(
                "You are a helpful assistant",
                "Hello, how are you?"
            )
        
        assert result == "Great to hear from you!"

    async def test_generate_response_api_error(self, llm_config: LLMConfig):
        """Test handling of API error response."""
        manager = LLMManager(llm_config)
        
        # Mock error response
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")
        
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock()
        ))
        
        with patch('aiohttp.ClientSession', return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_session),
            __aexit__=AsyncMock()
        )):
            result = await manager.generate_response(
                "System prompt",
                "User prompt"
            )
        
        assert result is None

    async def test_generate_response_timeout(self, llm_config: LLMConfig):
        """Test handling of timeout."""
        manager = LLMManager(llm_config)
        
        # Mock timeout by raising TimeoutError
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = MagicMock()
            mock_session.post = MagicMock(side_effect=asyncio.TimeoutError())
            mock_session_class.return_value = AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock()
            )
            
            result = await manager.generate_response(
                "System prompt",
                "User prompt"
            )
        
        assert result is None

    async def test_generate_response_network_error(self, llm_config: LLMConfig):
        """Test handling of network error."""
        manager = LLMManager(llm_config)
        
        # Mock network error
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = MagicMock()
            mock_session.post = MagicMock(
                side_effect=aiohttp.ClientError("Connection failed")
            )
            mock_session_class.return_value = AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock()
            )
            
            result = await manager.generate_response(
                "System prompt",
                "User prompt"
            )
        
        assert result is None

    async def test_generate_response_invalid_format(self, llm_config: LLMConfig):
        """Test handling of invalid API response format."""
        manager = LLMManager(llm_config)
        
        # Mock response with missing choices
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"error": "No choices"})
        
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock()
        ))
        
        with patch('aiohttp.ClientSession', return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_session),
            __aexit__=AsyncMock()
        )):
            result = await manager.generate_response(
                "System prompt",
                "User prompt"
            )
        
        assert result is None

    async def test_generate_response_empty_choices(self, llm_config: LLMConfig):
        """Test handling of empty choices array."""
        manager = LLMManager(llm_config)
        
        # Mock response with empty choices
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"choices": []})
        
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock()
        ))
        
        with patch('aiohttp.ClientSession', return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_session),
            __aexit__=AsyncMock()
        )):
            result = await manager.generate_response(
                "System prompt",
                "User prompt"
            )
        
        assert result is None

    async def test_uses_default_provider(self, llm_config: LLMConfig):
        """Test that default provider is used when none specified."""
        manager = LLMManager(llm_config)
        
        assert manager.default_provider == llm_config.llm_providers["test"]
        assert manager.default_provider.name == "test"

    async def test_invalid_provider_name(self, llm_config: LLMConfig):
        """Test handling of invalid provider name."""
        manager = LLMManager(llm_config)
        
        result = await manager.generate_response(
            "System prompt",
            "User prompt",
            provider_name="nonexistent"
        )
        
        assert result is None
