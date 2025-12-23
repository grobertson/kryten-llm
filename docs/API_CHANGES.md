# API Changes and Developer Guide

## LLMManager.generate_response

### Update (Phase 3+)
The `generate_response` method has been updated to accept a structured `LLMRequest` object instead of positional arguments. This change supports multi-provider fallback, preferred provider selection, and better configuration management.

### Method Signature

```python
async def generate_response(
    self, 
    request: LLMRequest | str, 
    user_prompt: Optional[str] = None, 
    **kwargs
) -> Optional[LLMResponse]
```

### Parameters

- **request** (`LLMRequest` | `str`): 
  - **Preferred**: An instance of `LLMRequest` containing all request details.
  - **Deprecated**: A string representing the system prompt (for backward compatibility).
- **user_prompt** (`Optional[str]`): 
  - Only used if `request` is a string. The user prompt text.
- **kwargs**:
  - `provider_name` (`str`): Only used in deprecated call style to specify preferred provider.

### Usage Examples

#### Correct Usage (Recommended)

```python
from kryten_llm.models.phase3 import LLMRequest

# Construct request object
request = LLMRequest(
    system_prompt="You are a helpful assistant.",
    user_prompt="Hello, how are you?",
    preferred_provider="openai",  # Optional
    temperature=0.8,              # Optional (default: 0.7)
    max_tokens=500                # Optional (default: 500)
)

# Generate response
response = await llm_manager.generate_response(request)
```

#### Deprecated Usage (Legacy)

> **Warning**: This calling convention logs a warning and will be removed in future versions.

```python
# Old style - DO NOT USE IN NEW CODE
response = await llm_manager.generate_response(
    "You are a helpful assistant.",
    "Hello, how are you?",
    provider_name="openai"
)
```

### Error Handling

The method returns `None` if all providers fail. It catches internal provider errors and attempts fallback according to the configured priority list.

```python
response = await llm_manager.generate_response(request)
if not response:
    logger.error("All LLM providers failed to generate a response.")
    return
    
print(f"Response: {response.content}")
```

## ResponseValidator.validate_response

### Update (Phase 4+)
The `validate_response` method has been added as an alias to `validate` to support backward compatibility and explicit naming. It also supports optional context for relevance checking.

### Method Signature

```python
def validate_response(
    self, 
    response: str, 
    user_message: str, 
    context: dict[str, Any] | None = None
) -> ValidationResult
```

### Parameters

- **response** (`str`): The text content to validate.
- **user_message** (`str`): The user's input message (used for relevance checking).
- **context** (`dict[str, Any] | None`): Context dictionary (e.g., video metadata) for enhanced relevance checking.

### Usage Example

```python
result = validator.validate_response(
    response="This is a generated response.",
    user_message="Tell me about this video",
    context={"current_video": {"title": "Cool Video"}}
)

if not result.valid:
    logger.warning(f"Validation failed: {result.reason}")
```

### Validation Checks
- **Length**: Checks against configured min/max length.
- **Repetition**: Checks against recent response history.
- **Inappropriate**: Checks against configured regex patterns.
- **Relevance**: (Optional) Checks keyword overlap with user message and context.
