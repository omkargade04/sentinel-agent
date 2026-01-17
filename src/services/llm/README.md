# LLM Service - Multi-Provider Support

Factory pattern for switching between different LLM providers (Gemini for dev, Claude for prod).

## Quick Start

### 1. Install Dependencies

```bash
poetry add google-generativeai
```

### 2. Set Environment Variables

```bash
# For development (using Gemini - cheaper)
export LLM_PROVIDER=gemini
export GEMINI_API_KEY=your-gemini-api-key

# For production (using Claude - higher quality)
# export LLM_PROVIDER=claude
# export ANTHROPIC_API_KEY=your-anthropic-api-key
```

### 3. Basic Usage

```python
from src.services.llm import get_llm_client, LLMFactory

# Simple usage - uses environment variables
client = get_llm_client()

# Generate completion
response = await client.generate_completion(
    prompt="Review this code: def add(a, b): return a + b",
    system_prompt="You are a code reviewer."
)

print(response["content"])
print(f"Tokens: {response['usage']}")
```

## Architecture

```
src/services/llm/
├── base_client.py       # Abstract base class (interface)
├── claude_client.py     # Anthropic Claude implementation
├── gemini_client.py     # Google Gemini implementation
├── llm_factory.py       # Factory for creating clients
├── cost_tracker.py      # Multi-provider cost tracking
└── example_usage.py     # Usage examples
```

## Provider Comparison

| Provider | Model | Speed | Cost (per 1M tokens) | Use Case |
|----------|-------|-------|---------------------|----------|
| **Gemini** | gemini-1.5-flash | Fast | $0.075 in / $0.30 out | Development, testing |
| **Gemini** | gemini-2.0-flash-exp | Fast | Free (preview) | Experimentation |
| **Gemini** | gemini-1.5-pro | Medium | $1.25 in / $5.00 out | High-quality dev |
| **Claude** | claude-3-5-sonnet | Medium | $3.00 in / $15.00 out | Production |
| **Claude** | claude-3-opus | Slow | $15.00 in / $75.00 out | Critical production |

## Usage Examples

### Development (Gemini)

```python
from src.services.llm import LLMFactory, LLMProvider

client = LLMFactory.create_client(
    provider=LLMProvider.GEMINI,
    api_key=os.getenv("GEMINI_API_KEY"),
    model="gemini-1.5-flash"
)

response = await client.generate_completion(
    prompt="Your code review prompt"
)
```

### Production (Claude)

```python
from src.services.llm import LLMFactory, LLMProvider

client = LLMFactory.create_client(
    provider=LLMProvider.CLAUDE,
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    model="claude-3-5-sonnet-20241022"
)

response = await client.generate_completion(
    prompt="Your code review prompt"
)
```

### Environment-Based Selection

```python
# Set LLM_PROVIDER=gemini in .env for dev
# Set LLM_PROVIDER=claude in .env for prod

from src.services.llm import get_llm_client

client = get_llm_client()  # Automatically picks based on LLM_PROVIDER
response = await client.generate_completion(prompt="...")
```

## Cost Tracking

```python
from src.services.llm import LLMFactory, get_llm_client

client = get_llm_client()
cost_tracker = LLMFactory.create_cost_tracker(client)

response = await client.generate_completion(prompt="...")

cost_tracker.record_usage(
    response["usage"]["input_tokens"],
    response["usage"]["output_tokens"]
)

print(cost_tracker.get_stats())
# Output: {
#   "provider": "gemini",
#   "model": "gemini-1.5-flash",
#   "total_requests": 1,
#   "total_input_tokens": 150,
#   "total_output_tokens": 500,
#   "total_cost_usd": 0.0002
# }
```

## Switching Between Providers

### Method 1: Environment Variable (Recommended)

```bash
# .env file
LLM_PROVIDER=gemini  # Change to "claude" for production
```

### Method 2: Programmatic

```python
# Development
dev_client = get_llm_client(provider="gemini")

# Production
prod_client = get_llm_client(provider="claude")
```

### Method 3: Configuration-Based

```python
from src.core.config import settings

# Use settings.LLM_PROVIDER to decide
if settings.env == "production":
    client = get_llm_client(provider="claude")
else:
    client = get_llm_client(provider="gemini")
```

## Response Format

All clients return a standardized response:

```python
{
    "content": str,           # Generated text
    "usage": {
        "input_tokens": int,  # Tokens in prompt
        "output_tokens": int  # Tokens in response
    },
    "model": str,             # Model name used
    "stop_reason": str        # Why generation stopped
}
```

## Error Handling

```python
try:
    response = await client.generate_completion(prompt="...")
except Exception as e:
    logger.error(f"LLM error: {e}")
    # Fallback logic here
```

## Best Practices

1. **Use Gemini for development** - It's 40x cheaper than Claude Sonnet
2. **Use Claude for production** - Higher quality reviews
3. **Track costs** - Always use CostTracker to monitor spending
4. **Set timeouts** - Prevent hanging requests
5. **Use environment variables** - Easy switching between dev/prod

## Testing

Run the example:

```bash
poetry run python src/services/llm/example_usage.py
```

## API Key Setup

### Gemini (Google AI Studio)
1. Go to https://aistudio.google.com/app/apikey
2. Create a new API key
3. Set `GEMINI_API_KEY=your-key` in `.env`

### Claude (Anthropic)
1. Go to https://console.anthropic.com/
2. Create an API key
3. Set `ANTHROPIC_API_KEY=your-key` in `.env`
