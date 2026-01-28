"""Cost tracking for LLM API usage."""
import logging
from dataclasses import dataclass
from typing import Dict

logger = logging.getLogger(__name__)


# Pricing as of January 2024
LLM_PRICING = {
    "claude": {
        "claude-3-5-sonnet-20241022": {
            "input": 3.0 / 1_000_000,    # $3 per million input tokens
            "output": 15.0 / 1_000_000    # $15 per million output tokens
        },
        "claude-3-opus-20240229": {
            "input": 15.0 / 1_000_000,
            "output": 75.0 / 1_000_000
        }
    },
    "gemini": {
        "gemini-1.5-flash": {
            "input": 0.075 / 1_000_000,   # $0.075 per million input tokens
            "output": 0.30 / 1_000_000     # $0.30 per million output tokens
        },
        "gemini-1.5-pro": {
            "input": 1.25 / 1_000_000,
            "output": 5.0 / 1_000_000
        },
        "gemini-2.0-flash-exp": {
            "input": 0.0 / 1_000_000,      # Free during preview
            "output": 0.0 / 1_000_000
        }
    }
}


@dataclass
class CostTracker:
    """Track LLM API usage and costs across multiple providers."""
    
    provider: str = "claude"
    model: str = "claude-3-5-sonnet-20241022"
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_requests: int = 0
    
    def record_usage(self, input_tokens: int, output_tokens: int):
        """Record token usage."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_requests += 1
        
    def get_total_cost(self) -> float:
        """Calculate total cost in USD based on provider and model."""
        try:
            pricing = LLM_PRICING.get(self.provider, {}).get(self.model)
            if not pricing:
                logger.warning(
                    f"No pricing data for {self.provider}/{self.model}, "
                    f"using Claude Sonnet as fallback"
                )
                pricing = LLM_PRICING["claude"]["claude-3-5-sonnet-20241022"]
            
            input_cost = self.total_input_tokens * pricing["input"]
            output_cost = self.total_output_tokens * pricing["output"]
            return input_cost + output_cost
        except Exception as e:
            logger.error(f"Error calculating cost: {e}")
            return 0.0
    
    def get_stats(self) -> Dict:
        """Get usage statistics."""
        return {
            "provider": self.provider,
            "model": self.model,
            "total_requests": self.total_requests,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": round(self.get_total_cost(), 4)
        }