"""
LangGraph Context Assembly Workflow

Production-grade LangGraph workflow implementation for intelligent context assembly.
Uses rule-based ranking with proper error handling and monitoring.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, TypedDict
from dataclasses import dataclass, field
from uuid import uuid4

from src.langgraph.context_assembly.base_node import BaseContextAssemblyNode
from src.langgraph.context_assembly.context_ranker import ContextRankerNode
from src.langgraph.context_assembly.candidate_enricher import CandidateEnricherNode
from src.langgraph.context_assembly.pack_assembler import PackAssemblerNode
from src.langgraph.context_assembly.seed_analyzer import SeedAnalyzerNode
from src.langgraph.context_assembly.snippet_extractor import SnippetExtractorNode
from src.models.schemas.pr_review.context_pack import ContextPackLimits
from src.models.schemas.pr_review.seed_set import SeedSetS0
from src.models.schemas.pr_review.pr_patch import PRFilePatch

from .rule_based_ranker import RuleBasedContextRanker
from .hard_limits_enforcer import HardLimitsEnforcer
from .circuit_breaker import CircuitBreaker
from .exceptions import (
    WorkflowExecutionError, NodeExecutionError, WorkflowTimeoutError,
    GracefulDegradationManager
)

logger = logging.getLogger(__name__)


# ============================================================================
# WORKFLOW STATE DEFINITIONS
# ============================================================================

class WorkflowState(TypedDict, total=False):
    """State passed between workflow nodes."""

    # Input data
    seed_set: SeedSetS0
    kg_candidates: Dict[str, Any]
    patches: List[PRFilePatch]
    limits: ContextPackLimits

    # Processing state
    enriched_candidates: List[Dict[str, Any]]
    scored_candidates: List[Dict[str, Any]]
    ranked_candidates: List[Dict[str, Any]]
    final_context_items: List[Dict[str, Any]]

    # Metadata and metrics
    workflow_id: str
    execution_start_time: datetime
    node_execution_times: Dict[str, float]
    node_results: Dict[str, Any]
    error_count: int
    warnings: List[str]

    # Quality metrics
    total_candidates_processed: int
    candidates_after_scoring: int
    candidates_after_ranking: int
    final_items_count: int
    total_characters: int


@dataclass
class NodeMetrics:
    """Metrics for individual node execution."""
    node_name: str
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    execution_time_seconds: float = 0.0
    input_size: int = 0
    output_size: int = 0
    error_count: int = 0
    warning_count: int = 0

    def mark_complete(self) -> None:
        """Mark node as complete and calculate execution time."""
        self.end_time = datetime.utcnow()
        if self.start_time:
            self.execution_time_seconds = (self.end_time - self.start_time).total_seconds()


@dataclass
class NodeResult:
    """Result of node execution."""
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    metrics: Optional[NodeMetrics] = None
    error: Optional[Exception] = None
    warnings: List[str] = field(default_factory=list)


# ============================================================================
# WORKFLOW NODE IMPLEMENTATIONS
# ============================================================================

# ============================================================================
# LANGRAPH WORKFLOW ORCHESTRATOR
# ============================================================================

class ContextAssemblyWorkflow:
    """
    Production-grade LangGraph workflow for context assembly.

    Orchestrates the multi-step context assembly process with proper
    error handling, monitoring, and graceful degradation.
    """

    def __init__(
        self,
        circuit_breaker: CircuitBreaker,
        timeout_seconds: int = 300
    ):
        self.circuit_breaker = circuit_breaker
        self.timeout_seconds = timeout_seconds

        # Initialize components
        self.context_ranker = RuleBasedContextRanker()
        self.limits_enforcer = HardLimitsEnforcer()
        self.degradation_manager = GracefulDegradationManager()

        # Initialize workflow nodes
        self.nodes = {
            "seed_analyzer": SeedAnalyzerNode(),
            "candidate_enricher": CandidateEnricherNode(),
            "snippet_extractor": SnippetExtractorNode(),
            "context_ranker": ContextRankerNode(self.context_ranker),
            "pack_assembler": PackAssemblerNode(self.limits_enforcer)
        }

        # Define workflow edges (execution order)
        self.workflow_edges = [
            ("seed_analyzer", "candidate_enricher"),
            ("candidate_enricher", "snippet_extractor"),
            ("snippet_extractor", "context_ranker"),
            ("context_ranker", "pack_assembler")
        ]

        logger.info(f"Initialized ContextAssemblyWorkflow with {len(self.nodes)} nodes")

    async def execute(
        self,
        seed_set: SeedSetS0,
        kg_candidates: Dict[str, Any],
        patches: List[PRFilePatch],
        limits: ContextPackLimits,
        clone_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute the complete workflow with error handling and timeout.

        Args:
            seed_set: Seed symbols from PR analysis
            kg_candidates: Knowledge graph candidates
            patches: PR file patches
            limits: Hard limits to enforce
            clone_path: Path to cloned repository for code extraction

        Returns:
            Dict containing final context items and execution metadata
        """
        workflow_id = str(uuid4())
        start_time = datetime.utcnow()

        # Initialize workflow state
        state: WorkflowState = {
            "seed_set": seed_set,
            "kg_candidates": kg_candidates,
            "patches": patches,
            "limits": limits,
            "clone_path": clone_path,
            "workflow_id": workflow_id,
            "execution_start_time": start_time,
            "node_execution_times": {},
            "node_results": {},
            "error_count": 0,
            "warnings": []
        }

        try:
            logger.info(
                f"Starting context assembly workflow {workflow_id} "
                f"with {len(kg_candidates.get('candidates', []))} candidates"
            )

            # Execute workflow with timeout
            final_result = await asyncio.wait_for(
                self._execute_workflow(state),
                timeout=self.timeout_seconds
            )

            execution_time = (datetime.utcnow() - start_time).total_seconds()

            logger.info(
                f"Workflow {workflow_id} completed in {execution_time:.2f}s "
                f"with {len(final_result.get('final_context_items', []))} items"
            )

            return {
                **final_result,
                "workflow_metadata": {
                    "workflow_id": workflow_id,
                    "execution_time_seconds": execution_time,
                    "node_execution_times": state["node_execution_times"],
                    "total_errors": state["error_count"],
                    "warnings": state["warnings"]
                }
            }

        except asyncio.TimeoutError:
            error_msg = f"Workflow {workflow_id} timed out after {self.timeout_seconds}s"
            logger.error(error_msg)
            raise WorkflowTimeoutError(
                error_msg,
                timeout_seconds=self.timeout_seconds,
                completed_nodes=list(state["node_results"].keys())
            )

        except Exception as e:
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"Workflow {workflow_id} failed after {execution_time:.2f}s: {e}")

            # Attempt graceful degradation
            try:
                degradation_result = await self.degradation_manager.handle_error(
                    e if isinstance(e, Exception) else Exception(str(e)),
                    context={"state": state, "workflow_id": workflow_id}
                )

                logger.warning(f"Applied graceful degradation: {degradation_result.get('strategy')}")

                return {
                    "final_context_items": [],
                    "degradation_result": degradation_result,
                    "workflow_metadata": {
                        "workflow_id": workflow_id,
                        "execution_time_seconds": execution_time,
                        "failed": True,
                        "error": str(e)
                    }
                }

            except Exception as degradation_error:
                logger.error(f"Graceful degradation failed: {degradation_error}")
                raise WorkflowExecutionError(
                    f"Workflow failed and degradation unsuccessful: {e}",
                    workflow_name="context_assembly",
                    execution_step=len(state["node_results"])
                ) from e

    async def _execute_workflow(self, state: WorkflowState) -> Dict[str, Any]:
        """Execute workflow nodes in sequence."""

        # Execute nodes in order
        for node_name in ["seed_analyzer", "candidate_enricher", "snippet_extractor", "context_ranker", "pack_assembler"]:
            node: BaseContextAssemblyNode = self.nodes[node_name]

            try:
                # Execute node with circuit breaker protection
                async with self.circuit_breaker:
                    node_result = await node.execute(state)

                # Record execution time
                if node_result.metrics:
                    state["node_execution_times"][node_name] = node_result.metrics.execution_time_seconds

                # Handle node result
                if node_result.success:
                    state["node_results"][node_name] = node_result.data

                    # Add any warnings
                    if node_result.warnings:
                        state["warnings"].extend(node_result.warnings)

                    logger.debug(f"Node {node_name} succeeded")

                else:
                    # Node failed - attempt recovery
                    state["error_count"] += 1

                    recovery_result = await self._handle_node_failure(
                        node_name, node_result.error, state
                    )

                    if recovery_result["recovered"]:
                        state["node_results"][node_name] = recovery_result["data"]
                        state["warnings"].append(f"Node {node_name} recovered with fallback")
                    else:
                        raise NodeExecutionError(
                            f"Node {node_name} failed and could not recover",
                            node_name=node_name,
                            input_data={"state_keys": list(state.keys())}
                        )

            except Exception as e:
                logger.error(f"Node {node_name} execution failed: {e}")
                state["error_count"] += 1

                # Try to recover
                recovery_result = await self._handle_node_failure(node_name, e, state)
                if recovery_result["recovered"]:
                    state["node_results"][node_name] = recovery_result["data"]
                    state["warnings"].append(f"Node {node_name} used fallback due to error")
                else:
                    raise

        # Return final result
        pack_assembler_result = state["node_results"].get("pack_assembler", {})

        return {
            "final_context_items": pack_assembler_result.get("final_context_items", []),
            "assembly_stats": pack_assembler_result.get("assembly_stats", {}),
            "validation_results": pack_assembler_result.get("validation_results", {}),
            "node_results": state["node_results"]
        }

    async def _handle_node_failure(
        self,
        node_name: str,
        error: Exception,
        state: WorkflowState
    ) -> Dict[str, Any]:
        """Handle individual node failures with appropriate fallbacks."""

        logger.warning(f"Handling failure in node {node_name}: {error}")

        # Node-specific fallback strategies
        fallback_strategies = {
            "seed_analyzer": self._fallback_seed_analyzer,
            "candidate_enricher": self._fallback_candidate_enricher,
            "snippet_extractor": self._fallback_snippet_extractor,
            "context_ranker": self._fallback_context_ranker,
            "pack_assembler": self._fallback_pack_assembler
        }

        fallback_handler = fallback_strategies.get(node_name)
        if fallback_handler:
            try:
                fallback_data = await fallback_handler(state, error)
                return {"recovered": True, "data": fallback_data}
            except Exception as fallback_error:
                logger.error(f"Fallback for {node_name} failed: {fallback_error}")

        return {"recovered": False, "data": {}}

    async def _fallback_seed_analyzer(self, state: WorkflowState, error: Exception) -> Dict[str, Any]:
        """Fallback for seed analyzer - use simple analysis."""
        seed_set = state["seed_set"]

        analyzed_seeds = []
        for seed in seed_set.seed_symbols:
            analyzed_seeds.append({
                "name": seed.name,
                "type": seed.type,
                "file_path": seed.file_path,
                "priority": 2,  # Medium priority
                "context_requirements": {"needs_callers": True, "max_hops": 1}
            })

        return {
            "analyzed_seeds": analyzed_seeds,
            "context_priorities": {seed.name: 2 for seed in seed_set.seed_symbols},
            "search_strategy": {"prioritize_changed_files": True},
            "fallback_used": True
        }

    async def _fallback_candidate_enricher(self, state: WorkflowState, error: Exception) -> Dict[str, Any]:
        """Fallback for candidate enricher - use original candidates."""
        kg_candidates = state.get("kg_candidates", {})
        candidates = kg_candidates.get("candidates", [])

        # Simple enrichment
        enriched_candidates = []
        for candidate in candidates:
            enriched = dict(candidate)
            enriched["is_seed_symbol"] = False
            enriched["priority"] = 3
            enriched_candidates.append(enriched)

        return {
            "expanded_candidates": enriched_candidates,
            "expansion_stats": {"candidates_processed": len(candidates)},
            "fallback_used": True
        }

    async def _fallback_snippet_extractor(self, state: WorkflowState, error: Exception) -> Dict[str, Any]:
        """Fallback for snippet extractor - use existing snippets."""
        enriched_candidates = state.get("node_results", {}).get("candidate_enricher", {}).get("enriched_candidates", [])

        extracted_items = []
        for candidate in enriched_candidates:
            if "code_snippet" in candidate:
                extracted_items.append(candidate)

        return {
            "extracted_items": extracted_items,
            "extraction_stats": {"snippets_extracted": len(extracted_items)},
            "fallback_used": True
        }

    async def _fallback_context_ranker(self, state: WorkflowState, error: Exception) -> Dict[str, Any]:
        """Fallback for context ranker - use simple ranking."""
        extracted_items = state.get("node_results", {}).get("snippet_extractor", {}).get("extracted_items", [])

        # Simple priority-based ranking
        ranked_items = sorted(
            extracted_items,
            key=lambda x: (
                x.get("is_seed_symbol", False),
                -x.get("priority", 5)
            ),
            reverse=True
        )

        # Assign simple relevance scores
        for i, item in enumerate(ranked_items):
            item["relevance_score"] = max(0.1, 1.0 - (i * 0.1))

        return {
            "ranked_items": ranked_items,
            "ranking_stats": {"items_final": len(ranked_items)},
            "fallback_used": True
        }

    async def _fallback_pack_assembler(self, state: WorkflowState, error: Exception) -> Dict[str, Any]:
        """Fallback for pack assembler - simple truncation."""
        ranked_items = state.get("node_results", {}).get("context_ranker", {}).get("ranked_items", [])
        limits = state["limits"]

        # Simple truncation to fit limits
        final_items = ranked_items[:limits.max_context_items]

        # Ensure character limit
        total_chars = 0
        bounded_items = []

        for item in final_items:
            snippet = item.get("code_snippet", "")
            if total_chars + len(snippet) <= limits.max_total_characters:
                bounded_items.append(item)
                total_chars += len(snippet)
            else:
                break

        return {
            "final_context_items": bounded_items,
            "assembly_stats": {
                "items_final": len(bounded_items),
                "total_characters": total_chars
            },
            "fallback_used": True
        }

    def get_metrics(self) -> Dict[str, Any]:
        """Get workflow metrics for monitoring."""
        return {
            "nodes": list(self.nodes.keys()),
            "timeout_seconds": self.timeout_seconds,
            "component_metrics": {
                "context_ranker": self.context_ranker.get_request_count(),
                "limits_enforcer": self.limits_enforcer.get_metrics()
            }
        }