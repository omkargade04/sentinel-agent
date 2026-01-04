"""
JavaScript/TypeScript reference extractor using Tree-sitter.

This module extracts import statements and call sites from JS/TS source files.

Supported import patterns (ES6 modules):
  - `import x from 'y'`                   -> module_path="y", alias="x" (default import)
  - `import { A } from 'y'`               -> module_path="y", imported_names=["A"]
  - `import { A, B } from 'y'`            -> module_path="y", imported_names=["A", "B"]
  - `import { A as B } from 'y'`          -> module_path="y", imported_names=["A"], alias="B"
  - `import * as x from 'y'`              -> module_path="y", alias="x"
  - `import 'y'`                          -> module_path="y" (side-effect import)
  - `import x, { A } from 'y'`            -> module_path="y", alias="x", imported_names=["A"]

Supported import patterns (CommonJS):
  - `const x = require('y')`              -> module_path="y", alias="x"
  - `const { A } = require('y')`          -> module_path="y", imported_names=["A"]

Supported call patterns:
  - `foo()`                               -> callee_name="foo"
  - `obj.method()`                        -> callee_name="method", receiver="obj"
  - `a.b.c.method()`                      -> callee_name="method", receiver="a.b.c"
  - `new MyClass()`                       -> callee_name="MyClass", is_constructor=True
  - `new a.b.Class()`                     -> callee_name="Class", receiver="a.b", is_constructor=True

JavaScript Tree-sitter grammar reference:
  https://github.com/tree-sitter/tree-sitter-javascript/blob/master/grammar.js

TypeScript Tree-sitter grammar reference:
  https://github.com/tree-sitter/tree-sitter-typescript/blob/master/grammar.js

Note: TypeScript uses the same import/call syntax as JavaScript, so this
extractor works for both languages. TypeScript-specific constructs like
`import type` can be added later.

Key node types used:
  - import_statement: ES6 import declaration
  - import_clause: What's being imported (default, named, namespace)
  - named_imports: `{ A, B }` part
  - import_specifier: Individual named import
  - call_expression: Function/method call
  - new_expression: Constructor call with `new`
  - member_expression: `obj.property` access
  - identifier: Simple name
  - string: Import source path (with quotes)
"""

from tree_sitter import Node, Tree

from .base import CallSite, ExtractionResult, ImportReference, ReferenceExtractor


