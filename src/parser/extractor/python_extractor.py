"""
Python-specific symbol extractor using Tree-sitter.

This module implements symbol extraction for Python source files, handling:
  - Classes (class_definition)
  - Functions (function_definition)
  - Methods (function_definition inside class)
  - Decorated definitions (@decorator patterns)

Python's Tree-sitter grammar reference:
  https://github.com/tree-sitter/tree-sitter-python/blob/master/grammar.js
"""

from pathlib import Path

from tree_sitter import Node, Tree

from .base_extractor import ExtractedSymbol, SymbolExtractor
from .exceptions import SymbolExtractionError


class PythonSymbolExtractor(SymbolExtractor):
    """Python-specific symbol extractor using Tree-sitter queries.
    
    Extracts:
      - Classes (class_definition)
      - Functions (function_definition)
      - Methods (function_definition inside class)
      - Decorated definitions (@decorator patterns)
      
    Tree-sitter node types used:
      - class_definition: `class Foo:` or `class Foo(Bar):`
      - function_definition: `def foo():` or `async def foo():`
      - block: The indented body of compound statements
      - expression_statement: Container for standalone expressions (including docstrings)
      - string: String literal (used for docstrings)
      - identifier: Name node (class name, function name)
    """
    
    @property
    def language(self) -> str:
        return "python"
    
    # Tree-sitter query for Python definitions (for reference, using manual walk instead)
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
            self._walk_for_definitions(
                node=tree.root_node,
                content=file_content,
                symbols=symbols,
                depth=0,
                max_depth=self.DEFAULT_MAX_DEPTH,
                parent_class=None,
            )
            
            # Sort by position for consistent ordering
            symbols.sort(key=lambda s: (s.start_line, -s.end_line))
            
            return symbols
            
        except SymbolExtractionError:
            # Re-raise our own exceptions
            raise
        except Exception as e:
            raise SymbolExtractionError(
                f"Failed to extract Python symbols: {e}",
                language="python",
                file_path=str(file_path),
            ) from e
    
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
          
          Additionally, we enforce a maximum recursion depth to prevent stack overflow
          on deeply nested or malformed ASTs.
        
        Args:
            node: Current Tree-sitter Node being processed
            content: Raw file content as bytes (for extracting text)
            symbols: Accumulator list to append extracted symbols to
            depth: Current recursion depth
            max_depth: Maximum recursion depth allowed
            parent_class: Name of containing class (for qualified name building), or None
            
        Raises:
            SymbolExtractionError: If recursion depth exceeded or other error
        """
        depth += 1
        if depth > max_depth:
            raise SymbolExtractionError(
                f"Recursion depth exceeded: {depth} > {max_depth}",
                language="python",
            )
        
        # Handle class definition
        if node.type == "class_definition":
            symbol = self._extract_class(node, content, parent_class)
            if symbol:
                symbols.append(symbol)
                # Recurse into class body to find methods
                # The "block" child contains the class body (indented statements)
                for child in node.children:
                    if child.type == "block":
                        self._walk_for_definitions(
                            child, content, symbols,
                            depth, max_depth,
                            parent_class=symbol.name,
                        )
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
            self._walk_for_definitions(
                child, content, symbols,
                depth, max_depth,
                parent_class,
            )
    
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
        """Extract a function or method definition.
        
        Args:
            node: The function_definition Tree-sitter Node
            content: Raw file content as bytes
            parent_class: Name of containing class if this is a method, else None
            
        Returns:
            ExtractedSymbol for the function/method, or None if extraction failed
        """
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
        """Extract the signature line(s) for a definition.
        
        For multi-line signatures (e.g., long parameter lists), this method
        attempts to capture all lines up to the closing parenthesis and colon.
        
        Args:
            node: The definition node (class or function)
            content: Raw file content as bytes
            
        Returns:
            The signature string, stripped of leading/trailing whitespace
        """
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
          
        Args:
            node: The definition node (class or function)
            content: Raw file content as bytes
            
        Returns:
            The docstring content (without quotes), or None if no docstring
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
