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

class ContextAssemblyNode:
    """Base class for workflow nodes."""

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{name}")

    async def execute(self, state: WorkflowState) -> NodeResult:
        """Execute the node with error handling and metrics."""
        metrics = NodeMetrics(node_name=self.name)

        try:
            # Record input size
            metrics.input_size = self._calculate_state_size(state)

            # Execute node logic
            self.logger.info(f"Executing node: {self.name}")
            result_data = await self._execute_impl(state)

            # Record output size and complete metrics
            metrics.output_size = len(str(result_data))
            metrics.mark_complete()

            self.logger.info(
                f"Node {self.name} completed in {metrics.execution_time_seconds:.2f}s"
            )

            return NodeResult(
                success=True,
                data=result_data,
                metrics=metrics
            )

        except Exception as e:
            metrics.error_count = 1
            metrics.mark_complete()

            self.logger.error(f"Node {self.name} failed: {e}")

            return NodeResult(
                success=False,
                data={},
                metrics=metrics,
                error=e
            )

    async def _execute_impl(self, state: WorkflowState) -> Dict[str, Any]:
        """Implementation method to be overridden by subclasses."""
        raise NotImplementedError("Subclasses must implement _execute_impl")

    def _calculate_state_size(self, state: WorkflowState) -> int:
        """Calculate approximate size of state for metrics."""
        try:
            return len(str(state))
        except:
            return 0


class SeedAnalyzerNode(ContextAssemblyNode):
    """Node that analyzes seed symbols for context needs."""

    def __init__(self):
        super().__init__("seed_analyzer")

    async def _execute_impl(self, state: WorkflowState) -> Dict[str, Any]:
        """Analyze seed symbols and prepare context requirements."""
        seed_set = state["seed_set"]
        patches = state["patches"]

        # Analyze seed symbols
        analyzed_seeds = []
        context_priorities = {}

        for seed in seed_set.seed_symbols:
            # Determine priority based on symbol characteristics
            priority = self._calculate_seed_priority(seed, patches)
            context_requirements = self._determine_context_requirements(seed)

            analyzed_seed = {
                "name": seed.name,
                "type": seed.type,
                "file_path": seed.file_path,
                "priority": priority,
                "context_requirements": context_requirements,
                "analysis_metadata": {
                    "is_function": seed.type == "function",
                    "is_class": seed.type == "class",
                    "affected_by_patch": any(p.file_path == seed.file_path for p in patches),
                    "complexity_estimate": self._estimate_complexity(seed)
                }
            }

            analyzed_seeds.append(analyzed_seed)
            context_priorities[seed.name] = priority

        # Generate search strategy based on analysis
        search_strategy = self._generate_search_strategy(analyzed_seeds)

        return {
            "analyzed_seeds": analyzed_seeds,
            "context_priorities": context_priorities,
            "search_strategy": search_strategy,
            "analysis_summary": {
                "total_seeds": len(analyzed_seeds),
                "high_priority_seeds": len([s for s in analyzed_seeds if s["priority"] <= 2]),
                "functions_count": len([s for s in analyzed_seeds if s["type"] == "function"]),
                "classes_count": len([s for s in analyzed_seeds if s["type"] == "class"])
            }
        }

    def _calculate_seed_priority(self, seed, patches: List[PRFilePatch]) -> int:
        """Calculate priority for a seed symbol (1 = highest)."""
        priority = 3  # Default medium priority

        # Higher priority for symbols in changed files
        if any(patch.file_path == seed.file_path for patch in patches):
            priority = min(priority, 1)

        # Higher priority for functions and classes
        if seed.type in ["function", "method", "class"]:
            priority = min(priority, 2)

        return priority

    def _determine_context_requirements(self, seed) -> Dict[str, Any]:
        """Determine what kind of context is needed for this seed."""
        requirements = {
            "needs_callers": seed.type in ["function", "method"],
            "needs_callees": seed.type in ["function", "method"],
            "needs_inheritance": seed.type == "class",
            "needs_usage_examples": True,
            "needs_dependencies": True,
            "max_hops": 2 if seed.type == "class" else 1
        }

        return requirements

    def _estimate_complexity(self, seed) -> str:
        """Estimate complexity of seed symbol."""
        # Simple heuristic based on symbol type
        complexity_map = {
            "function": "medium",
            "method": "medium",
            "class": "high",
            "variable": "low",
            "constant": "low"
        }

        return complexity_map.get(seed.type, "medium")

    def _generate_search_strategy(self, analyzed_seeds: List[Dict]) -> Dict[str, Any]:
        """Generate search strategy based on seed analysis."""
        high_priority_count = len([s for s in analyzed_seeds if s["priority"] <= 2])
        total_count = len(analyzed_seeds)

        return {
            "prioritize_changed_files": True,
            "expand_high_priority_seeds_first": high_priority_count > 0,
            "max_expansion_per_seed": 8 if total_count < 10 else 5,
            "prefer_direct_relationships": True,
            "include_test_files": total_count < 20  # Only if manageable
        }


