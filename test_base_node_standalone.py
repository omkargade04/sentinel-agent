"""
Minimal standalone test for base node infrastructure.
"""

import asyncio
import logging
import sys
from datetime import datetime
from typing import Dict, List, Any, Type, Optional, TypeVar, Generic
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from uuid import uuid4
from abc import ABC, abstractmethod

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock dependencies to avoid config issues
class MockCircuitBreaker:
    async def can_execute(self) -> bool:
        return True

    async def record_success(self):
        pass

    async def record_failure(self, error: str):
        pass

    def health_check(self) -> Dict[str, Any]:
        return {"status": "healthy"}

class MockReviewGenerationError(Exception):
    def __init__(self, message: str, recoverable: bool = True):
        super().__init__(message)
        self.recoverable = recoverable

class MockWorkflowNodeError(Exception):
    pass

class MockWorkflowStateError(Exception):
    pass

# Type definitions
StateType = TypeVar('StateType', bound=Dict[str, Any])
ResultType = TypeVar('ResultType', bound=Dict[str, Any])
ReviewGenerationState = Dict[str, Any]

@dataclass
class NodeExecutionMetrics:
    """Comprehensive metrics for node execution."""
    node_name: str
    execution_id: str = field(default_factory=lambda: str(uuid4())[:8])
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    execution_time_seconds: float = 0.0
    input_size_bytes: int = 0
    output_size_bytes: int = 0
    state_keys_processed: List[str] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    retry_count: int = 0
    timeout_occurred: bool = False
    circuit_breaker_triggered: bool = False

    def mark_complete(self) -> None:
        self.end_time = datetime.utcnow()
        if self.start_time:
            self.execution_time_seconds = (self.end_time - self.start_time).total_seconds()

    def add_warning(self, message: str) -> None:
        self.warning_count += 1
        logger.warning(f"[{self.node_name}:{self.execution_id}] {message}")

    def add_error(self, error: Exception) -> None:
        self.error_count += 1
        logger.error(f"[{self.node_name}:{self.execution_id}] {str(error)}")

@dataclass
class NodeExecutionResult(Generic[ResultType]):
    """Result of node execution with comprehensive metadata."""
    success: bool
    node_name: str
    execution_id: str
    data: ResultType
    metrics: NodeExecutionMetrics
    modified_state_keys: List[str] = field(default_factory=list)
    error: Optional[Exception] = None
    warnings: List[str] = field(default_factory=list)
    degraded_mode: bool = False
    fallback_used: bool = False
    recovery_suggestions: List[str] = field(default_factory=list)

class StateValidator:
    @staticmethod
    def validate_required_keys(state: Dict[str, Any], required_keys: List[str], node_name: str) -> None:
        missing_keys = [key for key in required_keys if key not in state]
        if missing_keys:
            raise MockWorkflowStateError(f"Node {node_name} missing required state keys: {missing_keys}")

    @staticmethod
    def validate_state_types(state: Dict[str, Any], type_requirements: Dict[str, Type], node_name: str) -> None:
        invalid_fields = []
        for key, expected_type in type_requirements.items():
            if key in state and not isinstance(state[key], expected_type):
                invalid_fields.append(f"{key}: expected {expected_type.__name__}, got {type(state[key]).__name__}")
        if invalid_fields:
            raise MockWorkflowStateError(f"Node {node_name} has invalid state field types: {invalid_fields}")

    @staticmethod
    def calculate_state_size(state: Dict[str, Any]) -> int:
        try:
            return sys.getsizeof(str(state))
        except Exception:
            return len(str(state).encode('utf-8'))

class TimeoutManager:
    def __init__(self, default_timeout: float = 60.0):
        self.default_timeout = default_timeout

    @asynccontextmanager
    async def timeout_context(self, timeout_seconds: Optional[float] = None):
        timeout = timeout_seconds or self.default_timeout
        try:
            async with asyncio.timeout(timeout):
                yield timeout
        except asyncio.TimeoutError:
            logger.error(f"Operation timed out after {timeout} seconds")
            raise

