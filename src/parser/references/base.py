"""
Base reference extractor interface and data models.

This module provides:
  - ImportReference: Represents an import statement with source/target info
  - CallSite: Represents a function/method call with caller context
  - ReferenceExtractor: Abstract base class for language-specific reference extraction

These data models are used by CrossFileEdgeBuilder to create:
  - IMPORTS edges: FileNode(source) -> FileNode(target)
  - CALLS edges: SymbolNode(caller) -> SymbolNode(callee)

Design Principles:
  - Extract raw reference data without resolution (resolution is done later)
  - Include line numbers for all references (needed for caller symbol lookup)
  - Keep extractors stateless and focused on parsing
  - Support both imports and call-sites in a single pass when possible

Usage:
    from src.parser.references import get_reference_extractor
    
    extractor = get_reference_extractor("python")
    imports, calls = extractor.extract(tree, file_content)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Tree

# Data Models

@dataclass
class ImportReference:
    """Represents an import statement extracted from source code.
    
    This captures the raw import information without resolving to actual files.
    Resolution to file paths happens in CrossFileEdgeBuilder.
    
    Attributes:
        module_path: The module/path being imported.
            - Python: "os.path", ".", ".utils", "..parent"
            - JS/TS: "./utils", "../lib", "lodash", "@scope/pkg"
        
        imported_names: List of specific names imported from the module.
            - Python `from x import A, B` -> ["A", "B"]
            - JS `import { A, B } from 'x'` -> ["A", "B"]
            - Empty list for whole-module imports: `import x`, `import 'x'`
        
        alias: Optional alias for the import.
            - Python `import x as y` -> alias="y"
            - Python `from x import A as B` -> imported_names=["A"], alias="B"
            - JS `import * as x from 'y'` -> alias="x"
            - None if no alias
        
        is_relative: Whether this is a relative import.
            - Python: True for ".", "..", ".utils"
            - JS/TS: True for "./", "../"
            - False for absolute imports like "os", "lodash"
        
        line_number: 1-indexed line where the import appears.
            Used for debugging and error reporting.
        
        is_wildcard: Whether this is a wildcard import.
            - Python `from x import *` -> True
            - We still create the edge but can't resolve individual names
    
    Examples:
        # Python: import os
        ImportReference(module_path="os", imported_names=[], alias=None, 
                       is_relative=False, line_number=1)
        
        # Python: from ..utils import helper as h
        ImportReference(module_path="..utils", imported_names=["helper"], 
                       alias="h", is_relative=True, line_number=5)
        
        # JS: import { useState } from 'react'
        ImportReference(module_path="react", imported_names=["useState"], 
                       alias=None, is_relative=False, line_number=1)
        
        # JS: import * as path from 'path'
        ImportReference(module_path="path", imported_names=[], 
                       alias="path", is_relative=False, line_number=2)
    """
    module_path: str
    imported_names: list[str] = field(default_factory=list)
    alias: str | None = None
    is_relative: bool = False
    line_number: int = 0
    is_wildcard: bool = False


@dataclass
class CallSite:
    """Represents a function/method call extracted from source code.
    
    This captures call information needed to create CALLS edges.
    The caller symbol is determined by line span containment.
    The callee symbol is resolved via import mapping + local inference.
    
    Attributes:
        callee_name: The name/expression being called.
            - Simple call: "foo" for `foo()`
            - Method call: "bar" for `obj.bar()` (receiver is separate)
            - Chained: "baz" for `a.b.baz()` (receiver captures "a.b")
        
        receiver: The object/expression the method is called on, if any.
            - None for simple function calls: `foo()`
            - "obj" for `obj.method()`
            - "a.b" for `a.b.method()`
            - Used to resolve to imported class instances
        
        line_number: 1-indexed line where the call appears.
            Used to determine the enclosing caller symbol.
        
        column: 0-indexed column where the call starts.
            Helps distinguish multiple calls on the same line.
        
        is_constructor: Whether this is a constructor/instantiation call.
            - Python: True for `MyClass()` (identified heuristically by PascalCase)
            - JS/TS: True for `new MyClass()`
            - Helps resolve to class definitions
    
    Examples:
        # Python: result = helper()
        CallSite(callee_name="helper", receiver=None, line_number=10, 
                column=9, is_constructor=False)
        
        # Python: obj.process()
        CallSite(callee_name="process", receiver="obj", line_number=15,
                column=0, is_constructor=False)
        
        # Python: instance = MyClass()
        CallSite(callee_name="MyClass", receiver=None, line_number=20,
                column=11, is_constructor=True)
        
        # JS: const x = new Service()
        CallSite(callee_name="Service", receiver=None, line_number=5,
                column=10, is_constructor=True)
    """
    callee_name: str
    receiver: str | None = None
    line_number: int = 0
    column: int = 0
    is_constructor: bool = False


@dataclass
class ExtractionResult:
    """Container for all references extracted from a file.
    
    Attributes:
        imports: List of import references found in the file.
        call_sites: List of call sites found in the file.
    """
    imports: list[ImportReference] = field(default_factory=list)
    call_sites: list[CallSite] = field(default_factory=list)


class ReferenceExtractor(ABC):
    """Abstract interface for language-specific reference extraction.
    
    Each language implementation uses Tree-sitter to parse and extract:
      1. Import statements -> ImportReference objects
      2. Function/method calls -> CallSite objects
    
    Subclasses must implement:
      - language (property): Return the language identifier
      - extract(): Extract all references from a syntax tree
    
    The extraction is done in a single AST traversal for efficiency.
    
    Note on Tree-sitter:
      - Tree-sitter provides fast, incremental parsing with error recovery
      - Node types and field names are defined by each language's grammar
      - We use the tree_sitter_language_pack for parser access
    """
    
    # Maximum recursion depth to prevent stack overflow on malformed ASTs
    DEFAULT_MAX_DEPTH: int = 100
    
    @property
    @abstractmethod
    def language(self) -> str:
        """Return the language identifier (e.g., 'python', 'javascript')."""
        pass
    
    @abstractmethod
    def extract(
        self,
        tree: "Tree",
        file_content: bytes,
    ) -> ExtractionResult:
        """Extract all import references and call sites from the syntax tree.
        
        Args:
            tree: The Tree-sitter syntax tree (from parsing)
            file_content: Raw file content as bytes (for text extraction)
            
        Returns:
            ExtractionResult containing imports and call_sites lists
            
        Note:
            - Line numbers are 1-indexed in the returned objects
            - Columns are 0-indexed
            - Empty result is returned on parse errors (fail gracefully)
        """
        pass
    
    def _extract_text(self, content: bytes, start_byte: int, end_byte: int) -> str:
        """Extract text from content bytes.
        
        Args:
            content: Raw file content as bytes
            start_byte: Starting byte offset (from Tree-sitter node)
            end_byte: Ending byte offset (from Tree-sitter node)
            
        Returns:
            Decoded UTF-8 string from the byte range
        """
        return content[start_byte:end_byte].decode("utf-8", errors="replace")
