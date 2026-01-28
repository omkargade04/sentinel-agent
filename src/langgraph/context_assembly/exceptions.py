"""
Context Assembly Exception Hierarchy

Comprehensive exception handling for context assembly system with
detailed error categorization and recovery guidance.

Note: LLM-specific exceptions (CostLimitExceededError, LLMClientError, etc.)
are kept for backward compatibility and potential use in Review Generation phase.
Context assembly itself no longer uses LLM - it uses rule-based ranking.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime


class ContextAssemblyError(Exception):
    """Base exception for all context assembly errors."""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = False
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}
        self.recoverable = recoverable
        self.timestamp = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/serialization."""
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
            "recoverable": self.recoverable,
            "timestamp": self.timestamp.isoformat()
        }

    def __str__(self) -> str:
        return f"{self.error_code}: {self.message}"


# ============================================================================
# RESOURCE AND COST ERRORS
# ============================================================================

class CostLimitExceededError(ContextAssemblyError):
    """Raised when LLM API cost budget is exceeded."""

    def __init__(
        self,
        message: str,
        current_cost: float = 0.0,
        budget_limit: float = 0.0,
        predicted_cost: float = 0.0
    ):
        super().__init__(
            message=message,
            error_code="COST_LIMIT_EXCEEDED",
            details={
                "current_cost_usd": current_cost,
                "budget_limit_usd": budget_limit,
                "predicted_cost_usd": predicted_cost,
                "overage_usd": current_cost + predicted_cost - budget_limit
            },
            recoverable=False  # Budget exhaustion is not recoverable
        )


class RateLimitExceededError(ContextAssemblyError):
    """Raised when API rate limits are exceeded."""

    def __init__(
        self,
        message: str,
        retry_after_seconds: Optional[int] = None,
        rate_type: str = "requests"
    ):
        super().__init__(
            message=message,
            error_code="RATE_LIMIT_EXCEEDED",
            details={
                "rate_type": rate_type,
                "retry_after_seconds": retry_after_seconds
            },
            recoverable=True  # Rate limits are temporary
        )


class HardLimitsExceededError(ContextAssemblyError):
    """Raised when hard limits (items, characters) cannot be satisfied."""

    def __init__(
        self,
        message: str,
        limit_type: str,
        current_value: Any = None,
        limit_value: Any = None
    ):
        super().__init__(
            message=message,
            error_code="HARD_LIMITS_EXCEEDED",
            details={
                "limit_type": limit_type,
                "current_value": current_value,
                "limit_value": limit_value
            },
            recoverable=False  # Hard limits are configuration constraints
        )


# ============================================================================
# CIRCUIT BREAKER ERRORS
# ============================================================================

class CircuitBreakerError(ContextAssemblyError):
    """Base class for circuit breaker related errors."""
    pass


class CircuitBreakerOpenError(CircuitBreakerError):
    """Raised when circuit breaker is open and blocking requests."""

    def __init__(
        self,
        message: str,
        circuit_breaker_name: str = "unknown",
        failure_count: int = 0,
        recovery_time_seconds: Optional[int] = None
    ):
        super().__init__(
            message=message,
            error_code="CIRCUIT_BREAKER_OPEN",
            details={
                "circuit_breaker_name": circuit_breaker_name,
                "failure_count": failure_count,
                "recovery_time_seconds": recovery_time_seconds
            },
            recoverable=True  # Circuit breakers can recover
        )


# ============================================================================
# LLM CLIENT ERRORS
# ============================================================================

class LLMClientError(ContextAssemblyError):
    """Base class for LLM client errors."""
    pass


class LLMTimeoutError(LLMClientError):
    """Raised when LLM API requests timeout."""

    def __init__(
        self,
        message: str,
        timeout_seconds: float = 0.0,
        operation: str = "completion"
    ):
        super().__init__(
            message=message,
            error_code="LLM_TIMEOUT",
            details={
                "timeout_seconds": timeout_seconds,
                "operation": operation
            },
            recoverable=True  # Timeouts can be retried
        )


class LLMAuthenticationError(LLMClientError):
    """Raised when LLM API authentication fails."""

    def __init__(self, message: str, provider: str = "unknown"):
        super().__init__(
            message=message,
            error_code="LLM_AUTHENTICATION_ERROR",
            details={"provider": provider},
            recoverable=False  # Auth errors need configuration fix
        )


class LLMQuotaExceededError(LLMClientError):
    """Raised when LLM API quota is exceeded."""

    def __init__(
        self,
        message: str,
        provider: str = "unknown",
        quota_type: str = "unknown",
        reset_time: Optional[datetime] = None
    ):
        super().__init__(
            message=message,
            error_code="LLM_QUOTA_EXCEEDED",
            details={
                "provider": provider,
                "quota_type": quota_type,
                "reset_time": reset_time.isoformat() if reset_time else None
            },
            recoverable=True  # Quotas reset over time
        )


