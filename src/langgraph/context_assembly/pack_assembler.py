from src.langgraph.context_assembly.base_node import BaseContextAssemblyNode
from src.langgraph.context_assembly.hard_limits_enforcer import HardLimitsEnforcer
from src.langgraph.context_assembly.types import WorkflowState
from typing import Dict, Any
from src.utils.logging import get_logger

class PackAssemblerNode(BaseContextAssemblyNode):
    """Node that applies hard limits and builds final context pack."""

    def __init__(self, limits_enforcer: HardLimitsEnforcer):
        super().__init__("pack_assembler")
        self.limits_enforcer = limits_enforcer
        self.logger = get_logger(__name__)

    async def _execute_node_logic(self, state: WorkflowState) -> Dict[str, Any]:
        """Apply hard limits and assemble final context pack."""
        ranked_items = state.get("node_results", {}).get("context_ranker", {}).get("ranked_items", [])
        limits = state["limits"]
        seed_set = state.get("seed_set")

        # Apply hard limits
        self.logger.info(f"Applying hard limits to {len(ranked_items)} items")

        final_items = self.limits_enforcer.apply_limits(ranked_items, limits)
        
        # Ensure minimum context: if final_items is empty but seed symbols exist, include at least seed symbol
        if len(final_items) == 0 and seed_set and len(seed_set.seed_symbols) > 0:
            self.logger.warning(
                f"[PACK_ASSEMBLER] Final items is empty but {len(seed_set.seed_symbols)} seed symbols exist. "
                f"Ensuring minimum context by including seed symbol code."
            )
            
            # Find seed symbol items in ranked_items (they should be there)
            seed_items = [
                item for item in ranked_items
                if item.get("is_seed_symbol", False) or 
                   any(symbol.name == item.get("symbol_name") for symbol in seed_set.seed_symbols)
            ]
            
            if seed_items:
                # Take the first seed symbol item
                final_items = [seed_items[0]]
                self.logger.info(
                    f"[PACK_ASSEMBLER] Added seed symbol item to ensure minimum context: "
                    f"{final_items[0].get('symbol_name', 'unknown')}"
                )
            else:
                self.logger.warning(
                    f"[PACK_ASSEMBLER] No seed symbol items found in ranked_items. "
                    f"Context pack will be empty."
                )

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

