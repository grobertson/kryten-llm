import pytest
import time
import string
import random
from unittest.mock import Mock
from kryten_llm.components.validator import ResponseValidator, ValidationResult
from kryten_llm.models.config import ValidationConfig

@pytest.fixture
def mock_config():
    config = Mock(spec=ValidationConfig)
    config.min_length = 10
    config.max_length = 100000 # Allow large responses for stress test
    config.check_repetition = True
    config.repetition_history_size = 50
    config.repetition_threshold = 0.8
    config.check_inappropriate = True
    config.inappropriate_patterns = [r"badword"]
    config.check_relevance = False
    return config

@pytest.fixture
def validator(mock_config):
    return ResponseValidator(mock_config)

class TestValidationStress:
    """Stress tests for validation system."""

    def test_validation_performance(self, validator, mock_config):
        """Test validation performance with many iterations."""
        # Disable repetition check to avoid failures on identical inputs
        mock_config.check_repetition = False
        
        iterations = 1000
        start_time = time.time()
        
        response = "This is a standard response for performance testing."
        user_message = "test"
        
        for _ in range(iterations):
            result = validator.validate_response(response, user_message)
            assert result.valid
            
        duration = time.time() - start_time
        avg_time = duration / iterations
        
        # Ensure it's reasonably fast (e.g., < 1ms per validation)
        assert avg_time < 0.001, f"Validation too slow: {avg_time*1000:.2f}ms per call"

    def test_large_input_validation(self, validator):
        """Test validation with very large input."""
        # Generate 50KB string
        large_response = "word " * 10000
        user_message = "test"
        
        start_time = time.time()
        result = validator.validate_response(large_response, user_message)
        duration = time.time() - start_time
        
        assert result.valid
        assert duration < 0.1, f"Large input validation too slow: {duration:.4f}s"

    def test_repetition_history_stress(self, validator, mock_config):
        """Test repetition checking with full history."""
        # Fill history
        for i in range(mock_config.repetition_history_size):
            validator.validate_response(f"Unique response {i}", "test")
            
        # Validate new response against full history
        start_time = time.time()
        result = validator.validate_response("Another unique response", "test")
        duration = time.time() - start_time
        
        assert result.valid
        assert duration < 0.01, f"History check too slow: {duration:.4f}s"
