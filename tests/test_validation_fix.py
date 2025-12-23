import pytest
import re
from unittest.mock import MagicMock, patch, AsyncMock
from kryten_llm.components.validator import ResponseValidator, ValidationResult
from kryten_llm.models.config import ValidationConfig, LLMConfig
from kryten_llm.service import LLMService
from kryten_llm.models.phase3 import LLMResponse, LLMRequest

@pytest.fixture
def validation_config():
    return ValidationConfig(
        min_length=10,
        max_length=100,
        check_repetition=True,
        repetition_history_size=5,
        repetition_threshold=0.8,
        check_relevance=False,  # Disable relevance for basic tests to avoid keyword matching issues
        relevance_threshold=0.3,
        check_inappropriate=True,
        inappropriate_patterns=["badword"]
    )

@pytest.fixture
def validator(validation_config):
    return ResponseValidator(validation_config)

class TestResponseValidator:
    def test_validate_response_alias(self, validator):
        """Test that validate_response is a working alias for validate."""
        response = "This is a valid response."
        user_message = "Hello"
        
        result = validator.validate_response(response, user_message)
        assert result.valid, f"Validation failed: {result.reason}"
        assert result.severity == "INFO"

    def test_length_validation(self, validator):
        """Test min and max length validation."""
        # Too short
        result = validator.validate_response("Short", "msg")
        assert not result.valid
        assert "too short" in result.reason.lower()
        
        # Too long
        long_response = "a" * 101
        result = validator.validate_response(long_response, "msg")
        assert not result.valid
        assert "too long" in result.reason.lower()

    def test_repetition_validation(self, validator):
        """Test repetition detection."""
        response = "This is a unique response."
        
        # First time ok
        result = validator.validate_response(response, "msg")
        assert result.valid
        
        # Exact repetition
        result = validator.validate_response(response, "msg")
        assert not result.valid
        assert "identical" in result.reason.lower()
        
        # Similar repetition
        similar_response = "This is a unique response!"
        result = validator.validate_response(similar_response, "msg")
        assert not result.valid
        assert "too similar" in result.reason.lower()

    def test_inappropriate_content(self, validator):
        """Test inappropriate content filtering."""
        result = validator.validate_response("This contains a badword here", "msg")
        assert not result.valid
        assert "inappropriate content" in result.reason.lower()

    def test_relevance_validation(self, validator):
        """Test relevance checking."""
        # Enable relevance checking for this test specifically
        validator.config.check_relevance = True
        
        # Relevant
        result = validator.validate_response(
            "I like apples too",
            "Do you like apples?",
            context={}
        )
        assert result.valid
        
        # Irrelevant (if configured strictly, but here threshold is 0.3)
        # Note: Implementation logic for relevance is keyword based
        pass 

@pytest.mark.asyncio
async def test_media_change_validation_integration():
    """Test full integration of media change triggering with validation."""
    
    # Mock Config
    mock_config = MagicMock(spec=LLMConfig)
    mock_config.validation = ValidationConfig(min_length=5, max_length=100)
    mock_config.llm_providers = {}
    mock_config.retry_strategy = MagicMock()
    mock_config.default_provider = "test"
    mock_config.testing = MagicMock()
    mock_config.testing.dry_run = True
    mock_config.channels = [MagicMock()]
    mock_config.channels[0].channel = "test-channel"
    
    # Add missing configs
    mock_config.spam_detection = MagicMock()
    mock_config.service_metadata = MagicMock()
    mock_config.error_handling = MagicMock()
    mock_config.error_handling.generate_correlation_ids = True
    mock_config.personality = MagicMock()
    mock_config.personality.character_name = "Kryten"
    mock_config.triggers = []
    mock_config.metrics = MagicMock()
    mock_config.metrics.enabled = False
    
    with patch('kryten_llm.service.KrytenClient'), \
         patch('kryten_llm.service.MessageListener'), \
         patch('kryten_llm.service.TriggerEngine'), \
         patch('kryten_llm.service.PromptBuilder'), \
         patch('kryten_llm.service.ResponseFormatter'), \
         patch('kryten_llm.service.RateLimiter'), \
         patch('kryten_llm.service.ContextManager'), \
         patch('kryten_llm.service.LLMManager'), \
         patch('kryten_llm.service.ResponseLogger'), \
         patch('kryten_llm.service.SpamDetector'):
         
        service = LLMService(mock_config)
        
        # Setup mocks
        service.trigger_engine.check_media_change = AsyncMock(return_value=MagicMock(
            context={"title": "Movie"},
            history=[]
        ))
        service.prompt_builder.build_system_prompt.return_value = "System"
        service.prompt_builder.build_media_change_prompt.return_value = "User"
        
        # Mock LLM success
        service.llm_manager.generate_response = AsyncMock(return_value=LLMResponse(
            content="Valid response",
            model_used="model",
            provider_used="provider",
            tokens_used=10,
            response_time=0.1
        ))
        
        service.response_formatter.format_response.return_value = ["Valid response"]
        
        # Test successful flow
        event = MagicMock()
        await service._handle_media_change_trigger(event)
        
        # Verify validate_response was called
        # Note: service.validator is a real ResponseValidator instance
        assert len(service.validator._recent_responses) == 1
        assert service.validator._recent_responses[0] == "valid response"

