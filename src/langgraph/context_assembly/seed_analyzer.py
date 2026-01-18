from src.langgraph.context_assembly.base_node import BaseContextAssemblyNode
from src.langgraph.context_assembly.langgraph_workflow import NodeResult, WorkflowState
from typing import Dict, Any
import logging
from typing import Dict, List, Any

from src.models.schemas.pr_review.pr_patch import PRFilePatch

class SeedAnalyzerNode(BaseContextAssemblyNode):
    """Node that analyzes seed symbols for context needs."""

    def __init__(self):
        super().__init__("seed_analyzer")
        
    async def _execute_node_logic(self, state: WorkflowState) -> Dict[str, Any]:
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

