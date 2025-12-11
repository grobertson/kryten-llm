"""Unit tests for PromptBuilder component."""

import pytest

from kryten_llm.components.prompt_builder import PromptBuilder
from kryten_llm.models.config import LLMConfig


class TestPromptBuilder:
    """Test PromptBuilder prompt construction."""

    def test_build_system_prompt_includes_character_name(self, llm_config: LLMConfig):
        """Test that system prompt includes character name."""
        builder = PromptBuilder(llm_config)
        prompt = builder.build_system_prompt()
        
        assert llm_config.personality.character_name in prompt

    def test_build_system_prompt_includes_description(self, llm_config: LLMConfig):
        """Test that system prompt includes character description."""
        builder = PromptBuilder(llm_config)
        prompt = builder.build_system_prompt()
        
        assert llm_config.personality.character_description in prompt

    def test_build_system_prompt_includes_traits(self, llm_config: LLMConfig):
        """Test that system prompt includes personality traits."""
        builder = PromptBuilder(llm_config)
        prompt = builder.build_system_prompt()
        
        for trait in llm_config.personality.personality_traits:
            assert trait in prompt

    def test_build_system_prompt_includes_expertise(self, llm_config: LLMConfig):
        """Test that system prompt includes expertise areas."""
        builder = PromptBuilder(llm_config)
        prompt = builder.build_system_prompt()
        
        for area in llm_config.personality.expertise:
            assert area in prompt

    def test_build_system_prompt_includes_response_style(self, llm_config: LLMConfig):
        """Test that system prompt includes response style."""
        builder = PromptBuilder(llm_config)
        prompt = builder.build_system_prompt()
        
        assert llm_config.personality.response_style in prompt

    def test_build_system_prompt_includes_length_limit(self, llm_config: LLMConfig):
        """Test that system prompt includes character limit instruction."""
        builder = PromptBuilder(llm_config)
        prompt = builder.build_system_prompt()
        
        assert "240" in prompt
        assert "character" in prompt.lower()

    def test_build_system_prompt_includes_stay_in_character(self, llm_config: LLMConfig):
        """Test that system prompt includes stay in character instruction."""
        builder = PromptBuilder(llm_config)
        prompt = builder.build_system_prompt()
        
        assert "stay in character" in prompt.lower()

    def test_build_system_prompt_includes_no_markdown(self, llm_config: LLMConfig):
        """Test that system prompt instructs against markdown."""
        builder = PromptBuilder(llm_config)
        prompt = builder.build_system_prompt()
        
        assert "markdown" in prompt.lower()

    def test_build_system_prompt_includes_no_name_prefix(self, llm_config: LLMConfig):
        """Test that system prompt instructs against name prefix."""
        builder = PromptBuilder(llm_config)
        prompt = builder.build_system_prompt()
        
        assert "character name" in prompt.lower()
        assert "start" in prompt.lower()

    def test_build_user_prompt_format(self, llm_config: LLMConfig):
        """Test user prompt format."""
        builder = PromptBuilder(llm_config)
        prompt = builder.build_user_prompt("john", "hello")
        
        assert prompt == "john says: hello"

    def test_build_user_prompt_with_long_message(self, llm_config: LLMConfig):
        """Test user prompt with long message."""
        builder = PromptBuilder(llm_config)
        long_message = "This is a much longer message that goes on and on"
        prompt = builder.build_user_prompt("alice", long_message)
        
        assert prompt == f"alice says: {long_message}"
        assert "alice says:" in prompt
        assert long_message in prompt

    def test_build_user_prompt_preserves_message(self, llm_config: LLMConfig):
        """Test that user prompt preserves exact message content."""
        builder = PromptBuilder(llm_config)
        message = "What's your favorite kung fu movie?"
        prompt = builder.build_user_prompt("bob", message)
        
        assert message in prompt

    def test_build_user_prompt_includes_username(self, llm_config: LLMConfig):
        """Test that user prompt includes username."""
        builder = PromptBuilder(llm_config)
        username = "testuser123"
        prompt = builder.build_user_prompt(username, "hello")
        
        assert username in prompt

    def test_system_prompt_is_consistent(self, llm_config: LLMConfig):
        """Test that system prompt is consistent across calls."""
        builder = PromptBuilder(llm_config)
        prompt1 = builder.build_system_prompt()
        prompt2 = builder.build_system_prompt()
        
        assert prompt1 == prompt2

    def test_system_prompt_not_empty(self, llm_config: LLMConfig):
        """Test that system prompt is not empty."""
        builder = PromptBuilder(llm_config)
        prompt = builder.build_system_prompt()
        
        assert len(prompt) > 0
        assert prompt.strip() == prompt  # No leading/trailing whitespace

    def test_user_prompt_with_special_characters(self, llm_config: LLMConfig):
        """Test user prompt with special characters."""
        builder = PromptBuilder(llm_config)
        message = "Hey! What's up? I'm @home :)"
        prompt = builder.build_user_prompt("user", message)
        
        assert message in prompt
        assert "user says:" in prompt