class KGQuerierNode(ContextAssemblyNode):
    """Node that queries knowledge graph with intelligent expansion."""

    def __init__(self):
        super().__init__("kg_querier")

    async def _execute_impl(self, state: WorkflowState) -> Dict[str, Any]:
        """Query KG and expand context based on analysis."""
        kg_candidates = state.get("kg_candidates", {})
        analyzed_seeds = state.get("node_results", {}).get("seed_analyzer", {}).get("analyzed_seeds", [])
        search_strategy = state.get("node_results", {}).get("seed_analyzer", {}).get("search_strategy", {})

        # Process KG candidates with intelligent expansion
        expanded_candidates = []
        expansion_stats = {
            "candidates_processed": 0,
            "candidates_expanded": 0,
            "relationships_followed": 0
        }

        for candidate in kg_candidates.get("candidates", []):
            # Enrich candidate with seed priority
            enriched_candidate = self._enrich_with_seed_context(candidate, analyzed_seeds)

            # Apply expansion strategy
            if self._should_expand_candidate(enriched_candidate, search_strategy):
                expanded_candidate = await self._expand_candidate_context(enriched_candidate)
                expansion_stats["candidates_expanded"] += 1
            else:
                expanded_candidate = enriched_candidate

            expanded_candidates.append(expanded_candidate)
            expansion_stats["candidates_processed"] += 1

        # Sort by priority and relevance
        prioritized_candidates = self._prioritize_candidates(expanded_candidates)

        return {
            "expanded_candidates": prioritized_candidates,
            "expansion_stats": expansion_stats,
            "kg_metadata": kg_candidates.get("metadata", {}),
            "query_summary": {
                "total_candidates": len(prioritized_candidates),
                "high_priority": len([c for c in prioritized_candidates if c.get("priority", 5) <= 2]),
                "seed_related": len([c for c in prioritized_candidates if c.get("is_seed_symbol", False)]),
                "expanded": expansion_stats["candidates_expanded"]
            }
        }

    def _enrich_with_seed_context(self, candidate: Dict, analyzed_seeds: List[Dict]) -> Dict:
        """Enrich candidate with seed-specific context."""
        enriched = dict(candidate)

        # Find matching seed
        matching_seed = None
        for seed in analyzed_seeds:
            if seed["name"] == candidate.get("symbol_name"):
                matching_seed = seed
                break

        if matching_seed:
            enriched.update({
                "is_seed_symbol": True,
                "seed_priority": matching_seed["priority"],
                "context_requirements": matching_seed["context_requirements"],
                "seed_metadata": matching_seed["analysis_metadata"]
            })
        else:
            enriched.update({
                "is_seed_symbol": False,
                "seed_priority": 5,  # Low priority for non-seed symbols
                "relationship_distance": candidate.get("distance_from_seed", 2)
            })

        return enriched

    def _should_expand_candidate(self, candidate: Dict, strategy: Dict) -> bool:
        """Determine if candidate should be expanded with additional context."""
        # Always expand seed symbols
        if candidate.get("is_seed_symbol", False):
            return True

        # Expand high-priority candidates
        if candidate.get("priority", 5) <= 2:
            return True

        # Respect strategy limits
        max_expansions = strategy.get("max_expansion_per_seed", 5)
        current_expansions = candidate.get("expansion_count", 0)

        return current_expansions < max_expansions

    async def _expand_candidate_context(self, candidate: Dict) -> Dict:
        """Expand candidate with additional context information."""
        expanded = dict(candidate)

        # Add mock expansion (in real implementation, this would query KG)
        expanded["expansion_metadata"] = {
            "expanded_at": datetime.utcnow().isoformat(),
            "additional_relationships": ["calls", "used_by"],
            "context_snippets_added": 2
        }

        expanded["expansion_count"] = expanded.get("expansion_count", 0) + 1

        return expanded

    def _prioritize_candidates(self, candidates: List[Dict]) -> List[Dict]:
        """Prioritize candidates based on importance and relevance."""
        def priority_key(candidate):
            # Primary sort: seed symbols first
            is_seed = candidate.get("is_seed_symbol", False)

            # Secondary sort: priority level
            priority = candidate.get("priority", candidate.get("seed_priority", 5))

            # Tertiary sort: relationship strength
            rel_strength = candidate.get("relationship_strength", 0.0)

            return (not is_seed, priority, -rel_strength)

        return sorted(candidates, key=priority_key)


