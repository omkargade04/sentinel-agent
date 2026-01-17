"""
Example usage of the LLM factory for code review.

This file demonstrates how to use the factory pattern to switch between
different LLM providers (Gemini for dev, Claude for prod).
"""
import asyncio
import os
from llm_factory import LLMFactory, LLMProvider, get_llm_client
from cost_tracker import CostTracker


async def example_gemini_usage():
    """Example: Using Gemini for development."""
    print("\n=== Gemini (Development) Example ===")
    
    # Method 1: Using factory with explicit provider
    client = LLMFactory.create_client(
        provider=LLMProvider.GEMINI,
        api_key=os.getenv("GEMINI_API_KEY"),
        model="gemini-1.5-flash",  # Fast and cheap
        temperature=0.0
    )
    
    # Create cost tracker
    cost_tracker = LLMFactory.create_cost_tracker(client)
    
    # Generate completion
    response = await client.generate_completion(
        prompt="Review this Python code: def add(a, b): return a + b",
        system_prompt="You are a code reviewer. Be concise."
    )
    
    # Track usage
    cost_tracker.record_usage(
        response["usage"]["input_tokens"],
        response["usage"]["output_tokens"]
    )
    
    print(f"Response: {response['content'][:200]}...")
    print(f"Cost stats: {cost_tracker.get_stats()}")


async def example_claude_usage():
    """Example: Using Claude for production."""
    print("\n=== Claude (Production) Example ===")
    
    # Method 2: Using convenience function
    client = get_llm_client(
        provider="claude",
        model="claude-3-5-sonnet-20241022"
    )
    
    cost_tracker = LLMFactory.create_cost_tracker(client)
    
    response = await client.generate_completion(
        prompt="Review this Python code: def add(a, b): return a + b",
        system_prompt="You are a code reviewer. Be concise."
    )
    
    cost_tracker.record_usage(
        response["usage"]["input_tokens"],
        response["usage"]["output_tokens"]
    )
    
    print(f"Response: {response['content'][:200]}...")
    print(f"Cost stats: {cost_tracker.get_stats()}")


async def example_env_based_usage():
    """Example: Using environment variables to decide provider."""
    print("\n=== Environment-Based Selection ===")
    
    # Set LLM_PROVIDER=gemini in your .env for dev
    # Set LLM_PROVIDER=claude in your .env for prod
    client = LLMFactory.create_from_env()
    
    cost_tracker = LLMFactory.create_cost_tracker(client)
    
    print(f"Using provider: {client.provider_name}")
    print(f"Using model: {client.model}")
    
    response = await client.generate_completion(
        prompt="What are common code review issues?",
        system_prompt="You are a helpful assistant."
    )
    
    cost_tracker.record_usage(
        response["usage"]["input_tokens"],
        response["usage"]["output_tokens"]
    )
    
    print(f"Response: {response['content'][:200]}...")
    print(f"Cost stats: {cost_tracker.get_stats()}")


async def main():
    """Run all examples."""
    # Example 1: Gemini for development (cheap and fast)
    await example_gemini_usage()
    
    # Example 2: Claude for production (high quality)
    # await example_claude_usage()  # Uncomment when ready
    
    # Example 3: Environment-based selection
    await example_env_based_usage()


if __name__ == "__main__":
    asyncio.run(main())
