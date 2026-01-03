"""
Base symbol extractor interface and data models.

This module provides:
  - ExtractedSymbol: Intermediate representation of a code symbol
  - SymbolHierarchy: Parent-child relationship between symbols
  - SymbolExtractor: Abstract base class for language-specific extractors

The key insight is:
  1. File -> Symbols: Each file produces multiple ExtractedSymbol objects
  2. Hierarchical relationships: CONTAINS_SYMBOL edges for nested symbols
  3. Cross-references: CALLS and IMPORTS edges for semantic relationships
  4. No raw AST storage: Tree-sitter AST is used ephemerally for extraction

Key Design Decisions:
  - File content is passed as `bytes` (not `str`) because Tree-sitter is a C-based parser
    that operates on byte offsets. The `start_byte` and `end_byte` in Tree-sitter nodes
    are byte positions, not character positions. This is especially important for files
    containing multi-byte UTF-8 characters where byte offset != character offset.
  
  - The `Node` type used throughout is `tree_sitter.Node`, which is the 
    Python binding to Tree-sitter's C library. It provides methods like:
    - `child_by_field_name(name)`: Get a named child node
    - `children`: List of all child nodes
    - `type`: The grammar node type (e.g., "function_definition", "class_definition")
    - `start_point`, `end_point`: Line/column tuples
    - `start_byte`, `end_byte`: Byte offsets
  
  - AST node types like "block", "expression_statement", etc. are defined by Tree-sitter's
    grammar files for each language.

Usage:
    from src.parser.extractor import get_symbol_extractor
    
    extractor = get_symbol_extractor("python")
    symbols = extractor.extract_symbols(tree, file_path, file_content)
    hierarchy = extractor.build_symbol_hierarchy(symbols)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from tree_sitter import Tree

from .exceptions import HierarchyBuildError

# Use TYPE_CHECKING to avoid circular imports and for type hints only
if TYPE_CHECKING:
    from tree_sitter import Node


@dataclass
class ExtractedSymbol:
    """Represents a symbol extracted from source code.
    
    This is an intermediate representation before creating SymbolNode.
    It contains all the information needed to generate IDs and build graph nodes.
    
    Attributes:
        kind: The type of symbol (function, class, method, etc.)
        name: The symbol's name as it appears in code
        qualified_name: Best-effort fully qualified name (e.g., module.Class.method)
        start_line: 1-indexed inclusive start line
        end_line: 1-indexed inclusive end line
        start_byte: Byte offset for start position
        end_byte: Byte offset for end position
        signature: The declaration/signature line(s)
        docstring: Optional docstring or leading comment
        node_types: List of AST node types in pre-order traversal (for fingerprinting)
        parent_index: Index of parent symbol in the extraction list (-1 if top-level)
        tree_sitter_node: Reference to the original Tree-sitter node (ephemeral)
    """
    kind: str
    name: str
    qualified_name: str | None
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    signature: str
    docstring: str | None = None
    node_types: list[str] = field(default_factory=list)
    parent_index: int = -1
    tree_sitter_node: "Node | None" = None


@dataclass
class SymbolHierarchy:
    """Represents parent-child relationships between symbols.
    
    Used to generate CONTAINS_SYMBOL edges in the knowledge graph.
    
    Attributes:
        parent_index: Index of parent symbol in extraction list
        child_index: Index of child symbol in extraction list
    """
    parent_index: int
    child_index: int


class SymbolExtractor(ABC):
    """Abstract interface for language-specific symbol extraction.
    
    Each language implementation uses Tree-sitter queries tailored to that
    language's grammar to extract definition nodes (classes, functions, methods, etc.).
    
    Subclasses must implement:
      - language (property): Return the language identifier
      - extract_symbols(): Extract all symbols from a syntax tree
    
    The base class provides:
      - build_symbol_hierarchy(): Determine parent-child relationships
      - _collect_node_types(): Collect AST node types for fingerprinting
      - _extract_text(): Extract text from byte content
    """
    
    # Default maximum recursion depth for AST traversal
    DEFAULT_MAX_DEPTH: int = 100
    
    @property
    @abstractmethod
    def language(self) -> str:
        """Return the language identifier (e.g., 'python', 'javascript')."""
        pass
    
    @abstractmethod
    def extract_symbols(
        self,
        tree: Tree,
        file_path: Path,
        file_content: bytes,
    ) -> list[ExtractedSymbol]:
        """Extract all symbols from the given syntax tree.
        
        Args:
            tree: The Tree-sitter syntax tree
            file_path: Path to the source file (for context)
            file_content: Raw file content as bytes
            
        Returns:
            List of ExtractedSymbol objects, ordered by start position
            
        Raises:
            SymbolExtractionError: If extraction fails
        """
        pass
    
    def build_symbol_hierarchy(
        self,
        symbols: list[ExtractedSymbol],
    ) -> list[SymbolHierarchy]:
        """Determine parent-child relationships between symbols using span containment.
        
        Uses a span-stack algorithm:
          1. Sort symbols by (start_line ASC, end_line DESC) to ensure parents come before children
          2. Maintain a stack of currently open symbols
          3. For each symbol, pop stack until finding a parent that contains it
          4. If stack is non-empty, top of stack is the parent
        
        Why we use an indexed list for sorting:
          We need to preserve the original indices of symbols after sorting because the
          SymbolHierarchy result uses indices to reference parent-child relationships.
          If we sorted the list directly, we'd lose the mapping between sorted position
          and original position, making it impossible to correctly reference symbols.
          
        Why we store (index, symbol) tuples in the stack:
          The stack tracks "open" parent symbols. When we find a nested child, we need
          to know the ORIGINAL index of the parent (before sorting) so we can correctly
          build the SymbolHierarchy with parent_index and child_index that reference
          the original list positions.
          
        What "pop symbols that don't contain current symbol" means:
          As we process symbols in sorted order (parents before children), we maintain
          a stack of potential parent symbols. When we encounter a new symbol, we pop
          all symbols from the stack whose end_line is less than the current symbol's
          start_line or end_line — these symbols have "closed" and cannot be parents.
          
        Args:
            symbols: List of extracted symbols (will be sorted internally)
            
        Returns:
            List of SymbolHierarchy objects representing parent-child relationships
            
        Raises:
            HierarchyBuildError: If an error occurs while building the hierarchy
        """
        if not symbols:
            return []
        
        try:
            # Create indexed list for sorting while preserving original indices
            # Each element is (original_index, symbol) tuple
            indexed = list(enumerate(symbols))
            
            # Sort by (start_line ASC, end_line DESC):
            # - start_line ASC: parents appear before children (parents start earlier)
            # - end_line DESC: larger spans (parents) come before smaller spans (children) at same line
            indexed.sort(key=lambda x: (x[1].start_line, -x[1].end_line))
            
            hierarchy: list[SymbolHierarchy] = []
            # Stack contains tuples of (original_index, symbol) for tracking open parent scopes
            stack: list[tuple[int, ExtractedSymbol]] = []
            
            for original_idx, symbol in indexed:
                # Pop symbols from stack that have "closed" (their span doesn't contain us)
                # A parent contains a child if: parent.start <= child.start AND parent.end >= child.end
                while stack:
                    parent_idx, parent = stack[-1]
                    if parent.start_line <= symbol.start_line and parent.end_line >= symbol.end_line:
                        # Parent contains current symbol, keep it on stack
                        break
                    # Parent doesn't contain us, pop it (its scope has closed)
                    stack.pop()
                
                # If stack is non-empty, the top is our immediate parent
                if stack:
                    parent_idx, _ = stack[-1]
                    hierarchy.append(SymbolHierarchy(
                        parent_index=parent_idx,
                        child_index=original_idx,
                    ))
                    # Also update the symbol's parent_index for convenience
                    symbol.parent_index = parent_idx
                
                # Push current symbol onto stack as a potential parent for future symbols
                stack.append((original_idx, symbol))
            
            return hierarchy
            
        except Exception as e:
            raise HierarchyBuildError(
                f"Failed to build symbol hierarchy: {e}",
                symbol_count=len(symbols),
            ) from e
    
    def _collect_node_types(self, node: "Node") -> list[str]:
        """Collect all node types in pre-order traversal for fingerprinting.
        
        This creates an AST structure fingerprint that is resilient to:
          - Whitespace changes
          - Comment changes
          - Minor formatting differences
          
        Args:
            node: The Tree-sitter node to traverse
            
        Returns:
            List of node type strings in pre-order traversal
        """
        types: list[str] = []
        
        def traverse(n: "Node") -> None:
            types.append(n.type)
            for child in n.children:
                traverse(child)
        
        traverse(node)
        return types
    
    def _extract_text(self, content: bytes, start_byte: int, end_byte: int) -> str:
        """Extract text from content bytes.
        
        Args:
            content: Raw file content as bytes
            start_byte: Starting byte offset
            end_byte: Ending byte offset
            
        Returns:
            Decoded UTF-8 string from the byte range
        """
        return content[start_byte:end_byte].decode("utf-8", errors="replace")