class JavaScriptReferenceExtractor(ReferenceExtractor):
    """JavaScript/TypeScript reference extractor.
    
    Extracts import references and call sites from JS/TS source files
    using Tree-sitter for parsing.
    
    Supports both ES6 module syntax and CommonJS require() calls.
    
    The extraction is done in a single AST traversal:
      1. Look for import_statement (ES6) and require() calls (CommonJS)
      2. Look for call_expression and new_expression
    """
    
    @property
    def language(self) -> str:
        return "javascript"
    
    def extract(
        self,
        tree: Tree,
        file_content: bytes,
    ) -> ExtractionResult:
        """Extract imports and call sites from JavaScript/TypeScript source.
        
        Args:
            tree: Tree-sitter syntax tree
            file_content: Raw file content as bytes
            
        Returns:
            ExtractionResult with imports and call_sites
        """
        result = ExtractionResult()
        
        # Single traversal to extract both imports and calls
        self._walk_tree(
            node=tree.root_node,
            content=file_content,
            result=result,
            depth=0,
        )
        
        return result
    
    # AST Traversal
    def _walk_tree(
        self,
        node: Node,
        content: bytes,
        result: ExtractionResult,
        depth: int,
    ) -> None:
        """Recursively walk the AST to extract references.
        
        Args:
            node: Current Tree-sitter node
            content: Raw file content as bytes
            result: Accumulator for extracted references
            depth: Current recursion depth
        """
        if depth > self.DEFAULT_MAX_DEPTH:
            return
        
        # Import Extraction
        
        # ES6 import: `import ... from '...'` or `import '...'`
        if node.type == "import_statement":
            import_ref = self._extract_import_statement(node, content)
            if import_ref:
                result.imports.append(import_ref)
            return  # Don't recurse into import statements
        
        # CommonJS require in variable declaration:
        # `const x = require('y')` or `const { A } = require('y')`
        if node.type in ("lexical_declaration", "variable_declaration"):
            import_ref = self._extract_require_declaration(node, content)
            if import_ref:
                result.imports.append(import_ref)
                return  # Skip this subtree if it was a require
        
        # Call Site Extraction
        
        # Constructor call: `new MyClass()`
        if node.type == "new_expression":
            call_site = self._extract_new_expression(node, content)
            if call_site:
                result.call_sites.append(call_site)
            # Continue recursing - new expressions can have nested calls
        
        # Function/method call: `foo()` or `obj.method()`
        elif node.type == "call_expression":
            # Skip require() calls - they're handled as imports
            if not self._is_require_call(node, content):
                call_site = self._extract_call_expression(node, content)
                if call_site:
                    result.call_sites.append(call_site)
            # Continue recursing - calls can be nested
        
        # Recurse into children
        for child in node.children:
            self._walk_tree(child, content, result, depth + 1)
    
    # Import Extraction Helpers
    
    def _extract_import_statement(
        self,
        node: Node,
        content: bytes,
    ) -> ImportReference | None:
        """Extract import reference from ES6 import statement.
        
        Handles various ES6 import forms:
          - `import x from 'y'`           (default import)
          - `import { A } from 'y'`       (named import)
          - `import { A as B } from 'y'`  (aliased named import)
          - `import * as x from 'y'`      (namespace import)
          - `import 'y'`                  (side-effect import)
          - `import x, { A } from 'y'`    (mixed)
        
        Tree-sitter structure for `import { A, B } from './utils'`:
          import_statement
            ├── import
            ├── import_clause
            │   └── named_imports
            │       ├── {
            │       ├── import_specifier
            │       │   └── identifier "A"
            │       ├── ,
            │       ├── import_specifier
            │       │   └── identifier "B"
            │       └── }
            ├── from
            └── string "'./utils'"
        
        Args:
            node: import_statement node
            content: Raw file content
            
        Returns:
            ImportReference, or None if extraction failed
        """
        line_number = node.start_point[0] + 1
        
        # Find the source string (module path)
        module_path: str | None = None
        for child in node.children:
            if child.type == "string":
                # Remove quotes from string literal
                raw = self._extract_text(content, child.start_byte, child.end_byte)
                module_path = raw.strip("'\"")
                break
        
        if not module_path:
            return None
        
        # Determine if relative import
        is_relative = module_path.startswith("./") or module_path.startswith("../")
        
        # Extract import clause (what's being imported)
        imported_names: list[str] = []
        default_alias: str | None = None
        namespace_alias: str | None = None
        
        import_clause = None
        for child in node.children:
            if child.type == "import_clause":
                import_clause = child
                break
        
        if import_clause:
            for child in import_clause.children:
                # Default import: `import x from '...'`
                if child.type == "identifier":
                    default_alias = self._extract_text(
                        content, child.start_byte, child.end_byte
                    )
                
                # Namespace import: `import * as x from '...'`
                elif child.type == "namespace_import":
                    # Structure: namespace_import -> *, as, identifier
                    for subchild in child.children:
                        if subchild.type == "identifier":
                            namespace_alias = self._extract_text(
                                content, subchild.start_byte, subchild.end_byte
                            )
                
                # Named imports: `import { A, B } from '...'`
                elif child.type == "named_imports":
                    for specifier in child.children:
                        if specifier.type == "import_specifier":
                            name, alias = self._extract_import_specifier(specifier, content)
                            if name:
                                imported_names.append(name)
                                # Note: We only track the last alias for simplicity
                                # Full alias tracking would need a more complex data model
        
        # Determine the alias to use
        # Priority: namespace_alias > default_alias
        alias = namespace_alias or default_alias
        
        return ImportReference(
            module_path=module_path,
            imported_names=imported_names,
            alias=alias,
            is_relative=is_relative,
            line_number=line_number,
        )
    
    def _extract_import_specifier(
        self,
        node: Node,
        content: bytes,
    ) -> tuple[str | None, str | None]:
        """Extract name and alias from an import specifier.
        
        Handles:
          - `A`       -> ("A", None)
          - `A as B`  -> ("A", "B")
        
        Tree-sitter structure for `A as B`:
          import_specifier
            ├── identifier "A"
            ├── as
            └── identifier "B"
        
        Args:
            node: import_specifier node
            content: Raw file content
            
        Returns:
            Tuple of (original_name, alias) where alias may be None
        """
        identifiers: list[str] = []
        
        for child in node.children:
            if child.type == "identifier":
                identifiers.append(
                    self._extract_text(content, child.start_byte, child.end_byte)
                )
        
        if len(identifiers) == 0:
            return None, None
        elif len(identifiers) == 1:
            return identifiers[0], None
        else:
            # First is original, second is alias
            return identifiers[0], identifiers[1]
    
    def _extract_require_declaration(
        self,
        node: Node,
        content: bytes,
    ) -> ImportReference | None:
        """Extract import reference from CommonJS require() in a declaration.
        
        Handles:
          - `const x = require('y')`       -> alias="x"
          - `const { A, B } = require('y')` -> imported_names=["A", "B"]
          - `let x = require('y')`
          - `var x = require('y')`
        
        Tree-sitter structure for `const x = require('./utils')`:
          lexical_declaration
            ├── const
            └── variable_declarator
                ├── identifier "x"
                ├── =
                └── call_expression
                    ├── identifier "require"
                    └── arguments
                        └── string "'./utils'"
        
        Args:
            node: lexical_declaration or variable_declaration node
            content: Raw file content
            
        Returns:
            ImportReference, or None if not a require() call
        """
        line_number = node.start_point[0] + 1
        
        # Find the variable_declarator child
        for declarator in node.children:
            if declarator.type != "variable_declarator":
                continue
            
            # Get the name/pattern being assigned to
            name_node = declarator.child_by_field_name("name")
            value_node = declarator.child_by_field_name("value")
            
            if not name_node or not value_node:
                continue
            
            # Check if value is a require() call
            if value_node.type != "call_expression":
                continue
            
            if not self._is_require_call(value_node, content):
                continue
            
            # Extract the module path from require arguments
            module_path = self._extract_require_argument(value_node, content)
            if not module_path:
                continue
            
            is_relative = module_path.startswith("./") or module_path.startswith("../")
            
            # Determine what's being imported
            imported_names: list[str] = []
            alias: str | None = None
            
            # Simple assignment: `const x = require(...)`
            if name_node.type == "identifier":
                alias = self._extract_text(content, name_node.start_byte, name_node.end_byte)
            
            # Destructuring: `const { A, B } = require(...)`
            elif name_node.type == "object_pattern":
                for child in name_node.children:
                    # shorthand_property_identifier_pattern: `{ A }` -> A
                    if child.type in ("shorthand_property_identifier", "shorthand_property_identifier_pattern"):
                        imported_names.append(
                            self._extract_text(content, child.start_byte, child.end_byte)
                        )
                    # pair_pattern: `{ A: B }` -> A aliased to B
                    elif child.type == "pair_pattern":
                        key = child.child_by_field_name("key")
                        if key:
                            imported_names.append(
                                self._extract_text(content, key.start_byte, key.end_byte)
                            )
            
            return ImportReference(
                module_path=module_path,
                imported_names=imported_names,
                alias=alias,
                is_relative=is_relative,
                line_number=line_number,
            )
        
        return None
    
    def _is_require_call(self, node: Node, content: bytes) -> bool:
        """Check if a call_expression is a require() call.
        
        Args:
            node: call_expression node
            content: Raw file content
            
        Returns:
            True if this is a require() call
        """
        if node.type != "call_expression":
            return False
        
        function_node = node.child_by_field_name("function")
        if not function_node or function_node.type != "identifier":
            return False
        
        name = self._extract_text(content, function_node.start_byte, function_node.end_byte)
        return name == "require"
    
    def _extract_require_argument(self, node: Node, content: bytes) -> str | None:
        """Extract the module path from a require() call.
        
        Args:
            node: call_expression node for require()
            content: Raw file content
            
        Returns:
            Module path string (without quotes), or None
        """
        args_node = node.child_by_field_name("arguments")
        if not args_node:
            return None
        
        for child in args_node.children:
            if child.type == "string":
                raw = self._extract_text(content, child.start_byte, child.end_byte)
                return raw.strip("'\"")
        
        return None
    
    # Call Extraction Helpers
    
    def _extract_call_expression(
        self,
        node: Node,
        content: bytes,
    ) -> CallSite | None:
        """Extract a call site from a call_expression node.
        
        Handles:
          - `foo()`                 -> callee_name="foo"
          - `obj.method()`          -> callee_name="method", receiver="obj"
          - `a.b.c()`               -> callee_name="c", receiver="a.b"
        
        Tree-sitter structure for `obj.method()`:
          call_expression
            ├── function: member_expression
            │   ├── object: identifier "obj"
            │   ├── .
            │   └── property: property_identifier "method"
            └── arguments: arguments (...)
        
        Args:
            node: call_expression node
            content: Raw file content
            
        Returns:
            CallSite, or None if extraction failed
        """
        line_number = node.start_point[0] + 1
        column = node.start_point[1]
        
        function_node = node.child_by_field_name("function")
        if not function_node:
            return None
        
        callee_name: str | None = None
        receiver: str | None = None
        
        # Simple call: `foo()`
        if function_node.type == "identifier":
            callee_name = self._extract_text(
                content, function_node.start_byte, function_node.end_byte
            )
        
        # Method call: `obj.method()`
        elif function_node.type == "member_expression":
            # Get the property (method name)
            property_node = function_node.child_by_field_name("property")
            if property_node:
                callee_name = self._extract_text(
                    content, property_node.start_byte, property_node.end_byte
                )
            
            # Get the object (receiver)
            object_node = function_node.child_by_field_name("object")
            if object_node:
                receiver = self._extract_text(
                    content, object_node.start_byte, object_node.end_byte
                )
        
        else:
            # Other callable expressions (subscript, IIFE, etc.) - skip
            return None
        
        if not callee_name:
            return None
        
        return CallSite(
            callee_name=callee_name,
            receiver=receiver,
            line_number=line_number,
            column=column,
            is_constructor=False,  # Regular calls, not constructors
        )
    
    def _extract_new_expression(
        self,
        node: Node,
        content: bytes,
    ) -> CallSite | None:
        """Extract a call site from a new_expression (constructor call).
        
        Handles:
          - `new MyClass()`         -> callee_name="MyClass", is_constructor=True
          - `new a.b.Class()`       -> callee_name="Class", receiver="a.b", is_constructor=True
        
        Tree-sitter structure for `new MyClass()`:
          new_expression
            ├── new
            ├── constructor: identifier "MyClass"
            └── arguments: arguments (...)
        
        Tree-sitter structure for `new a.b.Class()`:
          new_expression
            ├── new
            ├── constructor: member_expression
            │   ├── object: member_expression (a.b)
            │   └── property: property_identifier "Class"
            └── arguments: arguments (...)
        
        Args:
            node: new_expression node
            content: Raw file content
            
        Returns:
            CallSite, or None if extraction failed
        """
        line_number = node.start_point[0] + 1
        column = node.start_point[1]
        
        # Get the constructor being called
        constructor_node = node.child_by_field_name("constructor")
        if not constructor_node:
            return None
        
        callee_name: str | None = None
        receiver: str | None = None
        
        # Simple: `new MyClass()`
        if constructor_node.type == "identifier":
            callee_name = self._extract_text(
                content, constructor_node.start_byte, constructor_node.end_byte
            )
        
        # Namespaced: `new a.b.Class()`
        elif constructor_node.type == "member_expression":
            property_node = constructor_node.child_by_field_name("property")
            if property_node:
                callee_name = self._extract_text(
                    content, property_node.start_byte, property_node.end_byte
                )
            
            object_node = constructor_node.child_by_field_name("object")
            if object_node:
                receiver = self._extract_text(
                    content, object_node.start_byte, object_node.end_byte
                )
        
        else:
            return None
        
        if not callee_name:
            return None
        
        return CallSite(
            callee_name=callee_name,
            receiver=receiver,
            line_number=line_number,
            column=column,
            is_constructor=True,
        )


class TypeScriptReferenceExtractor(JavaScriptReferenceExtractor):
    """TypeScript-specific reference extractor.
    
    TypeScript uses the same import/call syntax as JavaScript for runtime
    constructs, so we inherit from JavaScriptReferenceExtractor.
    
    TypeScript-specific features that could be added:
      - `import type { ... }` (type-only imports)
      - Type assertions in calls
      - Generic type parameters
    
    For now, we treat TypeScript the same as JavaScript since we're focused
    on runtime call relationships, not type-only imports.
    """
    
    @property
    def language(self) -> str:
        return "typescript"

