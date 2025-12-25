"""
Symbol extraction from Tree-sitter ASTs.

This module provides an abstract interface for extracting code symbols (functions, classes,
methods, etc.) from Tree-sitter syntax trees, along with language-specific implementations.

The key insight is:
  1. File -> Symbols: Each file produces multiple SymbolNode objects
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
    grammar files for each language. For Python, see:
    https://github.com/tree-sitter/tree-sitter-python/blob/master/src/grammar.json

Usage:
    extractor = get_symbol_extractor("python")
    symbols = extractor.extract_symbols(tree, file_path, file_content)
    hierarchy = extractor.build_symbol_hierarchy(symbols)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
from tree_sitter import Node, Tree


class SymbolExtractionError(Exception):
    """Exception raised when symbol extraction fails."""
    pass


class HierarchyBuildError(Exception):
    """Exception raised when building symbol hierarchy fails."""
    pass


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
    tree_sitter_node: Node | None = None


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
    """
    
    @property
    @abstractmethod
    def language(self) -> str:
        """Return the language identifier (e.g., 'python', 'java')."""
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
            raise HierarchyBuildError(f"Failed to build symbol hierarchy: {e}") from e
    
    def _collect_node_types(self, node: Node) -> list[str]:
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
        
        def traverse(n: Node) -> None:
            types.append(n.type)
            for child in n.children:
                traverse(child)
        
        traverse(node)
        return types
    
    def _extract_text(self, content: bytes, start_byte: int, end_byte: int) -> str:
        """Extract text from content bytes."""
        return content[start_byte:end_byte].decode("utf-8", errors="replace")


