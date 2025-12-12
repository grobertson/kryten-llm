"""Enhanced LLM API manager with multi-provider support and fallback.

Phase 3: Implements REQ-001 through REQ-007 and REQ-025 through REQ-032 for
resilient multi-provider LLM interactions with automatic fallback.
"""

import asyncio
import logging
import os
import time
from typing import Dict, List, Optional

import aiohttp

from kryten_llm.models.config import LLMConfig, LLMProvider
from kryten_llm.models.phase3 import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)


class LLMManager:
    """Enhanced LLM manager with multi-provider support.

    Phase 3 enhancements:
    - Support multiple provider configurations (REQ-001)
    - Attempt providers in priority order with fallback (REQ-002)
    - Implement exponential backoff for retries (REQ-003)
    - Support provider selection by trigger (REQ-004)
    - Handle provider-specific errors gracefully (REQ-005)
    - Log provider selection and fallback decisions (REQ-006)
    - Support different provider types (REQ-007)
    """

    def __init__(self, config: LLMConfig):
        """Initialize with provider configurations.

        Args:
            config: LLM configuration containing provider settings
        """
        self.config = config
        self.providers: Dict[str, LLMProvider] = {}
        self._load_providers()

        logger.info(
            f"LLMManager initialized with {len(self.providers)} providers: "
            f"{list(self.providers.keys())}"
        )

    def _load_providers(self) -> None:
        """Load and validate provider configurations.

        REQ-001: Support multiple provider configurations.
        SEC-001: Resolve environment variable references in API keys.
        """
        for provider_name, provider_config in self.config.llm_providers.items():
            # SEC-001: Resolve API key environment variables
            api_key = self._resolve_api_key(provider_config.api_key)

            # Store resolved provider
            provider_config.api_key = api_key
            self.providers[provider_name] = provider_config

            logger.debug(
                f"Loaded provider: {provider_name} "
                f"(type={provider_config.type}, model={provider_config.model}, "
                f"priority={provider_config.priority})"
            )

    def _resolve_api_key(self, api_key: str) -> str:
        """Resolve environment variable references in API key.

        SEC-001: Support ${ENV_VAR} syntax for secure key storage.

        Args:
            api_key: API key string (may contain ${ENV_VAR})

        Returns:
            Resolved API key value
        """
        if api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            resolved = os.getenv(env_var, "")
            if not resolved:
                logger.warning(f"Environment variable {env_var} not set, using empty string")
            return resolved
        return api_key

    def _get_provider_priority(self, preferred_provider: Optional[str]) -> List[str]:
        """Get ordered list of providers to try.

        REQ-002: Attempt providers in priority order.
        REQ-004: Support preferred provider for triggers.

        Args:
            preferred_provider: Preferred provider name (from trigger)

        Returns:
            Ordered list of provider names to attempt
        """
        # REQ-004: If preferred provider specified and exists, try it first
        if preferred_provider and preferred_provider in self.providers:
            # Preferred first, then others by priority
            others = [
                name
                for name, p in sorted(self.providers.items(), key=lambda x: x[1].priority)
                if name != preferred_provider
            ]
            return [preferred_provider] + others

        # REQ-002: Use configured priority order or sort by priority
        if self.config.default_provider_priority:
            # Use configured order, filter to existing providers
            priority_order = [
                name for name in self.config.default_provider_priority if name in self.providers
            ]
            # Add any providers not in configured order
            remaining = [name for name in self.providers if name not in priority_order]
            return priority_order + sorted(remaining, key=lambda x: self.providers[x].priority)
        else:
            # Sort all providers by priority field
            return [name for name, _ in sorted(self.providers.items(), key=lambda x: x[1].priority)]

    async def generate_response(self, request: LLMRequest) -> Optional[LLMResponse]:
        """Generate response with automatic provider fallback.

        REQ-002: Attempt providers in priority order until success.
        REQ-006: Log provider selection and fallback decisions.
        REQ-032: Graceful degradation when all providers fail.

        Args:
            request: LLM request with prompts and optional preferred provider

        Returns:
            LLM response or None if all providers failed
        """
        provider_order = self._get_provider_priority(request.preferred_provider)
        errors = []

        # REQ-006: Log provider selection
        logger.info(f"Attempting {len(provider_order)} providers in order: {provider_order}")

        for provider_name in provider_order:
            if provider_name not in self.providers:
                logger.warning(f"Provider {provider_name} not found, skipping")
                continue

            provider = self.providers[provider_name]

            try:
                # REQ-003: Try provider with retries and exponential backoff
                response = await self._try_provider(provider, provider_name, request)

                # REQ-006: Log successful provider
                logger.info(
                    f"LLM response generated using provider: {provider_name} "
                    f"(model={response.model_used}, time={response.response_time:.2f}s, "
                    f"tokens={response.tokens_used})"
                )

                return response

            except Exception as e:
                # REQ-031: Log provider failure with context
                error_msg = f"Provider {provider_name} failed: {type(e).__name__}: {str(e)}"
                logger.warning(error_msg)
                errors.append(error_msg)

                # Continue to next provider (fallback)
                continue

        # REQ-032: All providers failed - log comprehensive error
        logger.error(
            f"All {len(provider_order)} LLM providers failed. " f"Errors: {'; '.join(errors)}"
        )
        return None

    async def _try_provider(
        self, provider: LLMProvider, provider_name: str, request: LLMRequest
    ) -> LLMResponse:
        """Attempt to get response from a single provider with retries.

        REQ-003: Implement exponential backoff for retries.
        REQ-005: Handle provider-specific errors gracefully.

        Args:
            provider: Provider configuration
            provider_name: Provider identifier
            request: LLM request

        Returns:
            LLM response

        Raises:
            Exception: If all retry attempts fail
        """
        retry_delay = self.config.retry_strategy.initial_delay
        last_exception = None

        for attempt in range(provider.max_retries + 1):  # +1 for initial attempt
            try:
                # Attempt the request
                response = await self._call_provider(provider, provider_name, request)

                # Success
                if attempt > 0:
                    logger.info(f"Provider {provider_name} succeeded on attempt {attempt + 1}")
                return response

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                # REQ-005: Handle transient errors with retry
                last_exception = e

                if attempt < provider.max_retries:
                    # REQ-003: Exponential backoff
                    logger.debug(
                        f"Provider {provider_name} attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {retry_delay:.1f}s..."
                    )

                    await asyncio.sleep(retry_delay)

                    # Calculate next delay with exponential backoff
                    retry_delay = min(
                        retry_delay * self.config.retry_strategy.multiplier,
                        self.config.retry_strategy.max_delay,
                    )
                else:
                    # Max retries exceeded
                    logger.warning(f"Provider {provider_name} failed after {attempt + 1} attempts")
                    raise

            except Exception as e:
                # REQ-005: Non-retryable errors (auth, invalid config, etc.)
                logger.error(
                    f"Provider {provider_name} non-retryable error: "
                    f"{type(e).__name__}: {str(e)}"
                )
                raise

        # Should not reach here, but handle edge case
        if last_exception:
            raise last_exception
        raise RuntimeError(f"Provider {provider_name} failed with unknown error")

    async def _call_provider(
        self, provider: LLMProvider, provider_name: str, request: LLMRequest
    ) -> LLMResponse:
        """Call LLM provider API.

        REQ-007: Support different provider types.

        Args:
            provider: Provider configuration
            provider_name: Provider identifier
            request: LLM request

        Returns:
            LLM response

        Raises:
            Exception: On API errors
        """
        start_time = time.time()

        # REQ-007: Route to provider-specific implementation
        if provider.type in ("openai", "openai_compatible", "openrouter"):
            response = await self._call_openai_provider(provider, provider_name, request)
        else:
            raise ValueError(f"Unsupported provider type: {provider.type}")

        response_time = time.time() - start_time
        response.response_time = response_time

        return response

    async def _call_openai_provider(
        self, provider: LLMProvider, provider_name: str, request: LLMRequest
    ) -> LLMResponse:
        """Call OpenAI-compatible provider API.

        REQ-007: Support OpenAI-compatible providers.
        REQ-024: Support provider-specific headers.
        SEC-001: Never log API keys.

        Args:
            provider: Provider configuration
            provider_name: Provider identifier
            request: LLM request

        Returns:
            LLM response

        Raises:
            aiohttp.ClientError: On HTTP errors
            asyncio.TimeoutError: On timeout
        """
        # Build request
        url = f"{provider.base_url.rstrip('/')}/chat/completions"

        # REQ-024: Support custom headers
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }
        if provider.custom_headers:
            headers.update(provider.custom_headers)

        payload = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        # SEC-001: Log without exposing API key
        logger.debug(
            f"Calling {provider_name}: model={provider.model}, "
            f"temp={request.temperature}, max_tokens={request.max_tokens}"
        )

        # Make API call
        timeout = aiohttp.ClientTimeout(total=provider.timeout_seconds)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as response:
                # REQ-005: Handle HTTP errors
                if response.status != 200:
                    error_text = await response.text()
                    # SEC-001: Don't log full error (may contain keys)
                    raise aiohttp.ClientError(f"HTTP {response.status}: {error_text[:200]}")

                data = await response.json()

                # Validate response format
                if "choices" not in data or len(data["choices"]) == 0:
                    raise ValueError("Invalid API response: no choices returned")

                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens")

                return LLMResponse(
                    content=content,
                    provider_used=provider_name,
                    model_used=provider.model,
                    tokens_used=tokens,
                )