class SnippetExtractorNode(ContextAssemblyNode):
    """Node that extracts code snippets from PR head using cloned repository."""

    def __init__(self):
        super().__init__("snippet_extractor")
        # Initialize file snippet extractor
        from .file_snippet_extractor import FileSnippetExtractor
        self.file_extractor = FileSnippetExtractor(
            max_file_size_mb=5.0,  # Limit file size for performance
            max_line_length=5000,  # Limit line length to avoid memory issues
            encoding_detection_limit=4096
        )

    async def _execute_impl(self, state: WorkflowState) -> Dict[str, Any]:
        """Extract code snippets for context items using real file extraction."""
        expanded_candidates = state.get("node_results", {}).get("kg_querier", {}).get("expanded_candidates", [])
        patches = state["patches"]
        limits = state["limits"]
        clone_path = state.get("clone_path")

        extracted_items = []
        extraction_stats = {
            "candidates_processed": len(expanded_candidates),
            "snippets_extracted": 0,
            "snippets_truncated": 0,
            "extraction_errors": 0,
            "binary_files_skipped": 0,
            "file_not_found": 0
        }

        # Check if clone_path is available
        if not clone_path:
            self.logger.warning("No clone_path provided - falling back to mock extraction")
            return await self._fallback_mock_extraction(expanded_candidates, patches, limits, extraction_stats)

        self.logger.info(f"Extracting real code snippets from {len(expanded_candidates)} candidates using clone: {clone_path}")

        # Extract snippets using FileSnippetExtractor
        extraction_results = self.file_extractor.extract_multiple_snippets(
            clone_path=clone_path,
            candidates=expanded_candidates
        )

        # Process extraction results
        for i, (candidate, extraction_result) in enumerate(zip(expanded_candidates, extraction_results)):
            try:
                if extraction_result.extraction_success:
                    # Apply preliminary limits to extracted content
                    bounded_snippet = self._apply_snippet_limits(
                        {
                            "content": extraction_result.content,
                            "file_path": extraction_result.file_path,
                            "start_line": extraction_result.start_line,
                            "end_line": extraction_result.end_line,
                            "size": len(extraction_result.content)
                        },
                        limits.max_lines_per_snippet,
                        limits.max_chars_per_item
                    )

                    extracted_item = {
                        **candidate,
                        "code_snippet": bounded_snippet["content"],
                        "original_size": extraction_result.file_size_bytes,
                        "truncated": bounded_snippet["was_truncated"] or extraction_result.is_truncated,
                        "extraction_metadata": {
                            "extracted_at": datetime.utcnow().isoformat(),
                            "source": "clone_repository",
                            "line_count": extraction_result.actual_lines,
                            "encoding": extraction_result.encoding,
                            "actual_start_line": extraction_result.start_line,
                            "actual_end_line": extraction_result.end_line
                        }
                    }

                    extracted_items.append(extracted_item)
                    extraction_stats["snippets_extracted"] += 1

                    if bounded_snippet["was_truncated"] or extraction_result.is_truncated:
                        extraction_stats["snippets_truncated"] += 1

                else:
                    # Handle extraction errors
                    error_msg = extraction_result.extraction_error or "Unknown extraction error"
                    self.logger.debug(f"Failed to extract snippet for {candidate.get('symbol_name', 'unknown')}: {error_msg}")

                    # Categorize errors
                    if "not found" in error_msg.lower():
                        extraction_stats["file_not_found"] += 1
                    elif extraction_result.is_binary:
                        extraction_stats["binary_files_skipped"] += 1
                    else:
                        extraction_stats["extraction_errors"] += 1

            except Exception as e:
                self.logger.warning(f"Error processing extraction result {i}: {e}")
                extraction_stats["extraction_errors"] += 1
                continue

        # Log extraction summary
        success_rate = extraction_stats["snippets_extracted"] / max(extraction_stats["candidates_processed"], 1)
        self.logger.info(
            f"Real code extraction completed: {extraction_stats['snippets_extracted']}/{extraction_stats['candidates_processed']} "
            f"successful ({success_rate:.1%}), {extraction_stats['file_not_found']} files not found, "
            f"{extraction_stats['binary_files_skipped']} binary files skipped"
        )

        return {
            "extracted_items": extracted_items,
            "extraction_stats": extraction_stats,
            "quality_metrics": {
                "extraction_success_rate": success_rate,
                "truncation_rate": (
                    extraction_stats["snippets_truncated"] /
                    max(extraction_stats["snippets_extracted"], 1)
                ),
                "real_code_extraction": True,
                "clone_path_used": clone_path
            }
        }

    async def _fallback_mock_extraction(
        self,
        expanded_candidates: List[Dict],
        patches: List[PRFilePatch],
        limits,
        extraction_stats: Dict
    ) -> Dict[str, Any]:
        """Fallback to mock extraction when clone_path is not available."""
        extracted_items = []

        for candidate in expanded_candidates:
            try:
                # Generate mock code snippet (keep existing logic for backwards compatibility)
                snippet_data = await self._generate_mock_snippet(candidate, patches)

                if snippet_data:
                    # Apply preliminary limits
                    bounded_snippet = self._apply_snippet_limits(
                        snippet_data, limits.max_lines_per_snippet, limits.max_chars_per_item
                    )

                    extracted_item = {
                        **candidate,
                        "code_snippet": bounded_snippet["content"],
                        "original_size": bounded_snippet["original_size"],
                        "truncated": bounded_snippet["was_truncated"],
                        "extraction_metadata": {
                            "extracted_at": datetime.utcnow().isoformat(),
                            "source": "mock_generation",  # Indicate this is mock
                            "line_count": bounded_snippet["line_count"]
                        }
                    }

                    extracted_items.append(extracted_item)
                    extraction_stats["snippets_extracted"] += 1

                    if bounded_snippet["was_truncated"]:
                        extraction_stats["snippets_truncated"] += 1

            except Exception as e:
                self.logger.warning(f"Failed to generate mock snippet for {candidate.get('symbol_name', 'unknown')}: {e}")
                extraction_stats["extraction_errors"] += 1
                continue

        return {
            "extracted_items": extracted_items,
            "extraction_stats": extraction_stats,
            "quality_metrics": {
                "extraction_success_rate": (
                    extraction_stats["snippets_extracted"] /
                    max(extraction_stats["candidates_processed"], 1)
                ),
                "truncation_rate": (
                    extraction_stats["snippets_truncated"] /
                    max(extraction_stats["snippets_extracted"], 1)
                ),
                "real_code_extraction": False,  # Indicate this is mock
                "fallback_reason": "clone_path_unavailable"
            }
        }

    async def _generate_mock_snippet(self, candidate: Dict, patches: List[PRFilePatch]) -> Optional[Dict]:
        """Generate mock code snippet for backwards compatibility."""
        file_path = candidate.get("file_path", "")
        start_line = candidate.get("start_line", 1)
        end_line = candidate.get("end_line", start_line + 10)

        # Generate mock code snippet (existing logic)
        symbol_name = candidate.get("symbol_name", "unknown")
        symbol_type = candidate.get("symbol_type", "function")

        if symbol_type == "function":
            mock_snippet = f"""def {symbol_name}():
    \"\"\"Mock function for context assembly testing.\"\"\"
    # Implementation details would be here
    return None"""
        elif symbol_type == "class":
            mock_snippet = f"""class {symbol_name}:
    \"\"\"Mock class for context assembly testing.\"\"\"

    def __init__(self):
        pass

    def method_example(self):
        return None"""
        else:
            mock_snippet = f"# {symbol_type}: {symbol_name}\n# Mock code snippet"

        return {
            "content": mock_snippet,
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "size": len(mock_snippet)
        }

    def _apply_snippet_limits(self, snippet_data: Dict, max_lines: int, max_chars: int) -> Dict:
        """Apply size limits to extracted snippet."""
        content = snippet_data["content"]
        original_size = len(content)

        # Apply line limit
        lines = content.split('\n')
        if len(lines) > max_lines:
            content = '\n'.join(lines[:max_lines]) + '\n... [truncated] ...'

        # Apply character limit
        if len(content) > max_chars:
            content = content[:max_chars - 20] + '\n... [truncated] ...'

        return {
            "content": content,
            "original_size": original_size,
            "final_size": len(content),
            "was_truncated": len(content) < original_size,
            "line_count": len(content.split('\n'))
        }


