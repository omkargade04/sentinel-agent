
from src.langgraph.context_assembly.base_node import BaseContextAssemblyNode
from src.langgraph.context_assembly.langgraph_workflow import WorkflowState
from typing import Dict, List, Any, Optional

from src.langgraph.context_assembly.rule_based_ranker import RuleBasedContextRanker
from src.models.schemas.pr_review import PRFilePatch, SeedSetS0

class ContextRankerNode(BaseContextAssemblyNode):
    """Node that scores and prioritizes context items using rule-based ranking."""

    def __init__(self, context_ranker: Optional[RuleBasedContextRanker] = None):
        super().__init__("context_ranker")
        self.context_ranker = context_ranker or RuleBasedContextRanker()

    async def _execute_node_logic(self, state: WorkflowState) -> Dict[str, Any]:
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

