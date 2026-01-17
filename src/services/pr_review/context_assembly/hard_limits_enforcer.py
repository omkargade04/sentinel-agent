"""
Hard Limits Enforcer

Production-grade enforcement of strict resource limits for context assembly.
Implements intelligent truncation strategies, character counting, and resource allocation.
"""

import logging
import re
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum

from src.models.schemas.pr_review.context_pack import ContextPackLimits
from .exceptions import HardLimitsExceededError

logger = logging.getLogger(__name__)


class TruncationStrategy(Enum):
    """Strategies for truncating content when limits are exceeded."""
    MIDDLE_OUT = "middle_out"      # Keep beginning and end, truncate middle
    END_PRESERVE = "end_preserve"  # Keep beginning, truncate end
    SMART_BOUNDARY = "smart_boundary"  # Truncate at logical boundaries


@dataclass
class TruncationResult:
    """Result of content truncation operation."""
    original_content: str
    truncated_content: str
    original_size: int
    final_size: int
    truncation_point: int
    strategy_used: TruncationStrategy
    lines_removed: int = 0

    @property
    def was_truncated(self) -> bool:
        return self.original_size != self.final_size

    @property
    def compression_ratio(self) -> float:
        if self.original_size == 0:
            return 1.0
        return self.final_size / self.original_size


@dataclass
class ResourceAllocation:
    """Resource allocation tracking for context items."""
    allocated_items: int = 0
    allocated_characters: int = 0
    reserved_characters: int = 0  # Reserved for high-priority items
    remaining_items: int = 0
    remaining_characters: int = 0

    def can_allocate(self, item_characters: int) -> bool:
        """Check if resources can be allocated for an item."""
        return (
            self.remaining_items > 0 and
            self.remaining_characters >= item_characters
        )

    def allocate(self, item_characters: int) -> None:
        """Allocate resources for an item."""
        if not self.can_allocate(item_characters):
            raise HardLimitsExceededError(
                f"Cannot allocate {item_characters} chars: "
                f"{self.remaining_characters} remaining"
            )

        self.allocated_items += 1
        self.allocated_characters += item_characters
        self.remaining_items -= 1
        self.remaining_characters -= item_characters