class ContextRankerNode(ContextAssemblyNode):
    """Node that scores and prioritizes context items using rule-based ranking."""

    def __init__(self, context_ranker: Optional[RuleBasedContextRanker] = None):
        super().__init__("context_ranker")
        self.context_ranker = context_ranker or RuleBasedContextRanker()

    async def _execute_impl(self, state: WorkflowState) -> Dict[str, Any]:
        """Score and rank context items using rule-based approach."""
        extracted_items = state.get("node_results", {}).get("snippet_extractor", {}).get("extracted_items", [])
        seed_set = state["seed_set"]
        patches = state["patches"]

        self.logger.info(f"Scoring relevance for {len(extracted_items)} items")

        try:
            # Score using rule-based ranker (fast, free, deterministic)
            scored_items = self.context_ranker.score_relevance_batch(
                candidates=extracted_items,
                seed_set=seed_set,
                patches=patches
            )

            # Remove duplicates
            deduplicated_items = self.context_ranker.remove_duplicates(
                scored_items, similarity_threshold=0.85
            )

            # Sort by relevance score
            final_ranked_items = sorted(
                deduplicated_items,
                key=lambda x: (
                    x.get("relevance_score", 0.0),
                    x.get("is_seed_symbol", False),
                    -x.get("priority", 5)
                ),
                reverse=True
            )

            # Get scoring stats
            scoring_stats = self.context_ranker.get_scoring_stats(final_ranked_items)

            ranking_stats = {
                "items_input": len(extracted_items),
                "items_scored": len(scored_items),
                "items_after_dedup": len(deduplicated_items),
                "items_final": len(final_ranked_items),
                "avg_relevance_score": scoring_stats.get("avg_score", 0.0),
            }

            return {
                "ranked_items": final_ranked_items,
                "ranking_stats": ranking_stats,
                "quality_metrics": {
                    "deduplication_rate": (
                        (len(scored_items) - len(deduplicated_items)) /
                        max(len(scored_items), 1)
                    ),
                    "high_relevance_items": len([
                        item for item in final_ranked_items
                        if item.get("relevance_score", 0.0) >= 0.7
                    ])
                }
            }

        except Exception as e:
            self.logger.warning(f"Ranking failed, using simple fallback: {e}")

            fallback_items = self._simple_priority_ranking(extracted_items, seed_set, patches)

            return {
                "ranked_items": fallback_items,
                "ranking_stats": {
                    "items_input": len(extracted_items),
                    "items_final": len(fallback_items),
                    "fallback_used": True,
                },
                "warnings": ["Ranking failed, used simple priority fallback"]
            }

    def _simple_priority_ranking(
        self,
        items: List[Dict],
        seed_set: SeedSetS0,
        patches: List[PRFilePatch]
    ) -> List[Dict]:
        """Simple fallback ranking based on basic heuristics."""
        def simple_score(item):
            score = 0.0

            # Seed symbols get highest priority
            if item.get("is_seed_symbol", False):
                score += 0.8

            # Items in changed files get bonus
            if any(patch.file_path == item.get("file_path", "") for patch in patches):
                score += 0.6

            # Symbol type bonuses
            symbol_type = item.get("symbol_type", "")
            type_bonuses = {
                "function": 0.3,
                "method": 0.3,
                "class": 0.2,
                "variable": 0.1
            }
            score += type_bonuses.get(symbol_type, 0.0)

            # Distance penalty
            distance = item.get("distance_from_seed", 2)
            score += max(0, 0.2 - (distance * 0.05))

            return min(score, 1.0)

        # Apply simple scoring
        for item in items:
            item["relevance_score"] = simple_score(item)

        # Sort by score
        return sorted(items, key=lambda x: x.get("relevance_score", 0.0), reverse=True)