class TestPromptBuilderPhase2TriggerContext:
    """Test Phase 2 trigger context injection in PromptBuilder."""
    
    def test_user_prompt_with_trigger_context(self, llm_config: LLMConfig):
        """Test user prompt with trigger context appended."""
        builder = PromptBuilder(llm_config)
        message = "praise toddy"
        context = "Respond enthusiastically about Robert Z'Dar"
        
        prompt = builder.build_user_prompt("testuser", message, trigger_context=context)
        
        assert "testuser says: praise toddy" in prompt
        assert f"\n\nContext: {context}" in prompt
        assert prompt.endswith(context)
    
    def test_user_prompt_without_trigger_context(self, llm_config: LLMConfig):
        """Test user prompt without trigger context (Phase 1 behavior)."""
        builder = PromptBuilder(llm_config)
        message = "hello"
        
        prompt = builder.build_user_prompt("testuser", message)
        
        assert prompt == "testuser says: hello"
        assert "Context:" not in prompt
    
    def test_user_prompt_with_none_context(self, llm_config: LLMConfig):
        """Test user prompt with explicit None context."""
        builder = PromptBuilder(llm_config)
        message = "hello"
        
        prompt = builder.build_user_prompt("testuser", message, trigger_context=None)
        
        assert prompt == "testuser says: hello"
        assert "Context:" not in prompt
    
    def test_user_prompt_with_empty_context(self, llm_config: LLMConfig):
        """Test user prompt with empty string context."""
        builder = PromptBuilder(llm_config)
        message = "hello"
        
        prompt = builder.build_user_prompt("testuser", message, trigger_context="")
        
        # Empty context should not append Context section
        assert prompt == "testuser says: hello"
        assert "Context:" not in prompt
    
    def test_user_prompt_context_with_special_characters(self, llm_config: LLMConfig):
        """Test trigger context with special characters."""
        builder = PromptBuilder(llm_config)
        message = "kung fu question"
        context = "Discuss martial arts philosophy: \"strength through discipline\""
        
        prompt = builder.build_user_prompt("testuser", message, trigger_context=context)
        
        assert "testuser says: kung fu question" in prompt
        assert f"\n\nContext: {context}" in prompt
        assert '"strength through discipline"' in prompt
    
    def test_user_prompt_long_context(self, llm_config: LLMConfig):
        """Test user prompt with long trigger context."""
        builder = PromptBuilder(llm_config)
        message = "tell me about it"
        context = "Provide detailed information about this topic including historical background, key figures, and modern relevance"
        
        prompt = builder.build_user_prompt("testuser", message, trigger_context=context)
        
        assert "testuser says: tell me about it" in prompt
        assert f"\n\nContext: {context}" in prompt
        assert context in prompt
    
    def test_user_prompt_context_formatting(self, llm_config: LLMConfig):
        """Test that context is formatted correctly with newlines."""
        builder = PromptBuilder(llm_config)
        message = "test"
        context = "test context"
        
        prompt = builder.build_user_prompt("user", message, trigger_context=context)
        
        # Should have exactly 2 newlines before Context:
        assert "\n\nContext: test context" in prompt
        # Should not have extra newlines
        assert "\n\n\nContext:" not in prompt
