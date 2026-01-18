"""
Base Node Infrastructure for Review Generation Workflow

Production-grade abstract base class for LangGraph workflow nodes with:
- Comprehensive error handling and recovery
- Performance metrics collection
- Circuit breaker integration patterns
- Timeout handling with graceful degradation
- Type-safe state validation
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, TypeVar, Generic, Type
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from uuid import uuid4

from src.langgraph.review_generation.circuit_breaker import CircuitBreaker
from src.langgraph.review_generation.exceptions import (
    WorkflowNodeError,
    WorkflowStateError,
    ReviewGenerationError
)
from src.langgraph.review_generation.schema import ReviewGenerationState

logger = logging.getLogger(__name__)

# Type variables for generic node handling
StateType = TypeVar('StateType', bound=Dict[str, Any])
ResultType = TypeVar('ResultType', bound=Dict[str, Any])


# ============================================================================
# NODE METRICS AND MONITORING
# ============================================================================

@dataclass
class NodeExecutionMetrics:
    """Comprehensive metrics for node execution."""

    # Basic execution info
    node_name: str
    execution_id: str = field(default_factory=lambda: str(uuid4())[:8])
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    execution_time_seconds: float = 0.0

    # Data flow metrics
    input_size_bytes: int = 0
    output_size_bytes: int = 0
    state_keys_processed: List[str] = field(default_factory=list)

    # Error and performance metrics
    error_count: int = 0
    warning_count: int = 0
    retry_count: int = 0
    timeout_occurred: bool = False
    circuit_breaker_triggered: bool = False

    # Resource usage (if available)
    peak_memory_mb: Optional[float] = None
    cpu_time_seconds: Optional[float] = None

    def mark_complete(self) -> None:
        """Mark execution as complete and calculate final metrics."""
        self.end_time = datetime.utcnow()
        if self.start_time:
            self.execution_time_seconds = (self.end_time - self.start_time).total_seconds()

    def add_warning(self, message: str) -> None:
        """Add a warning and increment warning count."""
        self.warning_count += 1
        logger.warning(f"[{self.node_name}:{self.execution_id}] {message}")

    def add_error(self, error: Exception) -> None:
        """Add an error and increment error count."""
        self.error_count += 1
        logger.error(f"[{self.node_name}:{self.execution_id}] {str(error)}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for serialization."""
        return {
            "node_name": self.node_name,
            "execution_id": self.execution_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "execution_time_seconds": self.execution_time_seconds,
            "input_size_bytes": self.input_size_bytes,
            "output_size_bytes": self.output_size_bytes,
            "state_keys_processed": self.state_keys_processed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "retry_count": self.retry_count,
            "timeout_occurred": self.timeout_occurred,
            "circuit_breaker_triggered": self.circuit_breaker_triggered,
            "peak_memory_mb": self.peak_memory_mb,
            "cpu_time_seconds": self.cpu_time_seconds
        }


@dataclass
class NodeExecutionResult(Generic[ResultType]):
    """Result of node execution with comprehensive metadata."""

    # Execution status
    success: bool
    node_name: str
    execution_id: str

    # Data
    data: ResultType

    # Metrics and diagnostics
    metrics: NodeExecutionMetrics
    modified_state_keys: List[str] = field(default_factory=list)
    error: Optional[Exception] = None
    warnings: List[str] = field(default_factory=list)

    # Recovery information
    degraded_mode: bool = False
    fallback_used: bool = False
    recovery_suggestions: List[str] = field(default_factory=list)


# ============================================================================
# STATE VALIDATION
# ============================================================================

class StateValidator:
    """Validates workflow state integrity and completeness."""

    @staticmethod
    def validate_required_keys(state: Dict[str, Any], required_keys: List[str], node_name: str) -> None:
        """Validate that all required state keys are present."""
        missing_keys = [key for key in required_keys if key not in state]
        if missing_keys:
            raise WorkflowStateError(
                f"Node {node_name} missing required state keys: {missing_keys}",
                missing_fields=missing_keys
            )

    @staticmethod
    def validate_state_types(state: Dict[str, Any], type_requirements: Dict[str, Type], node_name: str) -> None:
        """Validate that state values match expected types."""
        invalid_fields = []
        for key, expected_type in type_requirements.items():
            if key in state and not isinstance(state[key], expected_type):
                invalid_fields.append(f"{key}: expected {expected_type.__name__}, got {type(state[key]).__name__}")

        if invalid_fields:
            raise WorkflowStateError(
                f"Node {node_name} has invalid state field types: {invalid_fields}",
                invalid_fields=invalid_fields
            )

    @staticmethod
    def calculate_state_size(state: Dict[str, Any]) -> int:
        """Calculate approximate size of state in bytes."""
        try:
            import sys
            return sys.getsizeof(str(state))
        except Exception:
            return len(str(state).encode('utf-8'))