class PackAssemblerNode(ContextAssemblyNode):
    """Node that applies hard limits and builds final context pack."""

    def __init__(self, limits_enforcer: HardLimitsEnforcer):
        super().__init__("pack_assembler")
        self.limits_enforcer = limits_enforcer

    async def _execute_impl(self, state: WorkflowState) -> Dict[str, Any]:
        """Apply hard limits and assemble final context pack."""
        ranked_items = state.get("node_results", {}).get("context_ranker", {}).get("ranked_items", [])
        limits = state["limits"]

        # Apply hard limits
        self.logger.info(f"Applying hard limits to {len(ranked_items)} items")

        final_items = self.limits_enforcer.apply_limits(ranked_items, limits)

        # Calculate final statistics
        total_characters = sum(len(item.get("code_snippet", "")) for item in final_items)

        assembly_stats = {
            "items_input": len(ranked_items),
            "items_final": len(final_items),
            "total_characters": total_characters,
            "items_truncated": self.limits_enforcer.get_truncation_count(),
            "character_utilization": total_characters / limits.max_total_characters,
            "item_utilization": len(final_items) / limits.max_context_items
        }

        # Validate final pack
        try:
            self.limits_enforcer.validate_final_limits(final_items, limits)
            validation_passed = True
            validation_errors = []
        except Exception as e:
            validation_passed = False
            validation_errors = [str(e)]
            self.logger.error(f"Final validation failed: {e}")

        return {
            "final_context_items": final_items,
            "assembly_stats": assembly_stats,
            "validation_results": {
                "passed": validation_passed,
                "errors": validation_errors
            },
            "quality_metrics": {
                "context_coverage": len(final_items) / max(len(ranked_items), 1),
                "seed_symbol_coverage": len([
                    item for item in final_items
                    if item.get("is_seed_symbol", False)
                ]) / max(len([
                    item for item in ranked_items
                    if item.get("is_seed_symbol", False)
                ]), 1)
            }
        }


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
            "kg_querier": KGQuerierNode(),
            "snippet_extractor": SnippetExtractorNode(),
            "context_ranker": ContextRankerNode(self.context_ranker),
            "pack_assembler": PackAssemblerNode(self.limits_enforcer)
        }

        # Define workflow edges (execution order)
        self.workflow_edges = [
            ("seed_analyzer", "kg_querier"),
            ("kg_querier", "snippet_extractor"),
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
        for node_name in ["seed_analyzer", "kg_querier", "snippet_extractor", "context_ranker", "pack_assembler"]:
            node = self.nodes[node_name]

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
            "kg_querier": self._fallback_kg_querier,
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

    async def _fallback_kg_querier(self, state: WorkflowState, error: Exception) -> Dict[str, Any]:
        """Fallback for KG querier - use original candidates."""
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
        expanded_candidates = state.get("node_results", {}).get("kg_querier", {}).get("expanded_candidates", [])

        extracted_items = []
        for candidate in expanded_candidates:
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