class PythonSymbolExtractor(SymbolExtractor):
    """Python-specific symbol extractor using Tree-sitter queries.
    
    Extracts:
      - Classes (class_definition)
      - Functions (function_definition)
      - Methods (function_definition inside class)
      - Decorated definitions (@decorator patterns)
    """
    
    @property
    def language(self) -> str:
        return "python"
    
    # Tree-sitter query for Python definitions
    # This captures classes and functions with their names
    DEFINITION_QUERY = """
    (class_definition
      name: (identifier) @class.name) @class.def
      
    (function_definition
      name: (identifier) @function.name) @function.def
    """
    
    def extract_symbols(
        self,
        tree: Tree,
        file_path: Path,
        file_content: bytes,
    ) -> list[ExtractedSymbol]:
        """Extract Python symbols from the syntax tree.
        
        Args:
            tree: The Tree-sitter syntax tree (from parsing)
            file_path: Path to the source file (for context, not read here)
            file_content: Raw file content as bytes (required for extracting text spans)
            
        Returns:
            List of ExtractedSymbol objects, sorted by position
            
        Raises:
            SymbolExtractionError: If extraction fails
        """
        try:
            symbols: list[ExtractedSymbol] = []
            
            # Walk the tree to find definitions
            self._walk_for_definitions(tree.root_node, file_content, symbols, parent_class=None)
            
            # Sort by position for consistent ordering
            symbols.sort(key=lambda s: (s.start_line, -s.end_line))
            
            return symbols
        except Exception as e:
            raise SymbolExtractionError(f"Failed to extract Python symbols: {e}") from e
    
    def _walk_for_definitions(
        self,
        node: Node,
        content: bytes,
        symbols: list[ExtractedSymbol],
        depth: int,
        max_depth: int,
        parent_class: str | None,
    ) -> None:
        """Recursively walk the AST to find definitions.
        
        This method traverses the Tree-sitter AST in a depth-first manner, extracting
        class and function/method definitions into ExtractedSymbol objects.
        
        About the `node` parameter:
          The `Node` type is `tree_sitter.Node`, the Python binding to Tree-sitter's
          C library. Key attributes/methods:
            - node.type: Grammar node type string (e.g., "class_definition", "function_definition")
            - node.children: List of child Node objects
            - node.child_by_field_name(name): Get a named child (e.g., "name", "body")
            - node.start_point, node.end_point: (line, column) tuples (0-indexed)
            - node.start_byte, node.end_byte: Byte offsets in the source
        
        About "block" node type:
          In Python's Tree-sitter grammar, a "block" is the indented body of a compound
          statement (class, function, if, for, while, etc.). For example:
            ```
            class Foo:      # class_definition
                def bar():  # block contains this function_definition
                    pass
            ```
          When we find a class_definition, we look for its "block" child to find methods.
        
        Recursion exit condition:
          The recursion exits naturally when a node has no children to process. For leaf
          nodes (like identifiers, literals, etc.), node.children will be empty, and the
          `for child in node.children` loop simply won't iterate, returning control to
          the caller. The base case is implicitly: "no more children to visit".
        
        Args:
            node: Current Tree-sitter Node being processed
            content: Raw file content as bytes (for extracting text)
            symbols: Accumulator list to append extracted symbols to
            depth: Current recursion depth
            max_depth: Maximum recursion depth
            parent_class: Name of containing class (for qualified name building), or None
        """
        depth += 1
        if depth > max_depth:
          raise SymbolExtractionError(f"Recursion depth exceeded: {depth} > {max_depth}")
        # Handle class definition
        if node.type == "class_definition":
            symbol = self._extract_class(node, content, parent_class)
            if symbol:
                symbols.append(symbol)
                # Recurse into class body to find methods
                # The "block" child contains the class body (indented statements)
                for child in node.children:
                    if child.type == "block":
                        self._walk_for_definitions(child, content, symbols, parent_class=symbol.name)
            return
        
        # Handle function/method definition
        if node.type == "function_definition":
            symbol = self._extract_function(node, content, parent_class)
            if symbol:
                symbols.append(symbol)
            # Don't recurse into nested functions for now (can be added later)
            return
        
        # For all other node types, recurse into children
        # Exit condition: when node.children is empty, loop doesn't execute
        for child in node.children:
            self._walk_for_definitions(child, content, symbols, parent_class)
    
    def _extract_class(
        self,
        node: Node,
        content: bytes,
        parent_class: str | None,
    ) -> ExtractedSymbol | None:
        """Extract a class definition into an ExtractedSymbol.
        
        About child_by_field_name():
          Tree-sitter grammars define "field names" for certain child nodes to make them
          easily accessible. For example, in Python's grammar, class_definition has:
            - "name" field: the identifier node for the class name
            - "body" field: the block containing class contents
            - "superclasses" field: optional argument_list of base classes
          
          The method returns None if the field doesn't exist for this node.
          See: https://tree-sitter.github.io/tree-sitter/using-parsers#named-vs-anonymous-nodes
        
        Args:
            node: The class_definition Tree-sitter Node
            content: Raw file content as bytes
            parent_class: Name of outer class if this is a nested class, else None
            
        Returns:
            ExtractedSymbol for the class, or None if extraction failed
        """
        # Get the class name using the grammar's "name" field
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None
        
        name = self._extract_text(content, name_node.start_byte, name_node.end_byte)
        qualified_name = f"{parent_class}.{name}" if parent_class else name
        
        # Get signature (first line of class definition)
        signature = self._get_signature(node, content)
        
        # Get docstring if present
        docstring = self._get_docstring(node, content)
        
        # Collect node types for fingerprinting
        node_types = self._collect_node_types(node)
        
        return ExtractedSymbol(
            kind="class",
            name=name,
            qualified_name=qualified_name,
            start_line=node.start_point[0] + 1,  # Convert to 1-indexed
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            signature=signature,
            docstring=docstring,
            node_types=node_types,
            tree_sitter_node=node,
        )
    
    def _extract_function(
        self,
        node: Node,
        content: bytes,
        parent_class: str | None,
    ) -> ExtractedSymbol | None:
        """Extract a function or method definition."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None
        
        name = self._extract_text(content, name_node.start_byte, name_node.end_byte)
        
        # Determine kind based on context
        kind = "method" if parent_class else "function"
        qualified_name = f"{parent_class}.{name}" if parent_class else name
        
        # Get signature (function definition line)
        signature = self._get_signature(node, content)
        
        # Get docstring if present
        docstring = self._get_docstring(node, content)
        
        # Collect node types for fingerprinting
        node_types = self._collect_node_types(node)
        
        return ExtractedSymbol(
            kind=kind,
            name=name,
            qualified_name=qualified_name,
            start_line=node.start_point[0] + 1,  # Convert to 1-indexed
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            signature=signature,
            docstring=docstring,
            node_types=node_types,
            tree_sitter_node=node,
        )
    
    def _get_signature(self, node: Node, content: bytes) -> str:
        """Extract the signature line(s) for a definition."""
        # Get the first line of the definition
        start_line = node.start_point[0]
        lines = content.decode("utf-8", errors="replace").split("\n")
        
        if start_line < len(lines):
            sig_line = lines[start_line].strip()
            # For multi-line signatures, include continuation
            if sig_line.endswith("(") or sig_line.endswith(","):
                # Try to include more lines up to closing paren or colon
                sig_lines = [sig_line]
                for i in range(start_line + 1, min(start_line + 10, len(lines))):
                    line = lines[i].strip()
                    sig_lines.append(line)
                    if line.endswith(":") or "):" in line:
                        break
                return " ".join(sig_lines)
            return sig_line
        return ""
    
    def _get_docstring(self, node: Node, content: bytes) -> str | None:
        """Extract docstring from a class or function definition.
        
        About "expression_statement" type:
          In Python's Tree-sitter grammar, an "expression_statement" is a statement that
          consists of just an expression (no assignment, no control flow). This includes:
            - Standalone function calls: `print("hello")`
            - Docstrings: `"This is a docstring"`
            - Any expression used for side effects: `x + 1`
          
          In Python, a docstring is specifically a string literal that appears as the
          first statement in a class/function/module body. Tree-sitter represents this as:
            function_definition
              └── block
                  └── expression_statement  <-- container for the docstring
                      └── string  <-- the actual docstring content
          
          This node type definitely exists in Python's Tree-sitter grammar.
          See: https://github.com/tree-sitter/tree-sitter-python/blob/master/grammar.js
        """
        # In Python, docstring is the first expression statement in the body
        for child in node.children:
            if child.type == "block":
                for stmt in child.children:
                    if stmt.type == "expression_statement":
                        expr = stmt.children[0] if stmt.children else None
                        if expr and expr.type == "string":
                            docstring = self._extract_text(content, expr.start_byte, expr.end_byte)
                            # Strip quotes
                            if docstring.startswith('"""') or docstring.startswith("'''"):
                                return docstring[3:-3].strip()
                            elif docstring.startswith('"') or docstring.startswith("'"):
                                return docstring[1:-1].strip()
                            return docstring
                    # First non-string statement means no docstring
                    break
        return None


