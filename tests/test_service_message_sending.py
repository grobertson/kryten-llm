import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from kryten_llm.models.config import LLMConfig
from kryten_llm.models.phase3 import LLMResponse
from kryten_llm.components.validator import ValidationResult

@pytest.fixture
def mock_config():
    config = MagicMock(spec=LLMConfig)
    config.testing = MagicMock()
    config.testing.dry_run = False
    config.channels = [{"channel": "test-channel"}]
    config.default_provider = "test-provider"
    
    # Validation mocks
    config.validation = MagicMock()
    config.spam_detection = MagicMock()
    config.service_metadata = MagicMock()
    
    return config

@pytest.mark.asyncio
async def test_media_change_sends_chat(mock_config):
    """Test that media change trigger sends message via send_chat."""
    with patch('kryten_llm.service.KrytenClient') as MockClient, \
         patch('kryten_llm.service.TriggerEngine') as MockTriggerEngine, \
         patch('kryten_llm.service.LLMManager') as MockLLMManager, \
         patch('kryten_llm.service.ResponseValidator') as MockValidator, \
         patch('kryten_llm.service.ResponseFormatter') as MockFormatter, \
         patch('kryten_llm.service.PromptBuilder') as MockPromptBuilder, \
         patch('kryten_llm.service.ContextManager'), \
         patch('kryten_llm.service.MessageListener'), \
         patch('kryten_llm.service.RateLimiter'), \
         patch('kryten_llm.service.ResponseLogger'), \
         patch('kryten_llm.service.SpamDetector'):
        
        # Setup mocks
        from kryten_llm.service import LLMService
        service = LLMService(mock_config)
        
        # Mock client instance
        # Note: service.client is set in __init__ using KrytenClient()
        # We need to access the instance that was created
        mock_client_instance = service.client
        mock_client_instance.send_chat = AsyncMock()
        
        # Mock trigger engine result
        mock_trigger_result = MagicMock()
        mock_trigger_result.context = {}
        service.trigger_engine.check_media_change = AsyncMock(return_value=mock_trigger_result)
        
        # Mock prompt builder
        service.prompt_builder.build_media_change_prompt = MagicMock(return_value=("System", "User"))
        
        # Mock LLM response
        mock_response = LLMResponse(
            content="Generated response",
            model_used="test",
            provider_used="test"
        )
        service.llm_manager.generate_response = AsyncMock(return_value=mock_response)
        
        # Mock Validator
        service.validator.validate_response = MagicMock(return_value=ValidationResult(valid=True, reason="ok", severity="INFO"))
        
        # Mock Formatter
        service.response_formatter.format_response = MagicMock(return_value=["Formatted response"])
        
        # Trigger the method
        event = MagicMock()
        await service._handle_media_change_trigger(event)
        
        # Verify send_chat was called
        mock_client_instance.send_chat.assert_called_once_with("test-channel", "Formatted response")

@pytest.mark.asyncio
async def test_media_change_send_error_handling(mock_config):
    """Test that send errors are caught and logged."""
    with patch('kryten_llm.service.KrytenClient') as MockClient, \
         patch('kryten_llm.service.TriggerEngine'), \
         patch('kryten_llm.service.LLMManager') as MockLLMManager, \
         patch('kryten_llm.service.ResponseValidator') as MockValidator, \
         patch('kryten_llm.service.ResponseFormatter') as MockFormatter, \
         patch('kryten_llm.service.PromptBuilder'), \
         patch('kryten_llm.service.ContextManager'), \
         patch('kryten_llm.service.MessageListener'), \
         patch('kryten_llm.service.RateLimiter'), \
         patch('kryten_llm.service.ResponseLogger'), \
         patch('kryten_llm.service.SpamDetector'):
        
        from kryten_llm.service import LLMService
        service = LLMService(mock_config)
        
        # Setup successful generation flow
        service.trigger_engine.check_media_change = AsyncMock(return_value=MagicMock(context={}))
        service.prompt_builder.build_media_change_prompt = MagicMock(return_value=("Sys", "User"))
        service.llm_manager.generate_response = AsyncMock(return_value=LLMResponse(content="msg", model_used="t", provider_used="p"))
        service.validator.validate_response = MagicMock(return_value=ValidationResult(valid=True, reason="ok", severity="INFO"))
        service.response_formatter.format_response = MagicMock(return_value=["msg"])
        
        # Mock send_chat failure
        service.client.send_chat = AsyncMock(side_effect=Exception("Connection failed"))
        
        # Should not raise exception
        await service._handle_media_change_trigger(MagicMock())
        
        # Verify attempt was made
        service.client.send_chat.assert_called_once()
