import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from kryten_llm.components.trigger_engine import TriggerEngine
from kryten_llm.components.prompt_builder import PromptBuilder
from kryten_llm.models.config import LLMConfig, MediaChangeConfig

@pytest.fixture
def mock_client():
    client = AsyncMock()
    # Mock KV store
    client.kv_store = {}
    
    # Store the bucket name for reference
    client._bucket_name = "kryten_llm_trigger_state"
    
    return client

@pytest.mark.asyncio
class TestMediaTrigger:
    
    async def test_media_trigger_disabled(self, llm_config: LLMConfig, mock_client):
        llm_config.media_change.enabled = False
        engine = TriggerEngine(llm_config)
        
        result = await engine.check_media_change(
            {"title": "Long Movie", "duration": 3600}, 
            mock_client
        )
        assert result is None

    async def test_duration_threshold(self, llm_config: LLMConfig, mock_client):
        llm_config.media_change.enabled = True
        llm_config.media_change.min_duration_minutes = 30  # 1800 seconds
        
        engine = TriggerEngine(llm_config)
        
        # Short media (10 mins)
        result = await engine.check_media_change(
            {"title": "Short Clip", "duration": 600},
            mock_client
        )
        assert result is None
        
        # Long media (60 mins)
        result = await engine.check_media_change(
            {"title": "Long Movie", "duration": 3600},
            mock_client
        )
        assert result is not None
        assert result.triggered is True
        assert result.trigger_type == "media_change"
        assert result.context["current_media_title"] == "Long Movie"

    async def test_state_tracking(self, llm_config: LLMConfig, mock_client):
        llm_config.media_change.enabled = True
        llm_config.media_change.min_duration_minutes = 10
        
        engine = TriggerEngine(llm_config)
        
        # Mock the kryten.kv_store functions
        mock_bucket = AsyncMock()
        with patch('kryten_llm.components.trigger_engine.get_kv_store') as mock_get_bucket, \
             patch('kryten_llm.components.trigger_engine.kv_put') as mock_kv_put:
            
            mock_get_bucket.return_value = mock_bucket
            
            # First movie
            await engine.check_media_change(
                {"title": "Movie 1", "duration": 3600},
                mock_client
            )
            
            # Verify state saved
            assert mock_kv_put.called
            assert engine.last_qualifying_media["title"] == "Movie 1"
            
            # Second movie
            result = await engine.check_media_change(
                {"title": "Movie 2", "duration": 3600},
                mock_client
            )
            
            # Verify previous media in context
            assert result.context["previous_media_title"] == "Movie 1"
            assert engine.last_qualifying_media["title"] == "Movie 2"

    async def test_prompt_generation(self, llm_config: LLMConfig):
        builder = PromptBuilder(llm_config)
        
        template_data = {
            "current_media_title": "The Matrix",
            "current_media_duration": "120m",
            "previous_media_title": "Inception",
            "transition_explanation": "Change detected."
        }
        
        chat_history = [
            {"username": "user1", "msg": "hello"},
            {"username": "user2", "msg": "world"}
        ]
        
        prompt = builder.build_media_change_prompt(template_data, chat_history)
        
        assert "The Matrix" in prompt
        assert "120m" in prompt
        assert "Inception" in prompt
        assert "user1: hello" in prompt
        assert "user2: world" in prompt

    async def test_kv_persistence(self, llm_config: LLMConfig, mock_client):
        """Test loading state from KV."""
        llm_config.media_change.enabled = True
        
        # Pre-populate KV
        mock_client.kv_store["kryten_llm_trigger_state:last_qualifying_media"] = {
            "title": "Old Movie",
            "duration": 5000
        }
        
        engine = TriggerEngine(llm_config)
        
        # Mock the kryten.kv_store functions
        mock_bucket = AsyncMock()
        with patch('kryten_llm.components.trigger_engine.get_kv_store') as mock_get_bucket, \
             patch('kryten_llm.components.trigger_engine.kv_get') as mock_kv_get:
            
            mock_get_bucket.return_value = mock_bucket
            mock_kv_get.return_value = mock_client.kv_store["kryten_llm_trigger_state:last_qualifying_media"]
            
            await engine.load_media_state(mock_client)
            
            assert engine.last_qualifying_media["title"] == "Old Movie"
            
            # Trigger new event
            with patch('kryten_llm.components.trigger_engine.kv_put') as mock_kv_put:
                result = await engine.check_media_change(
                    {"title": "New Movie", "duration": 3600},
                    mock_client
                )
                
                assert result.context["previous_media_title"] == "Old Movie"
