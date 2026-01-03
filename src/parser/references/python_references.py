"""
Python-specific reference extractor using Tree-sitter.

This module extracts import statements and call sites from Python source files.

Supported import patterns:
  - `import x`                    -> module_path="x"
  - `import x as y`               -> module_path="x", alias="y"
  - `import x.y.z`                -> module_path="x.y.z"
  - `from x import A`             -> module_path="x", imported_names=["A"]
  - `from x import A, B`          -> module_path="x", imported_names=["A", "B"]
  - `from x import A as B`        -> module_path="x", imported_names=["A"], alias="B"
  - `from . import x`             -> module_path=".", imported_names=["x"], is_relative=True
  - `from .. import x`            -> module_path="..", imported_names=["x"], is_relative=True
  - `from .utils import helper`   -> module_path=".utils", imported_names=["helper"], is_relative=True
  - `from x import *`             -> module_path="x", is_wildcard=True

Supported call patterns:
  - `foo()`                       -> callee_name="foo"
  - `obj.method()`                -> callee_name="method", receiver="obj"
  - `a.b.c.method()`              -> callee_name="method", receiver="a.b.c"
  - `MyClass()`                   -> callee_name="MyClass", is_constructor=True
  - `module.Class()`              -> callee_name="Class", receiver="module", is_constructor=True

Python Tree-sitter grammar reference:
  https://github.com/tree-sitter/tree-sitter-python/blob/master/grammar.js

Key node types used:
  - import_statement: `import x` or `import x as y`
  - import_from_statement: `from x import y`
  - dotted_name: Module path like `os.path`
  - aliased_import: `x as y` within import
  - call: Function/method call expression
  - attribute: `obj.attr` access
  - identifier: Simple name
"""

from tree_sitter import Node, Tree

from .base import CallSite, ExtractionResult, ImportReference, ReferenceExtractor


