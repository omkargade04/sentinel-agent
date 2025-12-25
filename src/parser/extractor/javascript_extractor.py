"""
JavaScript/TypeScript symbol extractor using Tree-sitter.

This module implements symbol extraction for JavaScript and TypeScript source files,
handling:
  - Classes (class_declaration)
  - Functions (function_declaration, arrow_function, method_definition)
  - Methods (method_definition inside class)
  - Arrow functions assigned to variables

Note: TypeScript uses the same basic AST structure for these constructs,
so this extractor works for both languages. TypeScript-specific constructs
like interfaces and type aliases can be added later.

JavaScript Tree-sitter grammar reference:
  https://github.com/tree-sitter/tree-sitter-javascript/blob/master/grammar.js
  
TypeScript Tree-sitter grammar reference:
  https://github.com/tree-sitter/tree-sitter-typescript/blob/master/grammar.js
"""

from pathlib import Path

from tree_sitter import Node, Tree

from .base_extractor import ExtractedSymbol, SymbolExtractor
from .exceptions import SymbolExtractionError


class JavaScriptSymbolExtractor(SymbolExtractor):
    """JavaScript/TypeScript symbol extractor.
    
    Extracts:
      - Classes (class_declaration)
      - Functions (function_declaration, arrow_function, method_definition)
      - Methods (method_definition inside class)
      
    Tree-sitter node types used:
      - class_declaration: `class Foo {}` or `class Foo extends Bar {}`
      - function_declaration: `function foo() {}`
      - method_definition: Method inside a class body
      - lexical_declaration: `const` or `let` declarations
      - variable_declaration: `var` declarations
      - variable_declarator: Individual binding in a declaration
      - arrow_function: `() => {}` or `x => x`
      - identifier: Name node
      - class_body: The `{}` part of a class containing methods
      
    Note: TypeScript uses the same basic AST structure for these constructs,
    so this extractor works for both languages.
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
            self._walk_for_definitions(
                node=tree.root_node,
                content=file_content,
                symbols=symbols,
                depth=0,
                max_depth=self.DEFAULT_MAX_DEPTH,
                parent_class=None,
            )
            symbols.sort(key=lambda s: (s.start_line, -s.end_line))
            return symbols
            
        except SymbolExtractionError:
            # Re-raise our own exceptions
            raise
        except Exception as e:
            raise SymbolExtractionError(
                f"Failed to extract JavaScript symbols: {e}",
                language="javascript",
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
        
        JavaScript/TypeScript grammar node types handled:
          - class_declaration: ES6 class definition
          - function_declaration: Traditional function definition
          - method_definition: Method inside a class body
          - lexical_declaration: const/let declarations (for arrow functions)
          - variable_declaration: var declarations (for arrow functions)
          - variable_declarator: The individual binding in a declaration
          - arrow_function: Arrow function expression
          
        Recursion exit condition:
          The recursion exits naturally when node.children is empty. Additionally,
          a maximum depth check prevents stack overflow on deeply nested or 
          malformed ASTs.
        
        Args:
            node: Current Tree-sitter Node being processed
            content: Raw file content as bytes
            symbols: Accumulator list for extracted symbols
            depth: Current recursion depth
            max_depth: Maximum recursion depth allowed
            parent_class: Name of containing class, or None
            
        Raises:
            SymbolExtractionError: If recursion depth exceeded
        """
        depth += 1
        if depth > max_depth:
            raise SymbolExtractionError(
                f"Recursion depth exceeded: {depth} > {max_depth}",
                language="javascript",
            )
        
        # Handle class declaration
        if node.type == "class_declaration":
            symbol = self._extract_class(node, content, parent_class)
            if symbol:
                symbols.append(symbol)
                # Recurse into class body (class_body node)
                body = node.child_by_field_name("body")
                if body:
                    self._walk_for_definitions(
                        body, content, symbols,
                        depth, max_depth,
                        parent_class=symbol.name,
                    )
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
        """Extract a class declaration.
        
        Args:
            node: The class_declaration Tree-sitter Node
            content: Raw file content as bytes
            parent_class: Name of outer class if nested, else None
            
        Returns:
            ExtractedSymbol for the class, or None if extraction failed
        """
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
        """Extract a function or method.
        
        Args:
            node: The function_declaration or method_definition Tree-sitter Node
            content: Raw file content as bytes
            parent_class: Name of containing class if this is a method, else None
            
        Returns:
            ExtractedSymbol for the function/method, or None if extraction failed
        """
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
        """Extract an arrow function assigned to a variable.
        
        This handles patterns like:
          - `const foo = () => {}`
          - `let bar = x => x * 2`
          - `var baz = (a, b) => a + b`
        
        Args:
            declarator_node: The variable_declarator Node
            name_node: The identifier Node for the variable name
            arrow_node: The arrow_function Node
            content: Raw file content as bytes
            
        Returns:
            ExtractedSymbol for the arrow function, or None if extraction failed
        """
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
        """Get the first line of a node as its signature.
        
        Args:
            node: The Tree-sitter Node
            content: Raw file content as bytes
            
        Returns:
            The first line of the node, stripped of whitespace
        """
        start = node.start_byte
        # Find the end of first line
        text = content[start:].decode("utf-8", errors="replace")
        first_line = text.split("\n")[0] if text else ""
        return first_line.strip()


class TypeScriptSymbolExtractor(JavaScriptSymbolExtractor):
    """TypeScript-specific symbol extractor.
    
    For basic constructs (classes, functions, methods), TypeScript uses the
    same AST structure as JavaScript, so we inherit from JavaScriptSymbolExtractor.
    
    TypeScript-specific constructs can be added here:
      - interface_declaration
      - type_alias_declaration
      - enum_declaration
      - namespace_declaration
      - module_declaration
    """
    
    @property
    def language(self) -> str:
        return "typescript"
    
    # TODO: Add TypeScript-specific extraction methods:
    # - _extract_interface()
    # - _extract_type_alias()
    # - _extract_enum()
