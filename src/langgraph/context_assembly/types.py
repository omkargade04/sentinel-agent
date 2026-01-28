"""
Shared types for the LangGraph context assembly workflow.

This module contains type definitions used across multiple modules to avoid circular imports.
"""

from datetime import datetime
from typing import Dict, List, Any, Optional, TypedDict
from dataclasses import dataclass, field

from src.models.schemas.pr_review.context_pack import ContextPackLimits
from src.models.schemas.pr_review.seed_set import SeedSetS0
from src.models.schemas.pr_review.pr_patch import PRFilePatch


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
    clone_path: Optional[str]

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
