
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from kryten_llm.components.trigger_engine import TriggerEngine
from kryten_llm.models.config import LLMConfig
from kryten_llm.models.phase3 import VideoMetadata

@pytest.fixture
def mock_client():
    client = AsyncMock()
    # Mock the _nats attribute for KV store access
    client._nats = AsyncMock()
    return client

@pytest.mark.asyncio
async def test_sync_state_fresh_start(llm_config: LLMConfig, mock_client):
    """Test syncing when engine has no state but context has video."""
    engine = TriggerEngine(llm_config)
    
    # Engine state is empty
    assert engine.last_qualifying_media is None
    
    # Context has video
    video = VideoMetadata(
        title="Startup Movie",
        duration=3600,
        type="movie",
        queued_by="user",
        timestamp=datetime.now()
    )
    
    # Mock the kv_store functions
    with patch('kryten_llm.components.trigger_engine.get_kv_store') as mock_get_bucket, \
         patch('kryten_llm.components.trigger_engine.kv_put') as mock_kv_put:
        
        mock_bucket = AsyncMock()
        mock_get_bucket.return_value = mock_bucket
        
        await engine.sync_state_from_context(video, mock_client)
        
        # Verify update and save
        assert engine.last_qualifying_media["title"] == "Startup Movie"
        assert engine.last_qualifying_media["duration"] == 3600
        mock_kv_put.assert_called_once()
        mock_get_bucket.assert_called()

@pytest.mark.asyncio
async def test_sync_state_update_needed(llm_config: LLMConfig, mock_client):
    """Test syncing when engine has stale state."""
    engine = TriggerEngine(llm_config)
    engine.last_qualifying_media = {"title": "Old Movie", "duration": 100}
    
    # Context has NEW video (bot was down during transition)
    video = VideoMetadata(
        title="Current Movie",
        duration=5000,
        type="movie",
        queued_by="user",
        timestamp=datetime.now()
    )
    
    # Mock the kv_store functions
    with patch('kryten_llm.components.trigger_engine.get_kv_store') as mock_get_bucket, \
          patch('kryten_llm.components.trigger_engine.kv_put') as mock_kv_put:
        
        mock_bucket = AsyncMock()
        mock_get_bucket.return_value = mock_bucket
        
        await engine.sync_state_from_context(video, mock_client)
        
        # Verify update to CURRENT
        assert engine.last_qualifying_media["title"] == "Current Movie"
        mock_kv_put.assert_called_once()

@pytest.mark.asyncio
async def test_sync_state_no_change(llm_config: LLMConfig, mock_client):
    """Test syncing when state matches (no save needed)."""
    engine = TriggerEngine(llm_config)
    engine.last_qualifying_media = {"title": "Same Movie", "duration": 3600}
    
    video = VideoMetadata(
        title="Same Movie",
        duration=3600,
        type="movie",
        queued_by="user",
        timestamp=datetime.now()
    )
    
    # Mock the kv_store functions
    with patch('kryten_llm.components.trigger_engine.get_kv_store') as mock_get_bucket, \
          patch('kryten_llm.components.trigger_engine.kv_put') as mock_kv_put:
        
        mock_bucket = AsyncMock()
        mock_get_bucket.return_value = mock_bucket
        
        await engine.sync_state_from_context(video, mock_client)
        
        # Verify NO save
        mock_kv_put.assert_not_called()

@pytest.mark.asyncio
async def test_sync_state_with_dict(llm_config: LLMConfig, mock_client):
    """Test syncing with raw dict (fallback)."""
    engine = TriggerEngine(llm_config)
    
    video_dict = {
        "title": "Dict Movie",
        "seconds": 1200
    }
    
    # Mock the kv_store functions
    with patch('kryten_llm.components.trigger_engine.get_kv_store') as mock_get_bucket, \
          patch('kryten_llm.components.trigger_engine.kv_put') as mock_kv_put:
        
        mock_bucket = AsyncMock()
        mock_get_bucket.return_value = mock_bucket
        
        await engine.sync_state_from_context(video_dict, mock_client)
        
        assert engine.last_qualifying_media["title"] == "Dict Movie"
        assert engine.last_qualifying_media["duration"] == 1200
        mock_kv_put.assert_called_once()
