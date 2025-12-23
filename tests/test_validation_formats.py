import pytest
from unittest.mock import Mock
from kryten_llm.components.validator import ResponseValidator, ValidationResult
from kryten_llm.models.config import ValidationConfig

@pytest.fixture
def mock_config():
    config = Mock(spec=ValidationConfig)
    config.min_length = 10
    config.max_length = 500
    config.check_repetition = True
    config.repetition_history_size = 5
    config.repetition_threshold = 0.8
    config.check_inappropriate = True
    config.inappropriate_patterns = [r"badword"]
    config.check_relevance = False
    return config

@pytest.fixture
def validator(mock_config):
    return ResponseValidator(mock_config)

class TestValidationFormats:
    """Test validation with different response formats."""

    def test_validate_json_response(self, validator):
        """Test validation of JSON formatted response."""
        json_response = '{"response": "This is a valid JSON response.", "status": "ok"}'
        user_message = "test"
        
        result = validator.validate_response(json_response, user_message)
        assert result.valid
        assert result.severity == "INFO"

    def test_validate_json_response_too_short(self, validator, mock_config):
        """Test validation of short JSON response."""
        mock_config.min_length = 50
        # Length is 41 chars
        json_response = '{"key": "val"}' 
        user_message = "test"
        
        result = validator.validate_response(json_response, user_message)
        assert not result.valid
        assert "too short" in result.reason

    def test_validate_json_inappropriate(self, validator):
        """Test validation of JSON containing inappropriate content."""
        json_response = '{"message": "This contains a badword here."}'
        user_message = "test"
        
        result = validator.validate_response(json_response, user_message)
        assert not result.valid
        assert "inappropriate content" in result.reason

    def test_validate_xml_response(self, validator):
        """Test validation of XML formatted response."""
        xml_response = '<response>This is a valid XML response.</response>'
        user_message = "test"
        
        result = validator.validate_response(xml_response, user_message)
        assert result.valid

    def test_validate_xml_inappropriate(self, validator):
        """Test validation of XML containing inappropriate content."""
        xml_response = '<response>This contains a badword.</response>'
        user_message = "test"
        
        result = validator.validate_response(xml_response, user_message)
        assert not result.valid
        assert "inappropriate content" in result.reason

    def test_validate_markdown_response(self, validator):
        """Test validation of Markdown formatted response."""
        md_response = "**Bold** and *Italic* text with `code`."
        user_message = "test"
        
        result = validator.validate_response(md_response, user_message)
        assert result.valid
