"""Google Gemini API client for PR review."""
import logging
from typing import Optional, Dict, Any
import google.generativeai as genai
from google.generativeai.types import GenerationConfig

from .base_client import BaseLLMClient

logger = logging.getLogger(__name__)


class GeminiClient(BaseLLMClient):
    """Wrapper for Google Gemini API with cost tracking and error handling."""
    
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-1.5-flash",
        max_tokens: int = 8000,
        temperature: float = 0.0,
        timeout: int = 60
    ):
        super().__init__(api_key, model, max_tokens, temperature, timeout)
        
        # Configure Gemini
        genai.configure(api_key=api_key)
        
        # Initialize model
        self.client = genai.GenerativeModel(
            model_name=self.model,
            generation_config=GenerationConfig(
                max_output_tokens=self.max_tokens,
                temperature=self.temperature,
            )
        )
        
    @property
    def provider_name(self) -> str:
        """Return provider name."""
        return "gemini"
        
    async def generate_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate completion with Gemini.
        
        Note: Gemini API is primarily synchronous, but we wrap it in async
        for interface compatibility. For production, consider using aiohttp
        to call the REST API directly.
        """
        try:
            # Combine system prompt with user prompt if provided
            full_prompt = prompt
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{prompt}"
            
            # Override generation config if provided
            generation_config = GenerationConfig(
                max_output_tokens=kwargs.get("max_tokens", self.max_tokens),
                temperature=kwargs.get("temperature", self.temperature),
            )
            
            # Generate response (synchronous call)
            response = self.client.generate_content(
                full_prompt,
                generation_config=generation_config
            )
            
            # Extract token usage
            usage_metadata = response.usage_metadata
            input_tokens = usage_metadata.prompt_token_count if usage_metadata else 0
            output_tokens = usage_metadata.candidates_token_count if usage_metadata else 0
            
            # Determine stop reason
            stop_reason = "stop"
            if response.candidates and len(response.candidates) > 0:
                finish_reason = response.candidates[0].finish_reason
                if finish_reason:
                    stop_reason = str(finish_reason).lower()
            
            return {
                "content": response.text,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
                "model": self.model,
                "stop_reason": stop_reason
            }
            
        except Exception as e:
            logger.error(f"Gemini API error: {e}", exc_info=True)
            raise