# ============================================================================
# CONTEXT RANKING ERRORS
# ============================================================================

class ContextRankingError(ContextAssemblyError):
    """Base class for context ranking and scoring errors."""
    pass


class RelevanceScoringError(ContextRankingError):
    """Raised when relevance scoring fails."""

    def __init__(
        self,
        message: str,
        candidates_processed: int = 0,
        batch_size: int = 0
    ):
        super().__init__(
            message=message,
            error_code="RELEVANCE_SCORING_ERROR",
            details={
                "candidates_processed": candidates_processed,
                "batch_size": batch_size
            },
            recoverable=True  # Can fallback to rule-based scoring
        )


class DeduplicationError(ContextRankingError):
    """Raised when deduplication process fails."""

    def __init__(
        self,
        message: str,
        candidates_count: int = 0,
        similarity_threshold: float = 0.0
    ):
        super().__init__(
            message=message,
            error_code="DEDUPLICATION_ERROR",
            details={
                "candidates_count": candidates_count,
                "similarity_threshold": similarity_threshold
            },
            recoverable=True  # Can skip deduplication
        )


# ============================================================================
# LANGRAPH WORKFLOW ERRORS
# ============================================================================

class LangGraphError(ContextAssemblyError):
    """Base class for LangGraph workflow errors."""
    pass


class WorkflowExecutionError(LangGraphError):
    """Raised when LangGraph workflow execution fails."""

    def __init__(
        self,
        message: str,
        workflow_name: str = "unknown",
        node_name: Optional[str] = None,
        execution_step: int = 0
    ):
        super().__init__(
            message=message,
            error_code="WORKFLOW_EXECUTION_ERROR",
            details={
                "workflow_name": workflow_name,
                "node_name": node_name,
                "execution_step": execution_step
            },
            recoverable=True  # Workflows can be retried
        )


class NodeExecutionError(LangGraphError):
    """Raised when a specific workflow node fails."""

    def __init__(
        self,
        message: str,
        node_name: str,
        input_data: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            error_code="NODE_EXECUTION_ERROR",
            details={
                "node_name": node_name,
                "input_data_keys": list(input_data.keys()) if input_data else []
            },
            recoverable=True  # Individual nodes can often be retried
        )


class WorkflowTimeoutError(LangGraphError):
    """Raised when workflow execution exceeds timeout."""

    def __init__(
        self,
        message: str,
        timeout_seconds: float = 0.0,
        completed_nodes: Optional[List[str]] = None
    ):
        super().__init__(
            message=message,
            error_code="WORKFLOW_TIMEOUT",
            details={
                "timeout_seconds": timeout_seconds,
                "completed_nodes": completed_nodes or []
            },
            recoverable=True  # Can retry with higher timeout
        )


# ============================================================================
# DATA VALIDATION ERRORS
# ============================================================================

class ValidationError(ContextAssemblyError):
    """Base class for data validation errors."""
    pass


class InvalidInputDataError(ValidationError):
    """Raised when input data validation fails."""

    def __init__(
        self,
        message: str,
        field_name: Optional[str] = None,
        validation_rule: Optional[str] = None
    ):
        super().__init__(
            message=message,
            error_code="INVALID_INPUT_DATA",
            details={
                "field_name": field_name,
                "validation_rule": validation_rule
            },
            recoverable=False  # Invalid input needs correction
        )


class ContextPackValidationError(ValidationError):
    """Raised when context pack validation fails."""

    def __init__(
        self,
        message: str,
        validation_errors: Optional[List[str]] = None
    ):
        super().__init__(
            message=message,
            error_code="CONTEXT_PACK_VALIDATION",
            details={
                "validation_errors": validation_errors or []
            },
            recoverable=False  # Validation failures need fixes
        )


# ============================================================================
# EXTERNAL DEPENDENCY ERRORS
# ============================================================================

class ExternalDependencyError(ContextAssemblyError):
    """Base class for external dependency errors."""
    pass


class KnowledgeGraphError(ExternalDependencyError):
    """Raised when knowledge graph operations fail."""

    def __init__(
        self,
        message: str,
        operation: str = "query",
        kg_service: str = "neo4j"
    ):
        super().__init__(
            message=message,
            error_code="KNOWLEDGE_GRAPH_ERROR",
            details={
                "operation": operation,
                "kg_service": kg_service
            },
            recoverable=True  # KG operations can often be retried
        )


class FileSystemError(ExternalDependencyError):
    """Raised when file system operations fail."""

    def __init__(
        self,
        message: str,
        operation: str = "read",
        file_path: Optional[str] = None
    ):
        super().__init__(
            message=message,
            error_code="FILE_SYSTEM_ERROR",
            details={
                "operation": operation,
                "file_path": file_path
            },
            recoverable=True  # File operations can often be retried
        )


# ============================================================================
# GRACEFUL DEGRADATION SUPPORT
# ============================================================================

