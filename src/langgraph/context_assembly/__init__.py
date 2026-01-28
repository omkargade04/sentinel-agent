"""
Context Assembly Package

Production-grade context assembly system for AI code review.

Features:
- Rule-based relevance scoring (fast, free, deterministic)
- LangGraph workflow orchestration
- Hard limits enforcement
- Circuit breaker patterns
- Comprehensive error handling and graceful degradation
"""

from .service import ContextAssemblyService, AssemblyConfig, AssemblyMetrics
from .context_graph import ContextAssemblyGraph
from .rule_based_ranker import RuleBasedContextRanker
from .hard_limits_enforcer import HardLimitsEnforcer
from .circuit_breaker import CircuitBreaker, MultiCircuitBreaker
from .langgraph_workflow import ContextAssemblyWorkflow
from .exceptions import (
    ContextAssemblyError,
    WorkflowExecutionError,
    NodeExecutionError,
    WorkflowTimeoutError,
    GracefulDegradationManager
)

__all__ = [
    # Main service
    "ContextAssemblyService",
    "AssemblyConfig",
    "AssemblyMetrics",

    # Integration layer
    "ContextAssemblyGraph",

    # Ranking
    "RuleBasedContextRanker",

    # Core components
    "HardLimitsEnforcer",
    "CircuitBreaker",
    "MultiCircuitBreaker",

    # Workflow
    "ContextAssemblyWorkflow",

    # Exceptions
    "ContextAssemblyError",
    "WorkflowExecutionError",
    "NodeExecutionError",
    "WorkflowTimeoutError",
    "GracefulDegradationManager",
]

__version__ = "2.0.0"
