"""
Overlap Detector Service

Detects which code symbols (functions, classes, methods) overlap with 
changed lines from PR diff hunks. This is the core algorithm for 
transforming line-level changes into semantic symbol-level changes.
"""

from dataclasses import dataclass
from typing import List, Set, Dict, Tuple

from src.parser.extractor import ExtractedSymbol
from src.models.schemas.pr_review.pr_patch import PRHunk
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SymbolOverlap:
    """
    Represents a symbol that overlaps with one or more diff hunks.
    
    Attributes:
        symbol: The extracted symbol from AST parsing
        hunk_ids: List of hunk IDs that overlap with this symbol
        overlapping_lines: Set of line numbers where overlap occurs
        overlap_ratio: Fraction of symbol lines that are changed (0.0-1.0)
    """
    symbol: ExtractedSymbol
    hunk_ids: List[str]
    overlapping_lines: Set[int]
    overlap_ratio: float


class OverlapDetector:
    """
    Detects symbols that overlap with changed lines from diff hunks.
    
    The overlap algorithm:
    1. Build a mapping of line numbers to hunk IDs from all hunks
    2. For each symbol, check if any line in [start_line, end_line] 
       exists in the changed lines mapping
    3. Return symbols with their associated hunk IDs
    
    This enables:
    - Precise symbol-to-hunk mapping for diff anchoring
    - Filtering out symbols that weren't actually changed
    - Tracking which hunks affect which symbols
    """
    
    def __init__(self, min_overlap_ratio: float = 0.0):
        """
        Initialize the overlap detector.
        
        Args:
            min_overlap_ratio: Minimum fraction of symbol lines that must be 
                               changed to consider it an overlap (0.0 = any overlap)
        """
        self.min_overlap_ratio = min_overlap_ratio
        self.logger = get_logger(__name__)
    
    def find_overlapping_symbols(
        self,
        symbols: List[ExtractedSymbol],
        hunks: List[PRHunk]
    ) -> List[SymbolOverlap]:
        """
        Find all symbols that overlap with changed lines from hunks.
        
        Args:
            symbols: List of symbols extracted from AST parsing
            hunks: List of diff hunks with changed line information
            
        Returns:
            List of SymbolOverlap objects for symbols that overlap with changes
        """
        if not symbols or not hunks:
            return []
        
        # Build line-to-hunk mapping
        line_to_hunks = self._build_line_to_hunk_mapping(hunks)
        
        if not line_to_hunks:
            self.logger.debug("No changed lines found in hunks")
            return []
        
        # Find overlapping symbols
        overlaps = []
        for symbol in symbols:
            overlap = self._check_symbol_overlap(symbol, line_to_hunks)
            if overlap:
                overlaps.append(overlap)
        
        self.logger.debug(
            f"Found {len(overlaps)} overlapping symbols out of {len(symbols)} total"
        )
        
        return overlaps
    
    def _build_line_to_hunk_mapping(
        self, 
        hunks: List[PRHunk]
    ) -> Dict[int, Set[str]]:
        """
        Build a mapping from line numbers to the hunk IDs that change them.
        
        Args:
            hunks: List of diff hunks
            
        Returns:
            Dictionary mapping line number -> set of hunk IDs
        """
        line_to_hunks: Dict[int, Set[str]] = {}
        
        for hunk in hunks:
            for line_num in hunk.new_changed_lines:
                if line_num not in line_to_hunks:
                    line_to_hunks[line_num] = set()
                line_to_hunks[line_num].add(hunk.hunk_id)
        
        return line_to_hunks
    
    def _check_symbol_overlap(
        self,
        symbol: ExtractedSymbol,
        line_to_hunks: Dict[int, Set[str]]
    ) -> SymbolOverlap | None:
        """
        Check if a symbol overlaps with any changed lines.
        
        Args:
            symbol: The symbol to check
            line_to_hunks: Mapping from line numbers to hunk IDs
            
        Returns:
            SymbolOverlap if there's overlap, None otherwise
        """
        # Get the set of lines this symbol spans
        symbol_lines = set(range(symbol.start_line, symbol.end_line + 1))
        
        # Find intersection with changed lines
        changed_lines = set(line_to_hunks.keys())
        overlapping_lines = symbol_lines & changed_lines
        
        if not overlapping_lines:
            return None
        
        # Calculate overlap ratio
        symbol_line_count = len(symbol_lines)
        overlap_ratio = len(overlapping_lines) / symbol_line_count if symbol_line_count > 0 else 0.0
        
        # Apply minimum overlap threshold
        if overlap_ratio < self.min_overlap_ratio:
            return None
        
        # Collect all hunk IDs that overlap with this symbol
        hunk_ids: Set[str] = set()
        for line_num in overlapping_lines:
            hunk_ids.update(line_to_hunks[line_num])
        
        return SymbolOverlap(
            symbol=symbol,
            hunk_ids=sorted(list(hunk_ids)),  # Sort for deterministic output
            overlapping_lines=overlapping_lines,
            overlap_ratio=overlap_ratio
        )
    
    def get_changed_lines_from_hunks(self, hunks: List[PRHunk]) -> Set[int]:
        """
        Extract all changed line numbers from a list of hunks.
        
        Utility method for quick access to changed lines.
        
        Args:
            hunks: List of diff hunks
            
        Returns:
            Set of all changed line numbers
        """
        changed_lines: Set[int] = set()
        for hunk in hunks:
            changed_lines.update(hunk.new_changed_lines)
        return changed_lines


def find_symbols_for_file(
    symbols: List[ExtractedSymbol],
    hunks: List[PRHunk],
    min_overlap_ratio: float = 0.0
) -> List[SymbolOverlap]:
    """
    Convenience function to find overlapping symbols for a single file.
    
    Args:
        symbols: Symbols extracted from the file
        hunks: Hunks for the same file
        min_overlap_ratio: Minimum overlap ratio threshold
        
    Returns:
        List of SymbolOverlap objects
        
    Example:
        >>> symbols = extractor.extract_symbols(tree, path, content)
        >>> overlaps = find_symbols_for_file(symbols, patch.hunks)
        >>> for overlap in overlaps:
        ...     print(f"{overlap.symbol.name} overlaps with {overlap.hunk_ids}")
    """
    detector = OverlapDetector(min_overlap_ratio=min_overlap_ratio)
    return detector.find_overlapping_symbols(symbols, hunks)