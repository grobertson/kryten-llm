import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from kryten_llm.components.llm_manager import LLMManager
from kryten_llm.models.phase3 import LLMRequest, LLMResponse
from kryten_llm.models.config import LLMConfig

@pytest.fixture
def mock_config():
    config = MagicMock(spec=LLMConfig)
    config.llm_providers = {}
    config.retry_strategy = MagicMock()
    config.retry_strategy.initial_delay = 0.1
    config.default_provider = "test-provider"
    
    # Add validation config
    config.validation = MagicMock()
    
    # Add other potentially needed configs
    config.spam_detection = MagicMock()
    config.testing = MagicMock()
    config.testing.dry_run = False
    config.channels = [MagicMock()]
    config.channels[0].channel = "test-channel"
    
    return config

@pytest.mark.asyncio
async def test_generate_response_legacy_signature(mock_config):
    """Test generate_response with legacy/incorrect signature (str, str, provider_name)."""
    manager = LLMManager(mock_config)
    
    # Mock _try_provider to return a dummy response
    mock_response = LLMResponse(
        content="Test response",
        model_used="test-model",
        provider_used="test-provider",
        tokens_used=10,
        response_time=0.1
    )
    manager._try_provider = AsyncMock(return_value=mock_response)
    
    # Mock providers
    manager.providers = {"test-provider": MagicMock()}
    manager._get_provider_priority = MagicMock(return_value=["test-provider"])
    
    # Call with legacy signature
    system_prompt = "System prompt"
    user_prompt = "User prompt"
    provider_name = "test-provider"
    
    # This should now pass with a warning (which we won't assert on, but verify functionality)
    response = await manager.generate_response(
        system_prompt, 
        user_prompt, 
        provider_name=provider_name
    )
    assert response.content == "Test response"

@pytest.mark.asyncio
async def test_generate_response_correct_signature(mock_config):
    """Test generate_response with correct LLMRequest signature."""
    manager = LLMManager(mock_config)
    
    mock_response = LLMResponse(
        content="Test response",
        model_used="test-model",
        provider_used="test-provider",
        tokens_used=10,
        response_time=0.1
    )
    manager._try_provider = AsyncMock(return_value=mock_response)
    manager.providers = {"test-provider": MagicMock()}
    manager._get_provider_priority = MagicMock(return_value=["test-provider"])
    
    request = LLMRequest(
        system_prompt="System",
        user_prompt="User",
        preferred_provider="test-provider"
    )
    
    response = await manager.generate_response(request)
    assert response.content == "Test response"

@pytest.mark.asyncio
async def test_handle_media_change_trigger(mock_config):
    """Test _handle_media_change_trigger with the fix."""
    with patch('kryten_llm.service.KrytenClient'), \
         patch('kryten_llm.service.MessageListener'), \
         patch('kryten_llm.service.TriggerEngine'), \
         patch('kryten_llm.service.PromptBuilder'), \
         patch('kryten_llm.service.ResponseFormatter'), \
         patch('kryten_llm.service.RateLimiter'), \
         patch('kryten_llm.service.ContextManager'), \
         patch('kryten_llm.service.LLMManager'), \
         patch('kryten_llm.service.ResponseLogger'), \
         patch('kryten_llm.service.ResponseValidator'), \
         patch('kryten_llm.service.SpamDetector'):
         
        from kryten_llm.service import LLMService
        service = LLMService(mock_config)
        
        # Setup mocks
        service.trigger_engine.check_media_change = AsyncMock(return_value=MagicMock(
            context={"title": "Test Movie"},
            history=[]
        ))
        service.prompt_builder.build_system_prompt = MagicMock(return_value="System Prompt")
        service.prompt_builder.build_media_change_prompt = MagicMock(return_value="User Prompt")
        
        service.llm_manager.generate_response = AsyncMock(return_value=LLMResponse(
            content="Generated Response",
            model_used="model",
            provider_used="provider",
            tokens_used=10,
            response_time=0.1
        ))
        
        service.validator.validate_response = MagicMock(return_value=MagicMock(is_valid=True))
        service.response_formatter.format_response = MagicMock(return_value=["Formatted Response"])
        service.client.send_message = AsyncMock()
        
        # Create a mock event
        event = MagicMock()
        event.title = "Test Movie"
        event.duration = 120
        event.media_type = "yt"
        
        # Call the method
        await service._handle_media_change_trigger(event)
        
        # Verify generate_response was called with LLMRequest
        assert service.llm_manager.generate_response.called
        call_args = service.llm_manager.generate_response.call_args
        assert len(call_args[0]) == 1
        request = call_args[0][0]
        assert isinstance(request, LLMRequest)
        assert request.system_prompt == "System Prompt"
        assert request.user_prompt == "User Prompt"
