"""
Context Assembly Graph - Integration Layer

Provides interface for context assembly using rule-based ranking.
"""

import logging
from typing import List, Dict, Any, Optional

from .langgraph_workflow import ContextAssemblyWorkflow
from .circuit_breaker import CircuitBreaker
from .exceptions import ContextAssemblyError

logger = logging.getLogger(__name__)


class ContextAssemblyGraph:
    """
    Integration wrapper for context assembly workflow.
    
    Provides access to the rule-based context assembly pipeline.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize context assembly graph.

        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        self._workflow = None
        self._circuit_breaker = None

        self._initialize_components()

    def _initialize_components(self):
        """Initialize workflow components."""
        try:
            self._circuit_breaker = CircuitBreaker(
                failure_threshold=self.config.get('failure_threshold', 5),
                recovery_timeout=self.config.get('recovery_timeout', 60),
                name="context_assembly"
            )

            self._workflow = ContextAssemblyWorkflow(
                circuit_breaker=self._circuit_breaker,
                timeout_seconds=self.config.get('workflow_timeout', 300)
            )

            logger.info("Context assembly components initialized")

        except Exception as e:
            logger.error(f"Failed to initialize components: {e}")
            self._workflow = None

    async def assemble_context(
        self,
        seed_symbols: List[Dict],
        kg_candidates: List[Dict],
        pr_patches: List[Dict],
        clone_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Assemble bounded context pack from KG candidates.

        Args:
            seed_symbols: Seed symbols from PR analysis
            kg_candidates: Knowledge graph candidates
            pr_patches: PR file patches
            clone_path: Path to cloned repository for code extraction

        Returns:
            Dict with context_items and assembly statistics
        """
        if not self._workflow:
            logger.warning("Workflow not available, using fallback")
            return await self._fallback_assembly(seed_symbols, kg_candidates, pr_patches)

        try:
            from src.models.schemas.pr_review.seed_set import SeedSetS0, SeedSymbol
            from src.models.schemas.pr_review.pr_patch import PRFilePatch
            from src.models.schemas.pr_review.context_pack import ContextPackLimits

            seed_set = SeedSetS0(
                seed_symbols=[
                    SeedSymbol(
                        name=symbol.get('name', ''),
                        kind=symbol.get('kind', symbol.get('type', 'unknown')),
                        file_path=symbol.get('file_path', ''),
                        start_line=symbol.get('start_line', symbol.get('line_number', 1)),
                        end_line=symbol.get('end_line', symbol.get('start_line', symbol.get('line_number', 1))),
                        language=symbol.get('language', 'unknown'),
                        hunk_ids=symbol.get('hunk_ids', []),
                        qualified_name=symbol.get('qualified_name'),
                        signature=symbol.get('signature'),
                        docstring=symbol.get('docstring'),
                        fingerprint=symbol.get('fingerprint'),
                    ) for symbol in seed_symbols
                ],
                seed_files=[]
            )

            patches = [
                PRFilePatch(
                    file_path=patch.get('file_path', ''),
                    additions=patch.get('additions', 0),
                    deletions=patch.get('deletions', 0),
                    change_type=patch.get('change_type', 'modified'),
                    patch=patch.get('patch', ''),
                    hunks=patch.get('hunks', []),
                ) for patch in pr_patches
            ]

            limits = ContextPackLimits(
                max_context_items=self.config.get('max_context_items', 35),
                max_total_characters=self.config.get('max_total_characters', 120_000),
                max_lines_per_snippet=self.config.get('max_lines_per_snippet', 120),
                max_chars_per_item=self.config.get('max_chars_per_item', 2000),
                max_hops=self.config.get('max_hops', 1),
                max_neighbors_per_seed=self.config.get('max_neighbors_per_seed', 8)
            )

            result = await self._workflow.execute(
                seed_set=seed_set,
                kg_candidates={'candidates': kg_candidates},
                patches=patches,
                limits=limits,
                clone_path=clone_path
            )

            return {
                "context_items": self._convert_items_to_legacy_format(
                    result.get('final_context_items', [])
                ),
                "stats": {
                    "total_candidates": len(kg_candidates),
                    "selected_items": len(result.get('final_context_items', [])),
                    "total_characters": result.get('assembly_stats', {}).get('total_characters', 0),
                    "execution_time_seconds": result.get('workflow_metadata', {}).get('execution_time_seconds', 0),
                    "items_truncated": result.get('assembly_stats', {}).get('items_truncated', 0),
                },
                "workflow_metadata": result.get('workflow_metadata', {}),
                "quality_metrics": self._extract_quality_metrics(result)
            }

        except ContextAssemblyError as e:
            logger.error(f"Context assembly failed: {e}")
            return await self._fallback_assembly(seed_symbols, kg_candidates, pr_patches)

        except Exception as e:
            logger.error(f"Unexpected error in context assembly: {e}")
            return await self._fallback_assembly(seed_symbols, kg_candidates, pr_patches)

    async def _fallback_assembly(
        self,
        seed_symbols: List[Dict],
        kg_candidates: List[Dict],
        pr_patches: List[Dict]
    ) -> Dict[str, Any]:
        """Simple fallback implementation when workflow fails."""
        logger.info("Using fallback context assembly")

        max_items = self.config.get('max_context_items', 35)
        selected_items = []

        seed_names = {symbol.get('name') for symbol in seed_symbols}
        changed_files = {patch.get('file_path') for patch in pr_patches}

        for candidate in kg_candidates[:max_items * 2]:
            if len(selected_items) >= max_items:
                break

            is_seed = candidate.get('symbol_name') in seed_names
            in_changed_file = candidate.get('file_path') in changed_files

            if is_seed or in_changed_file or len(selected_items) < max_items // 2:
                context_item = {
                    "item_id": f"fallback_{len(selected_items)}",
                    "symbol_name": candidate.get('symbol_name', 'unknown'),
                    "file_path": candidate.get('file_path', ''),
                    "code_snippet": candidate.get('code_snippet', ''),
                    "relevance_score": 0.8 if is_seed else 0.6 if in_changed_file else 0.3,
                    "is_seed_symbol": is_seed,
                    "source": "fallback"
                }
                selected_items.append(context_item)

        total_chars = sum(len(item.get('code_snippet', '')) for item in selected_items)

        return {
            "context_items": selected_items,
            "stats": {
                "total_candidates": len(kg_candidates),
                "selected_items": len(selected_items),
                "total_characters": total_chars,
                "fallback_used": True,
            }
        }

    def _convert_items_to_legacy_format(self, context_items: List[Dict]) -> List[Dict]:
        """Convert context items to legacy format."""
        legacy_items = []

        for item in context_items:
            legacy_item = {
                "item_id": item.get('item_id', ''),
                "symbol_name": item.get('symbol_name', ''),
                "file_path": item.get('file_path', ''),
                "code_snippet": item.get('code_snippet', ''),
                "relevance_score": item.get('relevance_score', 0.0),
                "is_seed_symbol": item.get('is_seed_symbol', False),
                "priority": item.get('priority', 5),
                "source": item.get('source', 'unknown'),
                "truncated": item.get('truncated', False),
            }
            legacy_items.append(legacy_item)

        return legacy_items

    def _extract_quality_metrics(self, result: Dict) -> Dict[str, Any]:
        """Extract quality metrics from workflow result."""
        node_results = result.get('node_results', {})

        return {
            "seed_analysis_quality": len(node_results.get('seed_analyzer', {}).get('analyzed_seeds', [])),
            "kg_expansion_success": node_results.get('candidate_enricher', {}).get('expansion_stats', {}).get('candidates_expanded', 0),
            "extraction_success_rate": node_results.get('snippet_extractor', {}).get('quality_metrics', {}).get('extraction_success_rate', 0.0),
            "deduplication_rate": node_results.get('context_ranker', {}).get('quality_metrics', {}).get('deduplication_rate', 0.0),
            "context_coverage": node_results.get('pack_assembler', {}).get('quality_metrics', {}).get('context_coverage', 0.0),
            "validation_passed": node_results.get('pack_assembler', {}).get('validation_results', {}).get('passed', False),
        }

    def get_metrics(self) -> Dict[str, Any]:
        """Get metrics for monitoring."""
        metrics = {
            "workflow_available": self._workflow is not None,
            "config": self.config
        }

        if self._workflow:
            metrics["workflow_metrics"] = self._workflow.get_metrics()

        if self._circuit_breaker:
            metrics["circuit_breaker"] = self._circuit_breaker.get_metrics()

        return metrics

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on context assembly system."""
        health = {
            "status": "healthy",
            "components": {}
        }

        if self._circuit_breaker:
            cb_health = self._circuit_breaker.health_check()
            health["components"]["circuit_breaker"] = cb_health
            if cb_health["status"] != "healthy":
                health["status"] = "degraded"

        health["components"]["workflow"] = {
            "status": "healthy" if self._workflow else "unavailable"
        }

        return health
