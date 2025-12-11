"""LLM API manager for generating responses."""

import asyncio
import logging
from typing import Optional

import aiohttp

from kryten_llm.models.config import LLMConfig


logger = logging.getLogger(__name__)


class LLMManager:
    """Manages LLM API interactions.
    
    Implements REQ-007 through REQ-010 from Phase 1 specification:
    - Support OpenAI-compatible API endpoints
    - Use default_provider from configuration
    - Apply provider timeout settings
    - Handle API errors gracefully
    
    Phase 1: Single provider support
    Phase 3: Multi-provider with fallback chain
    """

    def __init__(self, config: LLMConfig):
        """Initialize with configuration.
        
        Args:
            config: LLM configuration containing provider settings
        """
        self.config = config
        self.default_provider = config.llm_providers[config.default_provider]
        logger.info(
            f"LLMManager initialized with default provider: {config.default_provider} "
            f"(model: {self.default_provider.model})"
        )

    async def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        provider_name: Optional[str] = None
    ) -> Optional[str]:
        """Generate LLM response.
        
        Makes API call to configured LLM provider using OpenAI-compatible format.
        
        Args:
            system_prompt: System/personality prompt
            user_prompt: User message prompt
            provider_name: Provider to use (None = default)
            
        Returns:
            Generated response text or None on error
        """
        # REQ-008: Use default provider if not specified
        if provider_name is None:
            provider = self.default_provider
            provider_name = self.config.default_provider
        else:
            provider = self.config.llm_providers.get(provider_name)
            if not provider:
                logger.error(f"Provider '{provider_name}' not found in configuration")
                return None
        
        # Build API request
        url = f"{provider.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": provider.max_tokens,
            "temperature": provider.temperature
        }
        
        logger.debug(
            f"Calling LLM API: provider={provider_name}, model={provider.model}, "
            f"max_tokens={provider.max_tokens}, temperature={provider.temperature}"
        )
        
        try:
            # REQ-009: Apply provider timeout
            timeout = aiohttp.ClientTimeout(total=provider.timeout_seconds)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        # REQ-022: Log with full context
                        logger.error(
                            f"LLM API error: provider={provider_name}, "
                            f"model={provider.model}, status={response.status}, "
                            f"error={error_text[:200]}"
                        )
                        return None
                    
                    data = await response.json()
                    
                    # Extract response content
                    if "choices" not in data or len(data["choices"]) == 0:
                        logger.error(
                            f"Invalid API response format: no choices returned "
                            f"(provider={provider_name})"
                        )
                        return None
                    
                    content = data["choices"][0]["message"]["content"]
                    
                    logger.info(
                        f"LLM response generated: provider={provider_name}, "
                        f"length={len(content)} chars"
                    )
                    
                    return content
        
        except aiohttp.ClientError as e:
            # REQ-010, REQ-023: Handle errors gracefully
            logger.error(
                f"LLM API network error: provider={provider_name}, "
                f"model={provider.model}, error={str(e)}"
            )
            return None
        
        except asyncio.TimeoutError:
            # REQ-023: Handle timeout specifically
            logger.error(
                f"LLM API timeout: provider={provider_name}, "
                f"model={provider.model}, timeout={provider.timeout_seconds}s"
            )
            return None
        
        except Exception as e:
            # Catch-all for unexpected errors
            logger.error(
                f"LLM API unexpected error: provider={provider_name}, "
                f"model={provider.model}, error={type(e).__name__}: {str(e)}",
                exc_info=True
            )
            return None
