"""
Review Generation LangGraph Workflow

Production-grade 6-node LangGraph workflow implementation for AI-powered code review generation.
Transforms assembled context into structured, anchored review findings.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, TypedDict
from dataclasses import dataclass, field
from uuid import uuid4

from src.langgraph.review_generation import DiffProcessorNode, FindingAnchorerNode, PromptBuilderNode, QualityValidatorNode
from src.langgraph.review_generation.circuit_breaker import CircuitBreaker
from src.langgraph.review_generation.base_node import (
    BaseReviewGenerationNode,
    NodeExecutionResult,
    NodeExecutionMetrics
)
from src.langgraph.review_generation.exceptions import (
    WorkflowExecutionError,
    WorkflowNodeError,
    WorkflowStateError
)
from src.langgraph.review_generation.schema import (
    ReviewGenerationState,
    RawLLMReviewOutput,
    AnalyzedContext,
    DiffMappings,
    RawLLMFinding
)
from src.langgraph.review_generation.context_analyzer import (
    ContextAnalyzerNode
)
from src.langgraph.review_generation.llm_generator import (
    LLMGeneratorNode
)

logger = logging.getLogger(__name__)


# ============================================================================
# WORKFLOW STATE DEFINITION
# ============================================================================

class ReviewWorkflowState(ReviewGenerationState):
    """
    State passed between review generation workflow nodes.

    This extends the base ReviewGenerationState with specific fields
    needed for the 6-node review generation pipeline.
    """
    # Input data
    context_pack: Dict[str, Any]
    patches: List[Dict[str, Any]]
    limits: Dict[str, Any]

    # Processing state (populated by nodes)
    analyzed_context: Optional[AnalyzedContext] = None
    diff_mappings: Optional[DiffMappings] = None
    structured_prompt: Optional[str] = None
    raw_llm_output: Optional[RawLLMReviewOutput] = None
    anchored_findings: Optional[List[Dict[str, Any]]] = None
    final_review_output: Optional[Dict[str, Any]] = None

    # Workflow metadata
    workflow_id: str = field(default_factory=lambda: str(uuid4()))
    execution_start_time: datetime = field(default_factory=datetime.utcnow)
    node_execution_times: Dict[str, float] = field(default_factory=dict)
    node_results: Dict[str, Any] = field(default_factory=dict)
    error_count: int = 0
    warnings: List[str] = field(default_factory=list)

    # Quality metrics
    total_context_items: int = 0
    selected_findings_count: int = 0
    anchored_findings_count: int = 0
    unanchored_findings_count: int = 0
    total_characters_generated: int = 0
    confidence_distribution: Dict[str, int] = field(default_factory=dict)


# ============================================================================
# WORKFLOW METRICS AND MONITORING
# ============================================================================

@dataclass
class WorkflowExecutionMetrics:
    """Comprehensive metrics for entire workflow execution."""

    workflow_id: str
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    total_execution_time_seconds: float = 0.0

    # Node execution tracking
    nodes_executed: List[str] = field(default_factory=list)
    nodes_failed: List[str] = field(default_factory=list)
    node_execution_times: Dict[str, float] = field(default_factory=dict)

    # Data flow metrics
    input_context_items: int = 0
    output_findings_count: int = 0
    total_retries: int = 0
    total_warnings: int = 0
    total_errors: int = 0

    # Quality metrics
    anchoring_success_rate: float = 0.0
    average_confidence_score: float = 0.0
    findings_by_severity: Dict[str, int] = field(default_factory=dict)

    def mark_complete(self) -> None:
        """Mark workflow execution as complete."""
        self.end_time = datetime.utcnow()
        if self.start_time:
            self.total_execution_time_seconds = (self.end_time - self.start_time).total_seconds()

    def add_node_result(self, node_name: str, result: NodeExecutionResult) -> None:
        """Add node execution result to metrics."""
        self.nodes_executed.append(node_name)
        self.node_execution_times[node_name] = result.metrics.execution_time_seconds

        if not result.success:
            self.nodes_failed.append(node_name)

        self.total_retries += result.metrics.retry_count
        self.total_warnings += result.metrics.warning_count
        self.total_errors += result.metrics.error_count

# ============================================================================
# MAIN WORKFLOW ORCHESTRATOR
# ============================================================================

class ReviewGenerationWorkflow:
    """
    6-node LangGraph workflow orchestrator for review generation.

    Coordinates the execution of all nodes with proper error handling,
    state management, and comprehensive metrics collection.
    """

    def __init__(
        self,
        circuit_breaker: Optional[CircuitBreaker] = None,
        timeout_seconds: float = 300.0  # 5 minutes total workflow timeout
    ):
        self.circuit_breaker = circuit_breaker
        self.timeout_seconds = timeout_seconds
        self.logger = logging.getLogger(f"{__name__}.workflow")

        # Initialize all nodes
        # NOTE: LLMGeneratorNode has llm_client as first param, so must use keyword arg
        self.nodes = {
            "context_analyzer": ContextAnalyzerNode(circuit_breaker),
            "diff_processor": DiffProcessorNode(circuit_breaker),
            "prompt_builder": PromptBuilderNode(circuit_breaker),
            "llm_generator": LLMGeneratorNode(circuit_breaker=circuit_breaker),
            "finding_anchorer": FindingAnchorerNode(circuit_breaker),
            "quality_validator": QualityValidatorNode(circuit_breaker)
        }

        # Define node execution order
        self.execution_order = [
            "context_analyzer",
            "diff_processor",
            "prompt_builder",
            "llm_generator",
            "finding_anchorer",
            "quality_validator"
        ]

        self._total_executions = 0
        self._successful_executions = 0
        self._failed_executions = 0

    async def execute(
        self,
        context_pack: Dict[str, Any],
        patches: List[Dict[str, Any]],
        limits: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute the complete 6-node review generation workflow.

        Args:
            context_pack: Rich context from Phase 5 (Context Assembly)
            patches: PR file patches with PRHunk data
            limits: Configuration limits and constraints

        Returns:
            Dictionary containing final review output and workflow metadata
        """
        workflow_id = str(uuid4())
        execution_start = datetime.utcnow()

        self.logger.info(f"Starting review generation workflow [{workflow_id}]")
        self._total_executions += 1

        # Initialize workflow metrics
        metrics = WorkflowExecutionMetrics(workflow_id=workflow_id)
        metrics.input_context_items = len(context_pack.get("context_items", []))

        try:
            # Initialize workflow state
            state: ReviewWorkflowState = {
                "context_pack": context_pack,
                "patches": patches,
                "limits": limits,
                "workflow_id": workflow_id,
                "execution_start_time": execution_start,
                "node_execution_times": {},
                "node_results": {},
                "error_count": 0,
                "warnings": [],
                "total_context_items": len(context_pack.get("context_items", [])),
                "selected_findings_count": 0,
                "anchored_findings_count": 0,
                "unanchored_findings_count": 0,
                "total_characters_generated": 0,
                "confidence_distribution": {}
            }

            # Execute workflow with timeout
            async with asyncio.timeout(self.timeout_seconds):
                final_state = await self._execute_workflow_nodes(state, metrics)

            # Extract final result
            final_output = final_state.get("final_review_output", {})

            metrics.output_findings_count = final_output.get("total_findings", 0)
            metrics.mark_complete()

            self._successful_executions += 1

            self.logger.info(
                f"Workflow [{workflow_id}] completed successfully in "
                f"{metrics.total_execution_time_seconds:.2f}s with "
                f"{metrics.output_findings_count} findings"
            )

            return {
                "workflow_id": workflow_id,
                "success": True,
                "final_review_output": final_output,
                "workflow_metadata": {
                    "execution_time_seconds": metrics.total_execution_time_seconds,
                    "nodes_executed": metrics.nodes_executed,
                    "total_retries": metrics.total_retries,
                    "total_warnings": metrics.total_warnings,
                    "total_errors": metrics.total_errors
                },
                "node_results": final_state.get("node_results", {}),
                "quality_metrics": {
                    "anchoring_success_rate": metrics.anchoring_success_rate,
                    "average_confidence_score": metrics.average_confidence_score,
                    "findings_by_severity": metrics.findings_by_severity
                }
            }

        except asyncio.TimeoutError:
            metrics.mark_complete()
            self._failed_executions += 1

            error_msg = f"Workflow [{workflow_id}] timed out after {self.timeout_seconds}s"
            self.logger.error(error_msg)

            return {
                "workflow_id": workflow_id,
                "success": False,
                "error": "WorkflowTimeout",
                "error_message": error_msg,
                "workflow_metadata": {
                    "execution_time_seconds": metrics.total_execution_time_seconds,
                    "nodes_executed": metrics.nodes_executed,
                    "timeout_occurred": True
                }
            }

        except Exception as e:
            metrics.mark_complete()
            self._failed_executions += 1

            error_msg = f"Workflow [{workflow_id}] failed: {str(e)}"
            self.logger.error(error_msg)

            return {
                "workflow_id": workflow_id,
                "success": False,
                "error": type(e).__name__,
                "error_message": str(e),
                "workflow_metadata": {
                    "execution_time_seconds": metrics.total_execution_time_seconds,
                    "nodes_executed": metrics.nodes_executed
                }
            }

    async def _execute_workflow_nodes(
        self,
        state: ReviewWorkflowState,
        metrics: WorkflowExecutionMetrics
    ) -> ReviewWorkflowState:
        """Execute all workflow nodes in sequence."""

        for node_name in self.execution_order:
            node: BaseReviewGenerationNode = self.nodes[node_name]

            self.logger.info(f"Executing node: {node_name}")

            try:
                # Execute node
                result = await node.execute(state)

                # Update metrics
                metrics.add_node_result(node_name, result)

                if result.success:
                    # Update state with node output
                    state.update(result.data)
                    state["node_results"][node_name] = {
                        "success": True,
                        "execution_time": result.metrics.execution_time_seconds,
                        "data": result.data
                    }
                    state["node_execution_times"][node_name] = result.metrics.execution_time_seconds

                    self.logger.info(f"Node {node_name} completed successfully")

                else:
                    # Handle node failure
                    state["error_count"] += 1
                    state["node_results"][node_name] = {
                        "success": False,
                        "error": str(result.error),
                        "execution_time": result.metrics.execution_time_seconds
                    }

                    error_msg = f"Node {node_name} failed: {result.error}"
                    self.logger.error(error_msg)

                    # Decide whether to continue or fail the workflow
                    if self._should_continue_after_node_failure(node_name, result.error):
                        state["warnings"].append(f"Node {node_name} failed but workflow continued")
                        continue
                    else:
                        raise WorkflowExecutionError(
                            f"Critical node {node_name} failed: {result.error}",
                            workflow_id=state["workflow_id"],
                            failed_node=node_name
                        )

            except Exception as e:
                state["error_count"] += 1
                state["node_results"][node_name] = {
                    "success": False,
                    "error": str(e),
                    "execution_time": 0.0
                }

                self.logger.error(f"Node {node_name} execution error: {e}")

                if not self._should_continue_after_node_failure(node_name, e):
                    raise

        return state

    def _should_continue_after_node_failure(self, node_name: str, error: Exception) -> bool:
        """Determine if workflow should continue after a node failure."""
        # Critical nodes that must succeed
        critical_nodes = {"context_analyzer", "quality_validator"}

        if node_name in critical_nodes:
            return False

        # For non-critical nodes, continue with degraded functionality
        return True

    def get_health_status(self) -> Dict[str, Any]:
        """Get overall workflow health status."""
        success_rate = (
            self._successful_executions / self._total_executions
            if self._total_executions > 0 else 1.0
        )

        node_health = {
            node_name: node.get_health_status()
            for node_name, node in self.nodes.items()
        }

        overall_healthy = success_rate >= 0.90 and all(
            node_status["healthy"] for node_status in node_health.values()
        )

        return {
            "workflow_healthy": overall_healthy,
            "success_rate": success_rate,
            "total_executions": self._total_executions,
            "successful_executions": self._successful_executions,
            "failed_executions": self._failed_executions,
            "timeout_seconds": self.timeout_seconds,
            "node_health": node_health
        }

    def get_metrics(self) -> Dict[str, Any]:
        """Get comprehensive workflow metrics."""
        return {
            "workflow_metrics": {
                "total_executions": self._total_executions,
                "success_rate": self._successful_executions / max(self._total_executions, 1),
                "average_execution_time": "not_available",  # Would need historical data
                "timeout_seconds": self.timeout_seconds
            },
            "node_metrics": {
                node_name: node.get_performance_metrics()
                for node_name, node in self.nodes.items()
            }
        }