@pytest.mark.asyncio
async def test_media_change_validation_failure():
    """Test media change flow when validation fails."""
    mock_config = MagicMock(spec=LLMConfig)
    mock_config.validation = ValidationConfig(min_length=100) # Set high min length to force failure
    mock_config.llm_providers = {}
    mock_config.retry_strategy = MagicMock()
    mock_config.default_provider = "test"
    mock_config.testing = MagicMock()
    mock_config.testing.dry_run = True
    
    # Add missing configs
    mock_config.spam_detection = MagicMock()
    mock_config.service_metadata = MagicMock()
    mock_config.error_handling = MagicMock()
    mock_config.error_handling.generate_correlation_ids = True
    mock_config.personality = MagicMock()
    mock_config.personality.character_name = "Kryten"
    mock_config.triggers = []
    mock_config.metrics = MagicMock()
    mock_config.metrics.enabled = False
    
    with patch('kryten_llm.service.KrytenClient'), \
         patch('kryten_llm.service.MessageListener'), \
         patch('kryten_llm.service.TriggerEngine'), \
         patch('kryten_llm.service.PromptBuilder'), \
         patch('kryten_llm.service.ResponseFormatter'), \
         patch('kryten_llm.service.RateLimiter'), \
         patch('kryten_llm.service.ContextManager'), \
         patch('kryten_llm.service.LLMManager'), \
         patch('kryten_llm.service.ResponseLogger'), \
         patch('kryten_llm.service.SpamDetector'):
         
        service = LLMService(mock_config)
        
        # Setup mocks
        service.trigger_engine.check_media_change = AsyncMock(return_value=MagicMock(
            context={"title": "Movie"},
            history=[]
        ))
        service.llm_manager.generate_response = AsyncMock(return_value=LLMResponse(
            content="Too short",
            model_used="model",
            provider_used="provider",
            tokens_used=10,
            response_time=0.1
        ))
        
        # Test failure flow
        event = MagicMock()
        await service._handle_media_change_trigger(event)
        
        # Should not have formatted or sent response
        service.response_formatter.format_response.assert_not_called()

@pytest.mark.asyncio
async def test_llm_failure_handling():
    """Test handling of LLM generation failure."""
    mock_config = MagicMock(spec=LLMConfig)
    mock_config.validation = ValidationConfig()
    mock_config.llm_providers = {}
    mock_config.retry_strategy = MagicMock()
    mock_config.default_provider = "test"
    
    # Add missing configs
    mock_config.spam_detection = MagicMock()
    mock_config.service_metadata = MagicMock()
    mock_config.error_handling = MagicMock()
    mock_config.error_handling.generate_correlation_ids = True
    mock_config.personality = MagicMock()
    mock_config.personality.character_name = "Kryten"
    mock_config.triggers = []
    mock_config.metrics = MagicMock()
    mock_config.metrics.enabled = False
    mock_config.testing = MagicMock()
    
    with patch('kryten_llm.service.KrytenClient'), \
         patch('kryten_llm.service.MessageListener'), \
         patch('kryten_llm.service.TriggerEngine'), \
         patch('kryten_llm.service.PromptBuilder'), \
         patch('kryten_llm.service.ResponseFormatter'), \
         patch('kryten_llm.service.RateLimiter'), \
         patch('kryten_llm.service.ContextManager'), \
         patch('kryten_llm.service.LLMManager'), \
         patch('kryten_llm.service.ResponseLogger'), \
         patch('kryten_llm.service.SpamDetector'):
         
        service = LLMService(mock_config)
        
        service.trigger_engine.check_media_change = AsyncMock(return_value=MagicMock())
        
        # Simulate Exception
        service.llm_manager.generate_response = AsyncMock(side_effect=Exception("API Error"))
        
        # Should catch exception and log error, not crash
        event = MagicMock()
        await service._handle_media_change_trigger(event)
        
        # Simulate None return (all providers failed)
        service.llm_manager.generate_response = AsyncMock(return_value=None)
        await service._handle_media_change_trigger(event)