class GracefulDegradationManager:
    """
    Manages graceful degradation strategies when errors occur.

    Provides fallback mechanisms and recovery strategies for different
    types of context assembly failures.
    """

    def __init__(self):
        self.degradation_strategies = {
            CostLimitExceededError: self._handle_cost_limit_exceeded,
            RateLimitExceededError: self._handle_rate_limit_exceeded,
            CircuitBreakerOpenError: self._handle_circuit_breaker_open,
            LLMTimeoutError: self._handle_llm_timeout,
            RelevanceScoringError: self._handle_relevance_scoring_error,
            WorkflowExecutionError: self._handle_workflow_execution_error,
        }

    async def handle_error(
        self,
        error: ContextAssemblyError,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle error with appropriate degradation strategy.

        Args:
            error: The error that occurred
            context: Additional context for recovery decisions

        Returns:
            Recovery result with fallback data and status
        """
        error_type = type(error)
        handler = self.degradation_strategies.get(error_type)

        if handler:
            return await handler(error, context)
        else:
            return await self._handle_unknown_error(error, context)

    async def _handle_cost_limit_exceeded(
        self,
        error: CostLimitExceededError,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle cost limit exceeded with budget-aware fallback."""
        return {
            "strategy": "cost_aware_fallback",
            "action": "use_rule_based_scoring_only",
            "context_quality": "reduced",
            "fallback_data": {
                "use_llm_scoring": False,
                "max_candidates": min(context.get("max_candidates", 35), 20),
                "prioritize_seed_symbols": True
            },
            "message": "Switched to rule-based scoring to stay within budget"
        }

    async def _handle_rate_limit_exceeded(
        self,
        error: RateLimitExceededError,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle rate limits with queuing and batching."""
        retry_after = error.details.get("retry_after_seconds", 60)

        return {
            "strategy": "delayed_retry",
            "action": "queue_for_retry",
            "retry_after_seconds": retry_after,
            "fallback_data": {
                "use_cached_scores": True,
                "reduce_batch_size": True,
                "extend_timeout": True
            },
            "message": f"Rate limited, will retry in {retry_after} seconds"
        }

    async def _handle_circuit_breaker_open(
        self,
        error: CircuitBreakerOpenError,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle circuit breaker with cached data and rule-based fallbacks."""
        return {
            "strategy": "circuit_breaker_fallback",
            "action": "use_cached_data_and_rules",
            "context_quality": "degraded",
            "fallback_data": {
                "use_cached_relevance_scores": True,
                "use_rule_based_ranking": True,
                "skip_deduplication": True,
                "reduce_context_items": True
            },
            "message": "Circuit breaker open, using cached data and rule-based fallbacks"
        }

    async def _handle_llm_timeout(
        self,
        error: LLMTimeoutError,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle LLM timeouts with smaller batches and retries."""
        return {
            "strategy": "timeout_recovery",
            "action": "reduce_batch_size_and_retry",
            "fallback_data": {
                "batch_size": max(1, context.get("batch_size", 10) // 2),
                "timeout_multiplier": 1.5,
                "max_retries": 2,
                "use_simpler_prompts": True
            },
            "message": "LLM timeout, reducing batch size and retrying"
        }

    async def _handle_relevance_scoring_error(
        self,
        error: RelevanceScoringError,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle relevance scoring failures with rule-based fallback."""
        return {
            "strategy": "scoring_fallback",
            "action": "use_rule_based_scoring",
            "context_quality": "reduced",
            "fallback_data": {
                "use_rule_based_scoring": True,
                "weight_seed_symbols_higher": True,
                "prefer_changed_files": True,
                "use_distance_from_seed": True
            },
            "message": "LLM scoring failed, using rule-based relevance calculation"
        }

    async def _handle_workflow_execution_error(
        self,
        error: WorkflowExecutionError,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle workflow failures with simplified pipeline."""
        return {
            "strategy": "simplified_workflow",
            "action": "use_direct_processing",
            "fallback_data": {
                "skip_complex_nodes": True,
                "use_sequential_processing": True,
                "reduce_parallelism": True,
                "skip_optional_steps": True
            },
            "message": "Workflow failed, using simplified processing pipeline"
        }

    async def _handle_unknown_error(
        self,
        error: ContextAssemblyError,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle unknown errors with conservative fallback."""
        return {
            "strategy": "conservative_fallback",
            "action": "minimal_context_assembly",
            "context_quality": "minimal",
            "fallback_data": {
                "use_seed_symbols_only": True,
                "skip_kg_expansion": True,
                "use_patch_context_only": True,
                "max_items": 10
            },
            "message": f"Unknown error ({type(error).__name__}), using minimal context assembly"
        }

    def can_recover_from(self, error: ContextAssemblyError) -> bool:
        """Check if an error type has a recovery strategy."""
        return error.recoverable or type(error) in self.degradation_strategies

    def get_supported_strategies(self) -> List[str]:
        """Get list of supported degradation strategies."""
        return [
            error_type.__name__ for error_type in self.degradation_strategies.keys()
        ]