class HardLimitsEnforcer:
    """
    Enforces strict resource limits with intelligent allocation strategies.

    Features:
    - Priority-based resource allocation
    - Smart truncation strategies
    - Character counting and line limit enforcement
    - Resource tracking and metrics
    """

    def __init__(self):
        # Tracking
        self._truncation_count = 0
        self._total_characters_removed = 0
        self._items_rejected = 0

        # Strategy configuration
        self.truncation_strategies = {
            "function": TruncationStrategy.SMART_BOUNDARY,
            "class": TruncationStrategy.SMART_BOUNDARY,
            "method": TruncationStrategy.END_PRESERVE,
            "variable": TruncationStrategy.END_PRESERVE,
            "comment": TruncationStrategy.MIDDLE_OUT,
            "default": TruncationStrategy.MIDDLE_OUT
        }

        logger.info("Initialized HardLimitsEnforcer with smart truncation strategies")

    def apply_limits(
        self,
        candidates: List[Dict[str, Any]],
        limits: ContextPackLimits
    ) -> List[Dict[str, Any]]:
        """
        Apply hard limits to context candidates with intelligent allocation.

        Args:
            candidates: List of context candidates (sorted by priority/relevance)
            limits: Hard limits to enforce

        Returns:
            List of candidates that fit within limits (possibly truncated)
        """
        try:
            logger.info(
                f"Applying hard limits: {limits.max_context_items} items, "
                f"{limits.max_total_characters:,} chars"
            )

            # Initialize resource allocation
            allocation = ResourceAllocation(
                remaining_items=limits.max_context_items,
                remaining_characters=limits.max_total_characters
            )

            # Reserve some resources for high-priority items
            self._reserve_resources_for_priority(allocation, candidates, limits)

            # Process candidates in priority order
            selected_candidates = []

            for i, candidate in enumerate(candidates):
                try:
                    # Apply per-item limits first
                    bounded_candidate = self._apply_item_limits(candidate, limits)

                    # Check if candidate fits in remaining allocation
                    candidate_size = len(bounded_candidate.get('code_snippet', ''))

                    if not allocation.can_allocate(candidate_size):
                        logger.debug(
                            f"Rejecting candidate {i+1}: {candidate_size} chars "
                            f"exceeds remaining {allocation.remaining_characters}"
                        )
                        self._items_rejected += 1
                        continue

                    # Allocate resources and add candidate
                    allocation.allocate(candidate_size)
                    selected_candidates.append(bounded_candidate)

                    logger.debug(
                        f"Selected candidate {i+1}: {candidate.get('symbol_name')} "
                        f"({candidate_size} chars, {allocation.remaining_items} items left)"
                    )

                except Exception as e:
                    logger.warning(f"Failed to process candidate {i+1}: {e}")
                    continue

            logger.info(
                f"Hard limits applied: {len(selected_candidates)}/{len(candidates)} items, "
                f"{allocation.allocated_characters:,} chars, "
                f"{self._truncation_count} truncated"
            )

            return selected_candidates

        except Exception as e:
            logger.error(f"Failed to apply hard limits: {e}")
            raise HardLimitsExceededError(f"Limit enforcement failed: {e}") from e

    def _reserve_resources_for_priority(
        self,
        allocation: ResourceAllocation,
        candidates: List[Dict[str, Any]],
        limits: ContextPackLimits
    ) -> None:
        """Reserve resources for high-priority items."""
        high_priority_candidates = [
            candidate for candidate in candidates[:10]  # Top 10 only
            if candidate.get('priority', 5) <= 2  # High priority
        ]

        if not high_priority_candidates:
            return

        # Reserve 30% of character budget for high-priority items
        reserved_chars = int(limits.max_total_characters * 0.3)
        allocation.reserved_characters = min(reserved_chars, allocation.remaining_characters)

        logger.debug(
            f"Reserved {allocation.reserved_characters:,} chars for "
            f"{len(high_priority_candidates)} high-priority items"
        )

    def _apply_item_limits(
        self,
        candidate: Dict[str, Any],
        limits: ContextPackLimits
    ) -> Dict[str, Any]:
        """Apply per-item limits (line count, character count)."""
        bounded = dict(candidate)  # Copy to avoid mutation

        code_snippet = candidate.get('code_snippet', '')
        if not code_snippet:
            return bounded

        original_size = len(code_snippet)

        # Apply line limit first
        line_limited_snippet = self._apply_line_limit(
            code_snippet, limits.max_lines_per_snippet
        )

        # Apply character limit
        char_limited_snippet = self._apply_character_limit(
            line_limited_snippet,
            limits.max_chars_per_item,
            candidate.get('symbol_type', 'default')
        )

        # Update candidate
        bounded['code_snippet'] = char_limited_snippet
        bounded['original_size'] = original_size
        bounded['truncated'] = len(char_limited_snippet) < original_size

        if bounded['truncated']:
            self._truncation_count += 1
            self._total_characters_removed += original_size - len(char_limited_snippet)

        return bounded

    def _apply_line_limit(self, content: str, max_lines: int) -> str:
        """Apply line count limit to content."""
        if max_lines <= 0:
            return content

        lines = content.split('\n')
        if len(lines) <= max_lines:
            return content

        # Keep first and last lines when truncating
        if max_lines <= 3:
            return '\n'.join(lines[:max_lines])

        # Smart truncation: keep beginning and end
        keep_start = max_lines // 2
        keep_end = max_lines - keep_start - 1  # -1 for truncation indicator

        truncated_lines = (
            lines[:keep_start] +
            ['... [truncated] ...'] +
            lines[-keep_end:] if keep_end > 0 else []
        )

        return '\n'.join(truncated_lines)

    def _apply_character_limit(
        self,
        content: str,
        max_chars: int,
        symbol_type: str
    ) -> str:
        """Apply character limit with smart truncation strategy."""
        if len(content) <= max_chars:
            return content

        # Select truncation strategy based on symbol type
        strategy = self.truncation_strategies.get(
            symbol_type, TruncationStrategy.MIDDLE_OUT
        )

        # Execute truncation
        truncation_result = self._truncate_content(content, max_chars, strategy)

        logger.debug(
            f"Truncated {symbol_type}: {truncation_result.original_size} -> "
            f"{truncation_result.final_size} chars using {strategy.value}"
        )

        return truncation_result.truncated_content

    def _truncate_content(
        self,
        content: str,
        max_chars: int,
        strategy: TruncationStrategy
    ) -> TruncationResult:
        """Truncate content using specified strategy."""
        if len(content) <= max_chars:
            return TruncationResult(
                original_content=content,
                truncated_content=content,
                original_size=len(content),
                final_size=len(content),
                truncation_point=0,
                strategy_used=strategy
            )

        truncation_marker = "\n... [truncated] ...\n"
        available_chars = max_chars - len(truncation_marker)

        if available_chars <= 0:
            # Extreme truncation
            return TruncationResult(
                original_content=content,
                truncated_content="[content too large]",
                original_size=len(content),
                final_size=len("[content too large]"),
                truncation_point=0,
                strategy_used=strategy
            )

        if strategy == TruncationStrategy.END_PRESERVE:
            truncated = content[:available_chars] + truncation_marker

        elif strategy == TruncationStrategy.MIDDLE_OUT:
            # Keep beginning and end
            keep_start = available_chars // 2
            keep_end = available_chars - keep_start

            start_part = content[:keep_start]
            end_part = content[-keep_end:] if keep_end > 0 else ""

            truncated = start_part + truncation_marker + end_part

        elif strategy == TruncationStrategy.SMART_BOUNDARY:
            truncated = self._truncate_at_boundary(content, available_chars)

        else:
            # Fallback
            truncated = content[:available_chars] + truncation_marker

        return TruncationResult(
            original_content=content,
            truncated_content=truncated,
            original_size=len(content),
            final_size=len(truncated),
            truncation_point=available_chars,
            strategy_used=strategy,
            lines_removed=content.count('\n') - truncated.count('\n')
        )

    def _truncate_at_boundary(self, content: str, max_chars: int) -> str:
        """Truncate at logical boundaries (function, class, etc.)."""
        # Find logical boundaries
        boundaries = self._find_logical_boundaries(content)

        if not boundaries:
            # Fallback to line boundary
            return self._truncate_at_line_boundary(content, max_chars)

        # Find best boundary within limit
        best_boundary = 0
        for boundary in boundaries:
            if boundary <= max_chars:
                best_boundary = boundary
            else:
                break

        if best_boundary == 0:
            return self._truncate_at_line_boundary(content, max_chars)

        return content[:best_boundary] + "\n... [truncated] ..."

    def _find_logical_boundaries(self, content: str) -> List[int]:
        """Find logical boundaries in code content."""
        boundaries = []

        # Function/method boundaries
        for match in re.finditer(r'^(def|function|class)\s+\w+', content, re.MULTILINE):
            boundaries.append(match.start())

        # Block comment boundaries
        for match in re.finditer(r'^#.*$|^//.*$|^/\*.*\*/$', content, re.MULTILINE):
            boundaries.append(match.start())

        # Empty line boundaries (natural breaks)
        for match in re.finditer(r'\n\s*\n', content):
            boundaries.append(match.end())

        return sorted(set(boundaries))

    def _truncate_at_line_boundary(self, content: str, max_chars: int) -> str:
        """Truncate at nearest line boundary."""
        if len(content) <= max_chars:
            return content

        # Find last complete line within limit
        truncate_point = max_chars
        while truncate_point > 0 and content[truncate_point] != '\n':
            truncate_point -= 1

        if truncate_point == 0:
            # No line break found, hard truncate
            return content[:max_chars - 20] + "\n... [truncated] ..."

        return content[:truncate_point] + "\n... [truncated] ..."

    def validate_final_limits(
        self,
        context_items: List[Dict[str, Any]],
        limits: ContextPackLimits
    ) -> None:
        """Validate that final context pack respects all limits."""
        total_items = len(context_items)
        total_chars = sum(len(item.get('code_snippet', '')) for item in context_items)

        # Check item limit
        if total_items > limits.max_context_items:
            raise HardLimitsExceededError(
                f"Item count exceeded: {total_items} > {limits.max_context_items}"
            )

        # Check character limit
        if total_chars > limits.max_total_characters:
            raise HardLimitsExceededError(
                f"Character count exceeded: {total_chars:,} > {limits.max_total_characters:,}"
            )

        # Check per-item limits
        for i, item in enumerate(context_items):
            snippet = item.get('code_snippet', '')

            if len(snippet) > limits.max_chars_per_item:
                raise HardLimitsExceededError(
                    f"Item {i+1} exceeds character limit: "
                    f"{len(snippet)} > {limits.max_chars_per_item}"
                )

            line_count = snippet.count('\n') + 1 if snippet else 0
            if line_count > limits.max_lines_per_snippet:
                raise HardLimitsExceededError(
                    f"Item {i+1} exceeds line limit: "
                    f"{line_count} > {limits.max_lines_per_snippet}"
                )

        logger.info(f"Final limits validation passed: {total_items} items, {total_chars:,} chars")

    def estimate_resource_usage(
        self,
        candidates: List[Dict[str, Any]],
        limits: ContextPackLimits
    ) -> Dict[str, Any]:
        """Estimate resource usage without actually applying limits."""
        total_chars_raw = sum(
            len(candidate.get('code_snippet', '')) for candidate in candidates
        )

        estimated_truncations = 0
        estimated_final_chars = 0
        estimated_items = 0

        # Simulate allocation
        for candidate in candidates:
            if estimated_items >= limits.max_context_items:
                break

            snippet = candidate.get('code_snippet', '')
            char_count = len(snippet)

            # Estimate truncation
            if char_count > limits.max_chars_per_item:
                char_count = limits.max_chars_per_item
                estimated_truncations += 1

            if estimated_final_chars + char_count > limits.max_total_characters:
                # Would exceed total limit
                remaining_budget = limits.max_total_characters - estimated_final_chars
                if remaining_budget > 100:  # Minimum viable size
                    char_count = remaining_budget
                    estimated_truncations += 1
                else:
                    break  # Can't fit

            estimated_final_chars += char_count
            estimated_items += 1

        return {
            "candidates_total": len(candidates),
            "estimated_items_selected": estimated_items,
            "estimated_items_rejected": len(candidates) - estimated_items,
            "raw_characters": total_chars_raw,
            "estimated_final_characters": estimated_final_chars,
            "estimated_truncations": estimated_truncations,
            "estimated_compression_ratio": estimated_final_chars / max(total_chars_raw, 1),
            "fits_within_limits": (
                estimated_items <= limits.max_context_items and
                estimated_final_chars <= limits.max_total_characters
            )
        }

    def get_metrics(self) -> Dict[str, Any]:
        """Get enforcement metrics for monitoring."""
        return {
            "truncations_performed": self._truncation_count,
            "total_characters_removed": self._total_characters_removed,
            "items_rejected_by_limits": self._items_rejected,
            "truncation_strategies": {
                strategy.value: strategy.name for strategy in TruncationStrategy
            }
        }

    def get_truncation_count(self) -> int:
        """Get number of truncations performed."""
        return self._truncation_count

    def reset_metrics(self) -> None:
        """Reset internal metrics (for testing/monitoring)."""
        self._truncation_count = 0
        self._total_characters_removed = 0
        self._items_rejected = 0