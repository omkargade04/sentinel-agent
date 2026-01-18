
import logging
from datetime import datetime
from typing import Dict, List, Any

from src.langgraph.context_assembly.base_node import BaseContextAssemblyNode
from src.langgraph.context_assembly.langgraph_workflow import WorkflowState


class CandidateEnricherNode(BaseContextAssemblyNode):
    """Node that enriches KG candidates with seed context."""

    def __init__(self):
        super().__init__("candidate_enricher")

    async def _execute_node_logic(self, state: WorkflowState) -> Dict[str, Any]:
        """Enrich KG candidates with seed context."""
        kg_candidates = state.get("kg_candidates", {})
        analyzed_seeds = state.get("node_results", {}).get("seed_analyzer", {}).get("analyzed_seeds", [])
        # Remove: search_strategy (unused)

        enriched_candidates = []
        
        for candidate in kg_candidates.get("candidates", []):
            enriched_candidate = self._enrich_with_seed_context(candidate, analyzed_seeds)
            enriched_candidates.append(enriched_candidate)

        prioritized_candidates = self._prioritize_candidates(enriched_candidates)

        return {
            "enriched_candidates": prioritized_candidates,
            "stats": {
                "candidates_processed": len(prioritized_candidates),
                "high_priority_count": len([c for c in prioritized_candidates if c.get("priority", 5) <= 2]),
                "seed_symbols_count": len([c for c in prioritized_candidates if c.get("is_seed_symbol", False)]),
            },
            "kg_metadata": kg_candidates.get("metadata", {}),
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