class PythonReferenceExtractor(ReferenceExtractor):
    """Python-specific reference extractor.
    
    Extracts import references and call sites from Python source files
    using Tree-sitter for parsing.
    
    The extraction is done in a single AST traversal:
      1. Top-level: Look for import_statement and import_from_statement
      2. Throughout: Look for call expressions
    
    Heuristic for constructor detection:
      - PascalCase names (starting with uppercase) are treated as class instantiations
      - This matches Python convention and works for most codebases
    """
    
    @property
    def language(self) -> str:
        return "python"
    
    def extract(
        self,
        tree: Tree,
        file_content: bytes,
    ) -> ExtractionResult:
        """Extract imports and call sites from Python source.
        
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
        
        This method performs a depth-first traversal, extracting:
          - Import statements at module level
          - Call expressions anywhere in the code
        
        Args:
            node: Current Tree-sitter node
            content: Raw file content as bytes
            result: Accumulator for extracted references
            depth: Current recursion depth (for overflow protection)
        """
        if depth > self.DEFAULT_MAX_DEPTH:
            return
        
        # Import Extraction
        # Handle: import x, import x as y, import x.y.z
        if node.type == "import_statement":
            imports = self._extract_import_statement(node, content)
            result.imports.extend(imports)
            return
        
        # Handle: from x import y, from . import z, from x import *
        if node.type == "import_from_statement":
            imports = self._extract_import_from_statement(node, content)
            result.imports.extend(imports)
            return
        
        # Call Site Extraction
        # Handle function/method calls
        if node.type == "call":
            call_site = self._extract_call(node, content)
            if call_site:
                result.call_sites.append(call_site)
            # Continue recursing - calls can be nested: foo(bar())
        
        # Recurse into children
        for child in node.children:
            self._walk_tree(child, content, result, depth + 1)
    

    # Import Extraction Helpers
    def _extract_import_statement(
        self,
        node: Node,
        content: bytes,
    ) -> list[ImportReference]:
        """Extract import references from `import x` style statements.
        
        Handles:
          - `import os`        -> module_path="os"
          - `import os.path`   -> module_path="os.path"
          - `import os as o`   -> module_path="os", alias="o"
          - `import os, sys`   -> two ImportReference objects
        
        Tree-sitter structure:
          import_statement
            ├── dotted_name "os.path"
            └── aliased_import
                ├── dotted_name "sys"
                └── as
                └── identifier "s"
        
        Args:
            node: import_statement node
            content: Raw file content
            
        Returns:
            List of ImportReference objects (one per imported module)
        """
        imports: list[ImportReference] = []
        line_number = node.start_point[0] + 1  # Convert to 1-indexed
        
        for child in node.children:
            # Direct module import: `import os` or `import os.path`
            if child.type == "dotted_name":
                module_path = self._extract_text(content, child.start_byte, child.end_byte)
                imports.append(ImportReference(
                    module_path=module_path,
                    imported_names=[],
                    alias=None,
                    is_relative=False,  # `import` statements are always absolute
                    line_number=line_number,
                ))
            
            # Aliased import: `import os as o`
            elif child.type == "aliased_import":
                module_path = None
                alias = None
                
                for subchild in child.children:
                    if subchild.type == "dotted_name":
                        module_path = self._extract_text(
                            content, subchild.start_byte, subchild.end_byte
                        )
                    elif subchild.type == "identifier":
                        # The alias identifier comes after "as"
                        alias = self._extract_text(
                            content, subchild.start_byte, subchild.end_byte
                        )
                
                if module_path:
                    imports.append(ImportReference(
                        module_path=module_path,
                        imported_names=[],
                        alias=alias,
                        is_relative=False,
                        line_number=line_number,
                    ))
        
        return imports
    
    def _extract_import_from_statement(
        self,
        node: Node,
        content: bytes,
    ) -> list[ImportReference]:
        """Extract import references from `from x import y` style statements.
        
        Handles:
          - `from os import path`           -> module_path="os", imported_names=["path"]
          - `from os import path, getcwd`   -> module_path="os", imported_names=["path", "getcwd"]
          - `from os import path as p`      -> module_path="os", imported_names=["path"], alias="p"
          - `from . import utils`           -> module_path=".", imported_names=["utils"], is_relative=True
          - `from ..utils import helper`    -> module_path="..utils", imported_names=["helper"], is_relative=True
          - `from os import *`              -> module_path="os", is_wildcard=True
        
        Tree-sitter structure:
          import_from_statement
            ├── from
            ├── dotted_name "os.path"  OR  relative_import "." / ".."
            ├── import
            └── (identifier | aliased_import | wildcard_import)*
        
        Note on relative imports:
          - "." means current package
          - ".." means parent package
          - ".utils" means utils module in current package
          - "..utils" means utils module in parent package
        
        Args:
            node: import_from_statement node
            content: Raw file content
            
        Returns:
            List of ImportReference objects
        """
        line_number = node.start_point[0] + 1
        
        # Extract the module path (what comes after "from")
        module_path = ""
        is_relative = False
        
        for child in node.children:
            # Absolute module path: `from os.path import ...`
            if child.type == "dotted_name":
                module_path = self._extract_text(content, child.start_byte, child.end_byte)
                is_relative = False
                break
            
            # Relative import prefix: `from . import ...` or `from .. import ...`
            elif child.type == "relative_import":
                prefix_parts = []
                module_name = ""
                
                for subchild in child.children:
                    if subchild.type == "import_prefix":
                        # This is the "." or ".." part
                        prefix_parts.append(
                            self._extract_text(content, subchild.start_byte, subchild.end_byte)
                        )
                    elif subchild.type == "dotted_name":
                        # This is the module name after the dots
                        module_name = self._extract_text(
                            content, subchild.start_byte, subchild.end_byte
                        )
                
                # Combine: ".." + "utils" -> "..utils"
                module_path = "".join(prefix_parts) + module_name
                is_relative = True
                break
        
        # Extract imported names (what comes after "import")
        imported_names: list[str] = []
        alias: str | None = None
        is_wildcard = False
        
        # Track if we've seen the "import" keyword
        seen_import = False
        
        for child in node.children:
            # Skip until we pass the "import" keyword
            if child.type == "import":
                seen_import = True
                continue
            
            if not seen_import:
                continue
            
            # Simple name import: `from x import A`
            if child.type == "identifier":
                name = self._extract_text(content, child.start_byte, child.end_byte)
                imported_names.append(name)
            
            # Imported name wrapped in dotted_name: `from x import A` or `from x import A.B`
            elif child.type == "dotted_name":
                name = self._extract_text(content, child.start_byte, child.end_byte)
                imported_names.append(name)
            
            # Aliased import: `from x import A as B`
            elif child.type == "aliased_import":
                name = None
                for subchild in child.children:
                    if subchild.type in ("identifier", "dotted_name"):
                        text = self._extract_text(
                            content, subchild.start_byte, subchild.end_byte
                        )
                        if name is None:
                            name = text  # First is the original name
                        else:
                            alias = text  # Second is the alias
                
                if name:
                    imported_names.append(name)
            
            # Wildcard import: `from x import *`
            elif child.type == "wildcard_import":
                is_wildcard = True
        
        # Create the ImportReference
        # Note: For `from x import A, B`, we return a single ImportReference
        # with multiple imported_names. The CrossFileEdgeBuilder will handle
        # resolving each name to symbols.
        return [ImportReference(
            module_path=module_path,
            imported_names=imported_names,
            alias=alias,
            is_relative=is_relative,
            line_number=line_number,
            is_wildcard=is_wildcard,
        )]
    

    # Call Extraction Helpers
    def _extract_call(
        self,
        node: Node,
        content: bytes,
    ) -> CallSite | None:
        """Extract a call site from a call expression node.
        
        Handles:
          - Simple calls: `foo()` -> callee_name="foo"
          - Method calls: `obj.method()` -> callee_name="method", receiver="obj"
          - Chained calls: `a.b.c()` -> callee_name="c", receiver="a.b"
          - Constructor calls: `MyClass()` -> callee_name="MyClass", is_constructor=True
        
        Tree-sitter structure for `obj.method()`:
          call
            ├── function: attribute
            │   ├── object: identifier "obj"
            │   ├── .
            │   └── attribute: identifier "method"
            └── arguments: argument_list (...)
        
        Tree-sitter structure for `foo()`:
          call
            ├── function: identifier "foo"
            └── arguments: argument_list (...)
        
        Args:
            node: call node
            content: Raw file content
            
        Returns:
            CallSite object, or None if extraction failed
        """
        line_number = node.start_point[0] + 1
        column = node.start_point[1]
        
        # Get the "function" child - what's being called
        function_node = node.child_by_field_name("function")
        if not function_node:
            return None
        
        callee_name: str | None = None
        receiver: str | None = None
        
        # Case 1: Simple function call - `foo()`
        if function_node.type == "identifier":
            callee_name = self._extract_text(
                content, function_node.start_byte, function_node.end_byte
            )
        
        # Case 2: Method/attribute call - `obj.method()` or `a.b.c()`
        elif function_node.type == "attribute":
            # The rightmost identifier is the method name
            attr_node = function_node.child_by_field_name("attribute")
            if attr_node:
                callee_name = self._extract_text(
                    content, attr_node.start_byte, attr_node.end_byte
                )
            
            # Everything to the left is the receiver
            object_node = function_node.child_by_field_name("object")
            if object_node:
                receiver = self._extract_text(
                    content, object_node.start_byte, object_node.end_byte
                )
        
        # Case 3: Other callable expressions (subscript, call result, etc.)
        # These are harder to resolve statically, so we skip them
        else:
            return None
        
        if not callee_name:
            return None
        
        # Heuristic: PascalCase names are likely class instantiations
        # This follows Python convention where classes use PascalCase
        is_constructor = (
            callee_name[0].isupper() and 
            not callee_name.isupper()  # Exclude ALL_CAPS (constants)
        )
        
        return CallSite(
            callee_name=callee_name,
            receiver=receiver,
            line_number=line_number,
            column=column,
            is_constructor=is_constructor,
        )

