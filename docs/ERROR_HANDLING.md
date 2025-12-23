# Error Handling and Recovery Guide

This guide details the error handling strategies and recovery procedures for the Kryten LLM service, with a focus on Phase 3 (Multi-provider) and Phase 4 (Validation) features.

## 1. LLM Generation Failures

### 1.1 Provider Failures
The service is designed to be resilient to individual provider failures (e.g., OpenAI API down, Ollama crash).

**Detection:**
- Connection errors (timeouts, connection refused).
- API errors (5xx status codes, rate limits).
- Invalid JSON responses from API.

**Recovery Strategy:**
1. **Fallback Chain:** The `LLMManager` attempts providers in the order specified in `config.yaml` (`provider_order`).
2. **Retry Logic:** Each provider implementation includes internal retries for transient network errors.
3. **Graceful Degradation:** If all providers fail, the service returns `None` and logs a critical error, but does not crash the application.

**Code Reference:**
- `kryten_llm/components/llm_manager.py`: `generate_response` method.

### 1.2 Model Loading Failures
Occurs when a local model (e.g., via Ollama) is not pulled or available.

**Recovery:**
- The system treats this as a provider failure and moves to the next provider in the chain.
- **Action Required:** Check Ollama logs and ensure models are pulled (`ollama pull llama3`).

## 2. Validation Failures

### 2.1 Content Validation
Responses are validated for quality before being sent to the user.

**Checks:**
- **Length:** Too short (< min_length) or too long (> max_length).
- **Repetition:** Identical or highly similar to recent responses.
- **Inappropriate Content:** Matches configured regex patterns.
- **Relevance:** Low keyword overlap with user input/context (optional).

**Handling:**
- **ValidationResult:** `ResponseValidator` returns a result object with `valid=False` and a `reason`.
- **Action:** The service logs the validation failure as a WARNING.
- **Retry (Future):** Currently, the response is discarded. Future improvements may include auto-regeneration with a different prompt.

**Code Reference:**
- `kryten_llm/components/validator.py`: `validate` method.
- `kryten_llm/service.py`: `_handle_media_change_trigger`.

## 3. Media Change Trigger Errors

### 3.1 Context Missing
Occurs when video metadata is unavailable during a media change event.

**Handling:**
- The system defaults to empty context.
- Validation checks that rely on context (relevance) will skip those specific checks or use fallback logic.

**Code Reference:**
- `kryten_llm/service.py`: `_handle_media_change_trigger`.

## 4. Operational Logging

All errors are logged with appropriate severity levels:
- **ERROR**: Critical failures (all providers failed, service crash).
- **WARNING**: Recoverable failures (provider failover, validation failure).
- **INFO**: Normal operation, successful generation.

**Log Location:**
- Standard output (console).
- Log files (if configured).

## 5. Troubleshooting Checklist

1. **Service won't start:**
   - Check `config.yaml` syntax.
   - Verify API keys are set in environment variables.

2. **Responses are empty:**
   - Check logs for "All LLM providers failed".
   - Verify network connectivity to APIs.

3. **High latency:**
   - Check if local models (Ollama) are running on CPU instead of GPU.
   - Verify internet connection speed for cloud providers.

4. **Validation failures:**
   - Adjust `min_length`/`max_length` in config.
   - Disable `check_repetition` if false positives occur.