# ============================================================================
# TIMEOUT AND CIRCUIT BREAKER MANAGEMENT
# ============================================================================

class TimeoutManager:
    """Manages operation timeouts with configurable strategies."""

    def __init__(self, default_timeout: float = 60.0):
        self.default_timeout = default_timeout

    @asynccontextmanager
    async def timeout_context(self, timeout_seconds: Optional[float] = None):
        """Context manager for timeout handling."""
        timeout = timeout_seconds or self.default_timeout

        try:
            async with asyncio.timeout(timeout):
                yield timeout
        except asyncio.TimeoutError:
            logger.error(f"Operation timed out after {timeout} seconds")
            raise


# ============================================================================
# ABSTRACT BASE NODE
# ============================================================================

class BaseReviewGenerationNode(ABC, Generic[StateType, ResultType]):
    """
    Abstract base class for review generation workflow nodes.

    Provides comprehensive infrastructure for:
    - Error handling with recovery strategies
    - Performance monitoring and metrics collection
    - Circuit breaker integration for fault tolerance
    - Timeout handling with graceful degradation
    - State validation and type safety
    """

    def __init__(
        self,
        name: str,
        timeout_seconds: float = 60.0,
        circuit_breaker: Optional[CircuitBreaker] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ):
        self.name = name
        self.timeout_seconds = timeout_seconds
        self.circuit_breaker = circuit_breaker
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Set up logging
        self.logger = logging.getLogger(f"{__name__}.{name}")

        # Initialize timeout manager
        self.timeout_manager = TimeoutManager(timeout_seconds)

        # Initialize metrics
        self._total_executions = 0
        self._successful_executions = 0
        self._failed_executions = 0

    async def execute(self, state: ReviewGenerationState) -> NodeExecutionResult[ResultType]:
        """
        Execute the node with comprehensive error handling and monitoring.

        This is the main entry point that orchestrates:
        1. State validation
        2. Timeout management
        3. Circuit breaker integration
        4. Metrics collection
        5. Error handling and recovery
        6. Retry logic
        """
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
            # Handle execution failure
            metrics.add_error(e)
            metrics.mark_complete()

            self._failed_executions += 1

            self.logger.error(
                f"Node {self.name} [{execution_id}] failed after "
                f"{metrics.execution_time_seconds:.2f}s: {str(e)}"
            )

            # Attempt graceful degradation
            degraded_result = await self._attempt_graceful_degradation(state, e, metrics)

            if degraded_result is not None:
                return NodeExecutionResult(
                    success=False,
                    node_name=self.name,
                    execution_id=execution_id,
                    data=degraded_result,
                    metrics=metrics,
                    error=e,
                    degraded_mode=True,
                    fallback_used=True,
                    recovery_suggestions=self._get_recovery_suggestions(e)
                )
            else:
                return NodeExecutionResult(
                    success=False,
                    node_name=self.name,
                    execution_id=execution_id,
                    data={},  # type: ignore
                    metrics=metrics,
                    error=e,
                    recovery_suggestions=self._get_recovery_suggestions(e)
                )

    async def _execute_with_retry(
        self,
        state: ReviewGenerationState,
        metrics: NodeExecutionMetrics
    ) -> ResultType:
        """Execute the node with retry logic and circuit breaker protection."""
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    metrics.retry_count += 1
                    await asyncio.sleep(self.retry_delay * attempt)  # Exponential backoff
                    self.logger.info(f"Retrying {self.name} (attempt {attempt + 1}/{self.max_retries + 1})")

                # Circuit breaker protection
                if self.circuit_breaker and not await self._check_circuit_breaker(metrics):
                    continue

                # Execute with timeout
                async with self.timeout_manager.timeout_context(self.timeout_seconds):
                    result = await self._execute_node_logic(state)

                # Record success in circuit breaker
                if self.circuit_breaker:
                    await self._record_success_in_circuit_breaker()

                return result

            except asyncio.TimeoutError:
                metrics.timeout_occurred = True
                last_exception = WorkflowNodeError(
                    f"Node {self.name} timed out after {self.timeout_seconds} seconds",
                    node_name=self.name,
                    input_state_keys=list(state.keys())
                )
                self.logger.warning(f"Timeout occurred for {self.name} (attempt {attempt + 1})")

            except Exception as e:
                last_exception = e
                # Record failure in circuit breaker
                if self.circuit_breaker:
                    await self._record_failure_in_circuit_breaker(e)

                # Don't retry for certain error types
                if not self._should_retry_error(e):
                    break

                self.logger.warning(f"Attempt {attempt + 1} failed for {self.name}: {str(e)}")

        # All retries exhausted
        if last_exception:
            raise last_exception
        else:
            raise WorkflowNodeError(
                f"Node {self.name} failed after {self.max_retries} retries",
                node_name=self.name,
                input_state_keys=list(state.keys())
            )

    async def _check_circuit_breaker(self, metrics: NodeExecutionMetrics) -> bool:
        """Check if circuit breaker allows execution."""
        if not self.circuit_breaker:
            return True

        try:
            return await self.circuit_breaker.can_execute()
        except Exception as e:
            metrics.circuit_breaker_triggered = True
            self.logger.warning(f"Circuit breaker check failed: {e}")
            return False

    async def _record_success_in_circuit_breaker(self) -> None:
        """Record successful execution in circuit breaker."""
        if self.circuit_breaker:
            await self.circuit_breaker.record_success()

    async def _record_failure_in_circuit_breaker(self, error: Exception) -> None:
        """Record failed execution in circuit breaker."""
        if self.circuit_breaker:
            await self.circuit_breaker.record_failure(str(error))

    def _should_retry_error(self, error: Exception) -> bool:
        """Determine if an error should trigger a retry."""
        # Don't retry validation errors or permanent failures
        if isinstance(error, (WorkflowStateError, ValueError, TypeError)):
            return False

        # Don't retry review generation errors marked as non-recoverable
        if isinstance(error, ReviewGenerationError) and not error.recoverable:
            return False

        return True

    # ========================================================================
    # ABSTRACT METHODS - Must be implemented by subclasses
    # ========================================================================

    @abstractmethod
    async def _execute_node_logic(self, state: ReviewGenerationState) -> ResultType:
        """
        Main node logic implementation.

        This method contains the core business logic for the node.
        It should be pure and stateless - all error handling, retries,
        timeouts, and metrics are handled by the base class.
        """
        pass

    @abstractmethod
    def _get_required_state_keys(self) -> List[str]:
        """Return list of required state keys for this node."""
        pass

    @abstractmethod
    def _get_state_type_requirements(self) -> Dict[str, Type]:
        """Return dict mapping state keys to their expected types."""
        pass

    # ========================================================================
    # VALIDATION AND UTILITY METHODS
    # ========================================================================

    async def _validate_input_state(
        self,
        state: ReviewGenerationState,
        metrics: NodeExecutionMetrics
    ) -> None:
        """Validate input state meets node requirements."""
        try:
            # Check required keys
            required_keys = self._get_required_state_keys()
            StateValidator.validate_required_keys(state, required_keys, self.name)

            # Check types
            type_requirements = self._get_state_type_requirements()
            StateValidator.validate_state_types(state, type_requirements, self.name)

        except Exception as e:
            metrics.add_error(e)
            raise

    def _get_modified_state_keys(self, result_data: ResultType) -> List[str]:
        """Get list of state keys that will be modified by this node's output."""
        # Default implementation - subclasses can override for more precise tracking
        return list(result_data.keys()) if isinstance(result_data, dict) else []

    async def _attempt_graceful_degradation(
        self,
        state: ReviewGenerationState,
        error: Exception,
        metrics: NodeExecutionMetrics
    ) -> Optional[ResultType]:
        """
        Attempt graceful degradation when node execution fails.

        Subclasses can override this to provide fallback behavior.
        Return None if no degradation is possible.
        """
        return None

    def _get_recovery_suggestions(self, error: Exception) -> List[str]:
        """Generate recovery suggestions based on the error type."""
        suggestions = []

        if isinstance(error, asyncio.TimeoutError):
            suggestions.append(f"Consider increasing timeout from {self.timeout_seconds}s")
            suggestions.append("Check for performance bottlenecks in node logic")

        if isinstance(error, WorkflowStateError):
            suggestions.append("Verify previous nodes are producing correct output")
            suggestions.append("Check state schema compatibility")

        if self.circuit_breaker and hasattr(error, 'circuit_breaker_open'):
            suggestions.append("Wait for circuit breaker to recover")
            suggestions.append("Check external service health")

        return suggestions

    # ========================================================================
    # MONITORING AND HEALTH CHECK
    # ========================================================================

    def get_health_status(self) -> Dict[str, Any]:
        """Get current health status of the node."""
        success_rate = (
            self._successful_executions / self._total_executions
            if self._total_executions > 0 else 1.0
        )

        status = {
            "node_name": self.name,
            "total_executions": self._total_executions,
            "successful_executions": self._successful_executions,
            "failed_executions": self._failed_executions,
            "success_rate": success_rate,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "healthy": success_rate >= 0.95,  # Consider healthy if >95% success rate
        }

        if self.circuit_breaker:
            cb_health = self.circuit_breaker.health_check()
            status["circuit_breaker"] = cb_health
            status["healthy"] = status["healthy"] and cb_health["status"] == "healthy"

        return status

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get performance metrics for monitoring."""
        return {
            "node_name": self.name,
            "total_executions": self._total_executions,
            "success_rate": self._successful_executions / max(self._total_executions, 1),
            "configuration": {
                "timeout_seconds": self.timeout_seconds,
                "max_retries": self.max_retries,
                "retry_delay": self.retry_delay,
                "circuit_breaker_enabled": self.circuit_breaker is not None
            }
        }