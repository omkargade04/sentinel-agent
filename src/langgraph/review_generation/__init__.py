"""
Review Generation Package

Production-grade AI review generation system for code review.

Features:
- 6-node LangGraph workflow orchestration
- Deterministic diff anchoring
- Anti-hallucination prompt engineering
- Quality validation and filtering
- Graceful degradation patterns
"""

from .circuit_breaker import CircuitBreaker
from .exceptions import (
    ReviewGenerationError,
    LLMGenerationError,
    AnchoringError,
    PromptBuildError,
    QualityValidationError,
    DiffProcessingError,
    WorkflowExecutionError,
    WorkflowNodeError,
    WorkflowStateError,
)
from .schema import (
    RawLLMFinding,
    RawLLMReviewOutput,
    AnalyzedContext,
    DiffMappings,
    HunkMapping,
    AnchoredFinding,
    ReviewGenerationState,
)
from .base_node import (
    BaseReviewGenerationNode,
    NodeExecutionMetrics,
    NodeExecutionResult,
    StateValidator,
    TimeoutManager,
)
from .context_analyzer import ContextAnalyzerNode
from .diff_processor import DiffProcessorNode
from .prompt_builder import PromptBuilderNode
from .llm_generator import LLMGeneratorNode
from .finding_anchorer import FindingAnchorerNode
from .quality_validator import QualityValidatorNode

from .langgraph_workflow import (
    ReviewGenerationWorkflow,
    ReviewWorkflowState,
    WorkflowExecutionMetrics,
)
from .review_graph import ReviewGenerationGraph
from .service import (
    ReviewGenerationService,
    ReviewGenerationConfig,
    ReviewGenerationMetrics,
)

__all__ = [
    # Circuit breaker
    "CircuitBreaker",
    
    # Exceptions
    "ReviewGenerationError",
    "LLMGenerationError",
    "AnchoringError",
    "PromptBuildError",
    "QualityValidationError",
    "DiffProcessingError",
    "WorkflowExecutionError",
    "WorkflowNodeError",
    "WorkflowStateError",

    # Internal schemas
    "RawLLMFinding",
    "RawLLMReviewOutput",
    "AnalyzedContext",
    "DiffMappings",
    "HunkMapping",
    "AnchoredFinding",
    "ReviewGenerationState",

    # Base node infrastructure
    "BaseReviewGenerationNode",
    "NodeExecutionMetrics",
    "NodeExecutionResult",
    "StateValidator",
    "TimeoutManager",

    # Workflow infrastructure
    "ReviewGenerationWorkflow",
    "ReviewWorkflowState",
    "WorkflowExecutionMetrics",
    "ContextAnalyzerNode",
    "DiffProcessorNode",
    "PromptBuilderNode",
    "LLMGeneratorNode",
    "FindingAnchorerNode",
    "QualityValidatorNode",
    
    # Integration layer
    "ReviewGenerationGraph",
    
    # Service layer
    "ReviewGenerationService",
    "ReviewGenerationConfig",
    "ReviewGenerationMetrics",
]

__version__ = "1.0.0"