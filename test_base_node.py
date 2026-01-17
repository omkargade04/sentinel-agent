"""
Test implementation to verify base node infrastructure.
"""

import asyncio
from typing import Dict, List, Any, Type

# Import our base infrastructure
from src.services.pr_review.review_generation.base_node import BaseReviewGenerationNode
from src.services.pr_review.review_generation.schema import ReviewGenerationState

class TestNode(BaseReviewGenerationNode):
    """Simple test node to verify base infrastructure."""

    def __init__(self):
        super().__init__(
            name="test_node",
            timeout_seconds=5.0,
            max_retries=2
        )

    async def _execute_node_logic(self, state: ReviewGenerationState) -> Dict[str, Any]:
        """Test implementation that processes input state."""
        # Simulate some work
        await asyncio.sleep(0.1)

        return {
            "processed": True,
            "input_keys": list(state.keys()),
            "message": "Test node executed successfully"
        }

    def _get_required_state_keys(self) -> List[str]:
        """Test node requires test_input key."""
        return ["test_input"]

    def _get_state_type_requirements(self) -> Dict[str, Type]:
        """Test node expects test_input to be a string."""
        return {"test_input": str}

async def test_base_node():
    """Test the base node infrastructure."""
    print("🧪 Testing Base Node Infrastructure...")

    # Create test node
    node = TestNode()

    # Test valid execution
    test_state = {
        "test_input": "hello world",
        "optional_data": {"key": "value"}
    }

    result = await node.execute(test_state)

    print(f"✅ Execution successful: {result.success}")
    print(f"✅ Node name: {result.node_name}")
    print(f"✅ Execution time: {result.metrics.execution_time_seconds:.3f}s")
    print(f"✅ Result data: {result.data}")
    print(f"✅ Modified keys: {result.modified_state_keys}")

    # Test health status
    health = node.get_health_status()
    print(f"✅ Node healthy: {health['healthy']}")
    print(f"✅ Success rate: {health['success_rate']:.2f}")

    print("🎉 Base Node Infrastructure Test PASSED!")

if __name__ == "__main__":
    asyncio.run(test_base_node())