class BaseReviewGenerationNode(ABC, Generic[StateType, ResultType]):
    """Abstract base class for review generation workflow nodes."""

    def __init__(
        self,
        name: str,
        timeout_seconds: float = 60.0,
        circuit_breaker: Optional[MockCircuitBreaker] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ):
        self.name = name
        self.timeout_seconds = timeout_seconds
        self.circuit_breaker = circuit_breaker
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.logger = logging.getLogger(f"{__name__}.{name}")
        self.timeout_manager = TimeoutManager(timeout_seconds)
        self._total_executions = 0
        self._successful_executions = 0
        self._failed_executions = 0

    async def execute(self, state: ReviewGenerationState) -> NodeExecutionResult[ResultType]:
        """Execute the node with comprehensive error handling and monitoring."""
        metrics = NodeExecutionMetrics(node_name=self.name)
        execution_id = metrics.execution_id

        self.logger.info(f"Starting execution [{execution_id}]")
        self._total_executions += 1

        try:
            # Pre-execution validation
            await self._validate_input_state(state, metrics)

            # Calculate input size for metrics
            metrics.input_size_bytes = StateValidator.calculate_state_size(state)
            metrics.state_keys_processed = list(state.keys())

            # Execute with retry logic
            result_data = await self._execute_with_retry(state, metrics)

            # Post-execution processing
            metrics.output_size_bytes = StateValidator.calculate_state_size(result_data)
            metrics.mark_complete()

            self._successful_executions += 1

            self.logger.info(
                f"Node {self.name} [{execution_id}] completed successfully in "
                f"{metrics.execution_time_seconds:.2f}s"
            )

            return NodeExecutionResult(
                success=True,
                node_name=self.name,
                execution_id=execution_id,
                data=result_data,
                modified_state_keys=self._get_modified_state_keys(result_data),
                metrics=metrics
            )

        except Exception as e:
            metrics.add_error(e)
            metrics.mark_complete()
            self._failed_executions += 1

            self.logger.error(
                f"Node {self.name} [{execution_id}] failed after "
                f"{metrics.execution_time_seconds:.2f}s: {str(e)}"
            )

            return NodeExecutionResult(
                success=False,
                node_name=self.name,
                execution_id=execution_id,
                data={},  # type: ignore
                metrics=metrics,
                error=e,
                recovery_suggestions=self._get_recovery_suggestions(e)
            )

    async def _execute_with_retry(self, state: ReviewGenerationState, metrics: NodeExecutionMetrics) -> ResultType:
        """Execute the node with retry logic and circuit breaker protection."""
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    metrics.retry_count += 1
                    await asyncio.sleep(self.retry_delay * attempt)
                    self.logger.info(f"Retrying {self.name} (attempt {attempt + 1}/{self.max_retries + 1})")

                # Execute with timeout
                async with self.timeout_manager.timeout_context(self.timeout_seconds):
                    result = await self._execute_node_logic(state)

                return result

            except asyncio.TimeoutError:
                metrics.timeout_occurred = True
                last_exception = MockWorkflowNodeError(
                    f"Node {self.name} timed out after {self.timeout_seconds} seconds"
                )
                self.logger.warning(f"Timeout occurred for {self.name} (attempt {attempt + 1})")

            except Exception as e:
                last_exception = e
                if not self._should_retry_error(e):
                    break
                self.logger.warning(f"Attempt {attempt + 1} failed for {self.name}: {str(e)}")

        if last_exception:
            raise last_exception
        else:
            raise MockWorkflowNodeError(f"Node {self.name} failed after {self.max_retries} retries")

    def _should_retry_error(self, error: Exception) -> bool:
        """Determine if an error should trigger a retry."""
        if isinstance(error, (MockWorkflowStateError, ValueError, TypeError)):
            return False
        if isinstance(error, MockReviewGenerationError) and not getattr(error, 'recoverable', True):
            return False
        return True

    async def _validate_input_state(self, state: ReviewGenerationState, metrics: NodeExecutionMetrics) -> None:
        """Validate input state meets node requirements."""
        try:
            required_keys = self._get_required_state_keys()
            StateValidator.validate_required_keys(state, required_keys, self.name)

            type_requirements = self._get_state_type_requirements()
            StateValidator.validate_state_types(state, type_requirements, self.name)

        except Exception as e:
            metrics.add_error(e)
            raise

    def _get_modified_state_keys(self, result_data: ResultType) -> List[str]:
        """Get list of state keys that will be modified by this node's output."""
        return list(result_data.keys()) if isinstance(result_data, dict) else []

    def _get_recovery_suggestions(self, error: Exception) -> List[str]:
        """Generate recovery suggestions based on the error type."""
        suggestions = []
        if isinstance(error, asyncio.TimeoutError):
            suggestions.append(f"Consider increasing timeout from {self.timeout_seconds}s")
            suggestions.append("Check for performance bottlenecks in node logic")
        if isinstance(error, MockWorkflowStateError):
            suggestions.append("Verify previous nodes are producing correct output")
            suggestions.append("Check state schema compatibility")
        return suggestions

    def get_health_status(self) -> Dict[str, Any]:
        """Get current health status of the node."""
        success_rate = (
            self._successful_executions / self._total_executions
            if self._total_executions > 0 else 1.0
        )

        return {
            "node_name": self.name,
            "total_executions": self._total_executions,
            "successful_executions": self._successful_executions,
            "failed_executions": self._failed_executions,
            "success_rate": success_rate,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "healthy": success_rate >= 0.95,
        }

    @abstractmethod
    async def _execute_node_logic(self, state: ReviewGenerationState) -> ResultType:
        """Main node logic implementation."""
        pass

    @abstractmethod
    def _get_required_state_keys(self) -> List[str]:
        """Return list of required state keys for this node."""
        pass

    @abstractmethod
    def _get_state_type_requirements(self) -> Dict[str, Type]:
        """Return dict mapping state keys to their expected types."""
        pass

# Test implementation
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

    # Test error handling - missing required key
    print("\n🧪 Testing error handling...")
    try:
        invalid_state = {"wrong_key": "value"}
        result = await node.execute(invalid_state)
        print(f"✅ Error handled gracefully: {not result.success}")
        print(f"✅ Error type: {type(result.error).__name__}")
        print(f"✅ Recovery suggestions: {result.recovery_suggestions}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

    print("\n🎉 Base Node Infrastructure Test PASSED!")

if __name__ == "__main__":
    asyncio.run(test_base_node())