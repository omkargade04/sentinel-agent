"""Anthropic Claude API client for PR review."""
import logging
from typing import Optional, Dict, Any
from anthropic import Anthropic, AsyncAnthropic

from .base_client import BaseLLMClient

logger = logging.getLogger(__name__)


class ClaudeClient(BaseLLMClient):
    """Wrapper for Anthropic Claude API with cost tracking and error handling."""
    
    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = 8000,
        temperature: float = 0.0,
        timeout: int = 60
    ):
        super().__init__(api_key, model, max_tokens, temperature, timeout)
        self.client = AsyncAnthropic(api_key=api_key, timeout=timeout)
    
    @property
    def provider_name(self) -> str:
        """Return provider name."""
        return "claude"
        
    async def generate_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate completion with Claude."""
        try:
            messages = [{"role": "user", "content": prompt}]
            
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                temperature=kwargs.get("temperature", self.temperature),
                system=system_prompt if system_prompt else "",
                messages=messages
            )
            
            return {
                "content": response.content[0].text,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                "model": response.model,
                "stop_reason": response.stop_reason
            }
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            raise