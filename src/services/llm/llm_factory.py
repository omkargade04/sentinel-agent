"""Factory for creating LLM clients based on configuration."""
import logging
import os
from enum import Enum
from typing import Optional

from .base_client import BaseLLMClient
from .claude_client import ClaudeClient
from .gemini_client import GeminiClient
from .cost_tracker import CostTracker

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    """Supported LLM providers."""
    CLAUDE = "claude"
    GEMINI = "gemini"


class LLMFactory:
    """
    Factory for creating LLM clients.
    
    Usage:
        # For development (using Gemini)
        client = LLMFactory.create_client(
            provider=LLMProvider.GEMINI,
            api_key=os.getenv("GEMINI_API_KEY")
        )
        
        # For production (using Claude)
        client = LLMFactory.create_client(
            provider=LLMProvider.CLAUDE,
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )
        
        # Using environment variable to decide
        client = LLMFactory.create_from_env()
    """
    
    # Default models for each provider
    DEFAULT_MODELS = {
        LLMProvider.CLAUDE: "claude-3-5-sonnet-20241022",
        LLMProvider.GEMINI: "gemini-3-flash-preview",  # Use gemini-3-flash-preview (stable) instead of gemini-1.5-flash for v1beta compatibility
    }
    
    @classmethod
    def create_client(
        cls,
        provider: LLMProvider,
        api_key: str,
        model: Optional[str] = None,
        max_tokens: int = 8000,
        temperature: float = 0.0,
        timeout: int = 60
    ) -> BaseLLMClient:
        """
        Create an LLM client for the specified provider.
        
        Args:
            provider: LLM provider (CLAUDE or GEMINI)
            api_key: API key for the provider
            model: Optional model name (uses default if not specified)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0 = deterministic)
            timeout: Request timeout in seconds
            
        Returns:
            BaseLLMClient instance
            
        Raises:
            ValueError: If provider is not supported or API key is missing
        """
        if not api_key or api_key == "1234567890":
            raise ValueError(f"Valid API key required for {provider}")
        
        # Use default model if not specified
        if not model:
            model = cls.DEFAULT_MODELS[provider]
        
        logger.info(
            f"Creating LLM client: provider={provider}, model={model}, "
            f"max_tokens={max_tokens}, temperature={temperature}"
        )
        
        if provider == LLMProvider.CLAUDE:
            return ClaudeClient(
                api_key=api_key,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout
            )
        elif provider == LLMProvider.GEMINI:
            return GeminiClient(
                api_key=api_key,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout
            )
        else:
            raise ValueError(f"Unsupported provider: {provider}")
    
    @classmethod
    def create_from_env(
        cls,
        max_tokens: int = 8000,
        temperature: float = 0.0,
        timeout: int = 60
    ) -> BaseLLMClient:
        """
        Create LLM client based on environment variables.
        
        Environment variables:
            LLM_PROVIDER: "claude" or "gemini" (default: "gemini")
            LLM_MODEL: Model name (optional, uses provider default)
            ANTHROPIC_API_KEY: Required if using Claude
            GEMINI_API_KEY: Required if using Gemini
            
        Returns:
            BaseLLMClient instance
        """
        # Get provider from environment (default to Gemini for dev)
        provider_name = os.getenv("LLM_PROVIDER", "gemini").lower()
        
        try:
            provider = LLMProvider(provider_name)
        except ValueError:
            logger.warning(
                f"Invalid LLM_PROVIDER '{provider_name}', defaulting to gemini"
            )
            provider = LLMProvider.GEMINI
        
        # Get model from environment (optional)
        model = os.getenv("LLM_MODEL", None)
        
        # Get API key based on provider
        if provider == LLMProvider.CLAUDE:
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
        else:
            # TODO: Remove hardcoded key before committing - LOCAL DEV ONLY
            api_key = os.getenv("GEMINI_API_KEY", "")
        
        return cls.create_client(
            provider=provider,
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout
        )
    
    @classmethod
    def create_cost_tracker(
        cls,
        client: BaseLLMClient
    ) -> CostTracker:
        """
        Create a cost tracker for the given client.
        
        Args:
            client: LLM client instance
            
        Returns:
            CostTracker configured for the client's provider and model
        """
        return CostTracker(
            provider=client.provider_name,
            model=client.model
        )


# Convenience function for quick client creation
def get_llm_client(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
) -> BaseLLMClient:
    """
    Convenience function to get an LLM client.
    
    Args:
        provider: "claude" or "gemini" (defaults to LLM_PROVIDER env var)
        model: Model name (optional)
        **kwargs: Additional arguments passed to create_client
        
    Returns:
        BaseLLMClient instance
        
    Example:
        # Use environment variables
        client = get_llm_client()
        
        # Specify provider
        client = get_llm_client(provider="gemini")
        
        # Specify both provider and model
        client = get_llm_client(provider="gemini", model="gemini-1.5-pro")
    """
    if provider:
        provider_enum = LLMProvider(provider.lower())
        
        # Get API key
        if provider_enum == LLMProvider.CLAUDE:
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
        else:
            # TODO: Remove hardcoded key before committing - LOCAL DEV ONLY
            api_key = os.getenv("GEMINI_API_KEY", "")
        
        return LLMFactory.create_client(
            provider=provider_enum,
            api_key=api_key,
            model=model,
            **kwargs
        )
    else:
        return LLMFactory.create_from_env(**kwargs)