class JavaScriptSymbolExtractor(SymbolExtractor):
    """JavaScript/TypeScript symbol extractor.
    
    Extracts:
      - Classes (class_declaration)
      - Functions (function_declaration, arrow_function, method_definition)
      - Methods (method_definition inside class)
      
    Note: TypeScript uses the same basic AST structure for these constructs,
    so this extractor works for both languages. TypeScript-specific constructs
    like interfaces and type aliases can be added later.
    """
    
    @property
    def language(self) -> str:
        return "javascript"
    
    def extract_symbols(
        self,
        tree: Tree,
        file_path: Path,
        file_content: bytes,
    ) -> list[ExtractedSymbol]:
        """Extract JavaScript/TypeScript symbols from the syntax tree.
        
        Args:
            tree: The Tree-sitter syntax tree
            file_path: Path to the source file
            file_content: Raw file content as bytes
            
        Returns:
            List of ExtractedSymbol objects, sorted by position
            
        Raises:
            SymbolExtractionError: If extraction fails
        """
        try:
            symbols: list[ExtractedSymbol] = []
            self._walk_for_definitions(tree.root_node, file_content, symbols, parent_class=None)
            symbols.sort(key=lambda s: (s.start_line, -s.end_line))
            return symbols
        except Exception as e:
            raise SymbolExtractionError(f"Failed to extract JavaScript symbols: {e}") from e
    
    def _walk_for_definitions(
        self,
        node: Node,
        content: bytes,
        symbols: list[ExtractedSymbol],
        depth: int,
        max_depth: int,
        parent_class: str | None,
    ) -> None:
        """Recursively walk the AST to find definitions.
        
        JavaScript/TypeScript grammar node types handled:
          - class_declaration: ES6 class definition
          - function_declaration: Traditional function definition
          - method_definition: Method inside a class body
          - lexical_declaration: const/let declarations (for arrow functions)
          - variable_declaration: var declarations (for arrow functions)
          - variable_declarator: The individual binding in a declaration
          - arrow_function: Arrow function expression
        
        Args:
            node: Current Tree-sitter Node being processed
            content: Raw file content as bytes
            symbols: Accumulator list for extracted symbols
            depth: Current recursion depth
            max_depth: Maximum recursion depth
            parent_class: Name of containing class, or None
        """
        depth += 1
        if depth > max_depth:
          raise SymbolExtractionError(f"Recursion depth exceeded: {depth} > {max_depth}")
        # Handle class declaration
        if node.type == "class_declaration":
            symbol = self._extract_class(node, content, parent_class)
            if symbol:
                symbols.append(symbol)
                # Recurse into class body (class_body node)
                body = node.child_by_field_name("body")
                if body:
                    self._walk_for_definitions(body, content, symbols, parent_class=symbol.name)
            return
        
        # Handle function declaration and method definition
        if node.type in ("function_declaration", "method_definition"):
            symbol = self._extract_function(node, content, parent_class)
            if symbol:
                symbols.append(symbol)
            return
        
        # Handle variable declarations with arrow functions (const foo = () => {})
        if node.type in ("lexical_declaration", "variable_declaration"):
            for child in node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    value_node = child.child_by_field_name("value")
                    if name_node and value_node and value_node.type == "arrow_function":
                        symbol = self._extract_arrow_function(child, name_node, value_node, content)
                        if symbol:
                            symbols.append(symbol)
            return
        
        # Recurse into children for other node types
        for child in node.children:
            self._walk_for_definitions(child, content, symbols, parent_class)
    
    def _extract_class(
        self,
        node: Node,
        content: bytes,
        parent_class: str | None,
    ) -> ExtractedSymbol | None:
        """Extract a class declaration."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None
        
        name = self._extract_text(content, name_node.start_byte, name_node.end_byte)
        qualified_name = f"{parent_class}.{name}" if parent_class else name
        signature = self._get_first_line(node, content)
        node_types = self._collect_node_types(node)
        
        return ExtractedSymbol(
            kind="class",
            name=name,
            qualified_name=qualified_name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            signature=signature,
            node_types=node_types,
            tree_sitter_node=node,
        )
    
    def _extract_function(
        self,
        node: Node,
        content: bytes,
        parent_class: str | None,
    ) -> ExtractedSymbol | None:
        """Extract a function or method."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None
        
        name = self._extract_text(content, name_node.start_byte, name_node.end_byte)
        kind = "method" if parent_class or node.type == "method_definition" else "function"
        qualified_name = f"{parent_class}.{name}" if parent_class else name
        signature = self._get_first_line(node, content)
        node_types = self._collect_node_types(node)
        
        return ExtractedSymbol(
            kind=kind,
            name=name,
            qualified_name=qualified_name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            signature=signature,
            node_types=node_types,
            tree_sitter_node=node,
        )
    
    def _extract_arrow_function(
        self,
        declarator_node: Node,
        name_node: Node,
        arrow_node: Node,
        content: bytes,
    ) -> ExtractedSymbol | None:
        """Extract an arrow function assigned to a variable."""
        name = self._extract_text(content, name_node.start_byte, name_node.end_byte)
        signature = self._get_first_line(declarator_node, content)
        node_types = self._collect_node_types(arrow_node)
        
        return ExtractedSymbol(
            kind="function",
            name=name,
            qualified_name=name,
            start_line=declarator_node.start_point[0] + 1,
            end_line=declarator_node.end_point[0] + 1,
            start_byte=declarator_node.start_byte,
            end_byte=declarator_node.end_byte,
            signature=signature,
            node_types=node_types,
            tree_sitter_node=arrow_node,
        )
    
    def _get_first_line(self, node: Node, content: bytes) -> str:
        """Get the first line of a node as signature."""
        start = node.start_byte
        # Find the end of first line
        text = content[start:].decode("utf-8", errors="replace")
        first_line = text.split("\n")[0] if text else ""
        return first_line.strip()


# Registry of language-specific extractors
_EXTRACTORS: dict[str, type[SymbolExtractor]] = {
    "python": PythonSymbolExtractor,
    "javascript": JavaScriptSymbolExtractor,
    "typescript": JavaScriptSymbolExtractor,  # TypeScript uses same extractor for basics
}


def get_symbol_extractor(language: str) -> SymbolExtractor | None:
    """Get a symbol extractor for the given language.
    
    Args:
        language: Language identifier (e.g., 'python', 'javascript')
        
    Returns:
        SymbolExtractor instance or None if language not supported
    """
    extractor_class = _EXTRACTORS.get(language)
    if extractor_class:
        return extractor_class()
    return None


def get_supported_languages() -> list[str]:
    """Get list of languages with symbol extraction support."""
    return list(_EXTRACTORS.keys())

