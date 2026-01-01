"""
Cross-file edge builder for IMPORTS and CALLS relationships.

This module creates cross-file edges in the knowledge graph:
  - IMPORTS edges: FileNode(source) -> FileNode(target) for import statements
  - CALLS edges: SymbolNode(caller) -> SymbolNode(callee) for function/method calls

The builder operates as a second pass after all FileNodes and SymbolNodes have been
created by RepoGraphBuilder. It uses the reference extractors to parse imports and
calls from source files, then resolves them to existing nodes.

Design principles:
  - High-confidence only: Skip edges when resolution is ambiguous
  - Best-effort type tracking: Track simple `obj = Class()` assignments
  - No external imports: Skip imports that resolve outside the repository

Supported languages:
  - Python
  - JavaScript
  - TypeScript
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.graph.graph_types import (
    FileNode,
    KnowledgeGraphEdge,
    KnowledgeGraphEdgeType,
    KnowledgeGraphNode,
    SymbolNode,
)
from src.parser.file_types import FileTypes
from src.parser.references import (
    CallSite,
    ExtractionResult,
    ImportReference,
    get_reference_extractor,
)
from src.parser.tree_sitter_parser import get_parser

logger = logging.getLogger(__name__)

# Languages that support reference extraction
SUPPORTED_LANGUAGES = frozenset({"python", "javascript", "typescript"})

# File extensions mapped to languages
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
}

# Extensions to try when resolving import paths
PYTHON_EXTENSIONS = (".py",)
JS_TS_EXTENSIONS = (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs")

# Package init files
PYTHON_INIT_FILES = ("__init__.py",)
JS_TS_INDEX_FILES = ("index.js", "index.ts", "index.jsx", "index.tsx")


@dataclass
class LocalImportMap:
    """Tracks imported names within a file for call resolution.
    
    Maps local names to their source file and original name.
    
    Attributes:
        name_to_source: Maps local name -> (source_file_relpath, original_name)
            Example: {"Calculator": ("utils.py", "Calculator")}
        
        module_aliases: Maps module alias -> source_file_relpath
            Example: {"utils": "lib/utils.py"} for `import utils` or `import lib.utils as utils`
    """
    name_to_source: dict[str, tuple[str, str]] = field(default_factory=dict)
    module_aliases: dict[str, str] = field(default_factory=dict)


@dataclass
class LocalTypeMap:
    """Tracks variable types from simple assignments for call resolution.
    
    Maps variable names to their inferred class/type name.
    
    Attributes:
        var_to_type: Maps variable name -> class name
            Example: {"obj": "Calculator"} for `obj = Calculator()`
    """
    var_to_type: dict[str, str] = field(default_factory=dict)


class CrossFileEdgeBuilder:
    """Builds cross-file IMPORTS and CALLS edges.
    
    This class performs a second pass over the repository after all nodes
    have been created. It:
      1. Builds lookup indices from existing nodes
      2. For each code file, extracts import and call references
      3. Resolves imports to target FileNodes -> creates IMPORTS edges
      4. Resolves calls to target SymbolNodes -> creates CALLS edges
    
    Example:
        builder = CrossFileEdgeBuilder(
            repo_root=Path("/path/to/repo"),
            nodes=existing_nodes,
        )
        new_edges = builder.build()
        all_edges.extend(new_edges)
    """
    
    def __init__(
        self,
        repo_root: Path,
        nodes: list[KnowledgeGraphNode],
    ):
        """Initialize the CrossFileEdgeBuilder.
        
        Args:
            repo_root: Absolute path to the repository root.
            nodes: List of all KnowledgeGraphNodes (FileNodes + SymbolNodes).
        """
        self.repo_root = repo_root
        self.nodes = nodes
        
        # Indices built from existing nodes
        self.file_by_relpath: dict[str, KnowledgeGraphNode] = {}
        self.symbols_by_file: dict[str, list[KnowledgeGraphNode]] = {}
        self.symbols_by_name_in_file: dict[tuple[str, str], list[KnowledgeGraphNode]] = {}
        self.symbols_by_qname_in_file: dict[tuple[str, str], KnowledgeGraphNode] = {}
        
        # Build indices
        self._build_indices()
    
    def _build_indices(self) -> None:
        """Build lookup indices from existing nodes.
        
        Creates fast lookup dictionaries for:
          - file_by_relpath: Find FileNode by relative path
          - symbols_by_file: Find all symbols in a file
          - symbols_by_name_in_file: Find symbols by name within a file
          - symbols_by_qname_in_file: Find symbols by qualified name within a file
        """
        for node in self.nodes:
            if isinstance(node.node, FileNode):
                # Index FileNodes by relative path
                self.file_by_relpath[node.node.relative_path] = node
                
            elif isinstance(node.node, SymbolNode):
                relpath = node.node.relative_path
                name = node.node.name
                qname = node.node.qualified_name
                
                # Index symbols by file
                if relpath not in self.symbols_by_file:
                    self.symbols_by_file[relpath] = []
                self.symbols_by_file[relpath].append(node)
                
                # Index symbols by (file, name)
                key = (relpath, name)
                if key not in self.symbols_by_name_in_file:
                    self.symbols_by_name_in_file[key] = []
                self.symbols_by_name_in_file[key].append(node)
                
                # Index symbols by (file, qualified_name)
                if qname:
                    qkey = (relpath, qname)
                    self.symbols_by_qname_in_file[qkey] = node
        
        logger.debug(
            f"Built indices: {len(self.file_by_relpath)} files, "
            f"{len(self.symbols_by_file)} files with symbols"
        )
    
    def build(self) -> list[KnowledgeGraphEdge]:
        """Build all cross-file edges.
        
        Processes each code file to extract references and create edges.
        
        Returns:
            List of KnowledgeGraphEdge objects (IMPORTS and CALLS edges).
        """
        edges: list[KnowledgeGraphEdge] = []
        imports_count = 0
        calls_count = 0
        
        # Process each file that has a supported language
        for relpath, file_node in self.file_by_relpath.items():
            # Get language from file extension
            language = self._get_language(relpath)
            if language is None:
                continue
            
            # Get absolute path
            abs_path = self.repo_root / relpath
            if not abs_path.exists() or not abs_path.is_file():
                continue
            
            try:
                # Extract references from this file
                result = self._extract_references(abs_path, language)
                if result is None:
                    continue
                
                # Build import map for call resolution
                import_map = LocalImportMap()
                
                # Process imports -> IMPORTS edges
                for imp in result.imports:
                    import_edges = self._resolve_import(
                        source_file=file_node,
                        source_relpath=relpath,
                        import_ref=imp,
                        language=language,
                        import_map=import_map,
                    )
                    edges.extend(import_edges)
                    imports_count += len(import_edges)
                
                # Build type map from call sites (track assignments like obj = Class())
                type_map = self._build_type_map(result.call_sites, import_map)
                
                # Process calls -> CALLS edges
                for call in result.call_sites:
                    call_edge = self._resolve_call(
                        source_relpath=relpath,
                        call_site=call,
                        import_map=import_map,
                        type_map=type_map,
                    )
                    if call_edge:
                        edges.append(call_edge)
                        calls_count += 1
                        
            except Exception as e:
                logger.warning(f"Failed to process references for {relpath}: {e}")
                continue
        
        logger.info(
            f"Built cross-file edges: {imports_count} IMPORTS, {calls_count} CALLS"
        )
        
        return edges
    
    def _get_language(self, relpath: str) -> str | None:
        """Get the language for a file based on its extension.
        
        Args:
            relpath: Relative path to the file.
            
        Returns:
            Language string if supported, None otherwise.
        """
        ext = Path(relpath).suffix.lower()
        return EXTENSION_TO_LANGUAGE.get(ext)
    
    def _extract_references(
        self,
        file_path: Path,
        language: str,
    ) -> ExtractionResult | None:
        """Extract import and call references from a file.
        
        Args:
            file_path: Absolute path to the file.
            language: Language identifier.
            
        Returns:
            ExtractionResult with imports and call_sites, or None on error.
        """
        try:
            # Parse with Tree-sitter
            tree, _ = get_parser(file_path)
            
            # Read file content
            with open(file_path, "rb") as f:
                content = f.read()
            
            # Extract references
            extractor = get_reference_extractor(language)
            return extractor.extract(tree, content)
            
        except Exception as e:
            logger.debug(f"Failed to extract references from {file_path}: {e}")
            return None
    
    # -------------------------------------------------------------------------
    # IMPORTS Edge Resolution
    # -------------------------------------------------------------------------
    
    def _resolve_import(
        self,
        source_file: KnowledgeGraphNode,
        source_relpath: str,
        import_ref: ImportReference,
        language: str,
        import_map: LocalImportMap,
    ) -> list[KnowledgeGraphEdge]:
        """Resolve an import reference to IMPORTS edges.
        
        Args:
            source_file: The FileNode of the importing file.
            source_relpath: Relative path of the importing file.
            import_ref: The ImportReference to resolve.
            language: Language of the source file.
            import_map: Import map to update with resolved imports.
            
        Returns:
            List of IMPORTS edges (usually 0 or 1).
        """
        edges: list[KnowledgeGraphEdge] = []
        
        # Resolve the import path to a file in the repository
        target_relpath = self._resolve_import_path(
            source_relpath=source_relpath,
            module_path=import_ref.module_path,
            is_relative=import_ref.is_relative,
            language=language,
        )
        
        if target_relpath is None:
            # External import or unresolvable - skip
            return edges
        
        # Get the target FileNode
        target_file = self.file_by_relpath.get(target_relpath)
        if target_file is None:
            return edges
        
        # Create IMPORTS edge: source_file -> target_file
        edges.append(KnowledgeGraphEdge(
            source_node=source_file,
            target_node=target_file,
            edge_type=KnowledgeGraphEdgeType.imports,
        ))
        
        # Update import map for call resolution
        if import_ref.imported_names:
            # `from x import A, B` -> map each name
            for name in import_ref.imported_names:
                import_map.name_to_source[name] = (target_relpath, name)
        
        if import_ref.alias:
            if import_ref.imported_names:
                # `from x import A as B` -> map alias to original
                # Note: We only handle single-name alias for simplicity
                if len(import_ref.imported_names) == 1:
                    original_name = import_ref.imported_names[0]
                    import_map.name_to_source[import_ref.alias] = (target_relpath, original_name)
            else:
                # `import x as y` or `import * as y` -> map alias to module
                import_map.module_aliases[import_ref.alias] = target_relpath
        elif not import_ref.imported_names and not import_ref.is_wildcard:
            # `import x` -> map module name to file
            # Extract the module name from the path
            module_name = Path(import_ref.module_path).stem
            if module_name:
                import_map.module_aliases[module_name] = target_relpath
        
        return edges
    
    def _resolve_import_path(
        self,
        source_relpath: str,
        module_path: str,
        is_relative: bool,
        language: str,
    ) -> str | None:
        """Resolve an import module path to a file path.
        
        Args:
            source_relpath: Relative path of the importing file.
            module_path: The module path from the import statement.
            is_relative: Whether this is a relative import.
            language: Language of the source file.
            
        Returns:
            Relative path to the target file if found, None otherwise.
        """
        if language == "python":
            return self._resolve_python_import(source_relpath, module_path, is_relative)
        else:  # javascript, typescript
            return self._resolve_js_import(source_relpath, module_path, is_relative)
    
    def _resolve_python_import(
        self,
        source_relpath: str,
        module_path: str,
        is_relative: bool,
    ) -> str | None:
        """Resolve a Python import path.
        
        Handles:
          - Relative: `.utils` -> sibling utils.py or utils/__init__.py
          - Relative: `..utils` -> parent's utils.py
          - Absolute: `mypackage.utils` -> mypackage/utils.py
        
        Args:
            source_relpath: Relative path of the importing file.
            module_path: The module path (e.g., ".utils", "..parent.utils").
            is_relative: Whether this is a relative import.
            
        Returns:
            Relative path to target file if found, None otherwise.
        """
        source_dir = Path(source_relpath).parent
        
        if is_relative:
            # Count leading dots and extract module name
            dots = 0
            for char in module_path:
                if char == ".":
                    dots += 1
                else:
                    break
            
            remaining_path = module_path[dots:]
            
            # Navigate up directories based on dot count
            # `.` = current directory, `..` = parent, etc.
            target_dir = source_dir
            for _ in range(dots - 1):  # -1 because first dot is current dir
                target_dir = target_dir.parent
                if str(target_dir) == ".":
                    target_dir = Path(".")
            
            # Convert module path to file path
            if remaining_path:
                module_parts = remaining_path.split(".")
                target_path = target_dir / "/".join(module_parts)
            else:
                target_path = target_dir
        else:
            # Absolute import - convert dots to path separators
            module_parts = module_path.split(".")
            target_path = Path("/".join(module_parts))
        
        # Try to find the actual file
        return self._find_python_file(str(target_path))
    
    def _find_python_file(self, base_path: str) -> str | None:
        """Find a Python file given a base path (without extension).
        
        Tries:
          1. base_path.py
          2. base_path/__init__.py
        
        Args:
            base_path: Base path without extension.
            
        Returns:
            Relative path if found, None otherwise.
        """
        # Clean up path
        base_path = base_path.lstrip("./")
        
        # Try direct file
        for ext in PYTHON_EXTENSIONS:
            candidate = f"{base_path}{ext}"
            if candidate in self.file_by_relpath:
                return candidate
        
        # Try package __init__.py
        for init in PYTHON_INIT_FILES:
            candidate = f"{base_path}/{init}"
            if candidate in self.file_by_relpath:
                return candidate
        
        return None
    
    def _resolve_js_import(
        self,
        source_relpath: str,
        module_path: str,
        is_relative: bool,
    ) -> str | None:
        """Resolve a JavaScript/TypeScript import path.
        
        Handles:
          - Relative: `./utils` -> sibling utils.js/ts
          - Relative: `../utils` -> parent's utils.js/ts
          - Package: `lodash` -> skip (external)
          - Scoped: `@scope/pkg` -> skip (external)
        
        Args:
            source_relpath: Relative path of the importing file.
            module_path: The module path (e.g., "./utils", "lodash").
            is_relative: Whether this is a relative import.
            
        Returns:
            Relative path to target file if found, None otherwise.
        """
        if not is_relative:
            # Non-relative imports are typically external packages
            # We could try to resolve node_modules, but skip for now
            return None
        
        source_dir = Path(source_relpath).parent
        
        # Resolve relative path
        # Handle ./ and ../ prefixes
        if module_path.startswith("./"):
            target_path = source_dir / module_path[2:]
        elif module_path.startswith("../"):
            # Count ../ prefixes
            remaining = module_path
            target_dir = source_dir
            while remaining.startswith("../"):
                target_dir = target_dir.parent
                remaining = remaining[3:]
            target_path = target_dir / remaining
        else:
            # Shouldn't happen for relative imports, but handle gracefully
            target_path = source_dir / module_path
        
        return self._find_js_file(str(target_path))
    
    def _find_js_file(self, base_path: str) -> str | None:
        """Find a JS/TS file given a base path (without extension).
        
        Tries:
          1. base_path (exact match, may already have extension)
          2. base_path.js, base_path.ts, etc.
          3. base_path/index.js, base_path/index.ts, etc.
        
        Args:
            base_path: Base path (may or may not have extension).
            
        Returns:
            Relative path if found, None otherwise.
        """
        # Clean up path
        base_path = base_path.lstrip("./")
        
        # Try exact match first (path may already have extension)
        if base_path in self.file_by_relpath:
            return base_path
        
        # Try with extensions
        for ext in JS_TS_EXTENSIONS:
            candidate = f"{base_path}{ext}"
            if candidate in self.file_by_relpath:
                return candidate
        
        # Try index files
        for index in JS_TS_INDEX_FILES:
            candidate = f"{base_path}/{index}"
            if candidate in self.file_by_relpath:
                return candidate
        
        return None
    
    # -------------------------------------------------------------------------
    # CALLS Edge Resolution
    # -------------------------------------------------------------------------
    
    def _build_type_map(
        self,
        call_sites: list[CallSite],
        import_map: LocalImportMap,
    ) -> LocalTypeMap:
        """Build a type map from constructor calls.
        
        Tracks simple patterns like:
          - `obj = MyClass()` -> obj has type MyClass
          - `instance = new Service()` -> instance has type Service
        
        This is a simple heuristic - we don't do full type inference.
        
        Args:
            call_sites: List of call sites from the file.
            import_map: Import map for resolving class names.
            
        Returns:
            LocalTypeMap with variable -> type mappings.
        """
        type_map = LocalTypeMap()
        
        # We can't directly determine assignments from call sites alone.
        # This would require parsing the AST more deeply.
        # For now, we'll use the constructor flag as a hint.
        # The actual variable assignment tracking would need AST analysis.
        
        # Note: Full implementation would require tracking assignments
        # like `x = Foo()` by looking at the parent AST node.
        # For this iteration, we rely on direct resolution.
        
        return type_map
    
    def _resolve_call(
        self,
        source_relpath: str,
        call_site: CallSite,
        import_map: LocalImportMap,
        type_map: LocalTypeMap,
    ) -> KnowledgeGraphEdge | None:
        """Resolve a call site to a CALLS edge.
        
        Args:
            source_relpath: Relative path of the calling file.
            call_site: The call site to resolve.
            import_map: Import map for resolving callee names.
            type_map: Type map for resolving method calls on typed variables.
            
        Returns:
            CALLS edge if resolved, None otherwise.
        """
        # Step 1: Find the caller symbol (enclosing function/method)
        caller_symbol = self._find_enclosing_symbol(
            source_relpath, call_site.line_number
        )
        if caller_symbol is None:
            # Call is at module level or we couldn't find enclosing symbol
            return None
        
        # Step 2: Resolve the callee symbol
        callee_symbol = self._resolve_callee(
            source_relpath=source_relpath,
            call_site=call_site,
            import_map=import_map,
            type_map=type_map,
        )
        if callee_symbol is None:
            return None
        
        # Step 3: Avoid self-references
        if caller_symbol.node_id == callee_symbol.node_id:
            return None
        
        # Create CALLS edge
        return KnowledgeGraphEdge(
            source_node=caller_symbol,
            target_node=callee_symbol,
            edge_type=KnowledgeGraphEdgeType.calls,
        )
    
    def _find_enclosing_symbol(
        self,
        relpath: str,
        line_number: int,
    ) -> KnowledgeGraphNode | None:
        """Find the tightest enclosing symbol for a line number.
        
        Uses line span containment to find the innermost function/method/class
        that contains the given line.
        
        Args:
            relpath: Relative path of the file.
            line_number: 1-indexed line number.
            
        Returns:
            The enclosing SymbolNode, or None if not found.
        """
        symbols = self.symbols_by_file.get(relpath, [])
        if not symbols:
            return None
        
        # Find all symbols that contain this line
        candidates: list[tuple[KnowledgeGraphNode, int]] = []
        for node in symbols:
            if isinstance(node.node, SymbolNode):
                symbol = node.node
                if symbol.start_line <= line_number <= symbol.end_line:
                    # Calculate span size (smaller = tighter)
                    span = symbol.end_line - symbol.start_line
                    candidates.append((node, span))
        
        if not candidates:
            return None
        
        # Return the symbol with the smallest span (tightest enclosure)
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]
    
    def _resolve_callee(
        self,
        source_relpath: str,
        call_site: CallSite,
        import_map: LocalImportMap,
        type_map: LocalTypeMap,
    ) -> KnowledgeGraphNode | None:
        """Resolve the callee of a call site.
        
        Handles:
          1. Direct imported function: `helper()` where helper is imported
          2. Method on module alias: `utils.helper()` where utils is imported module
          3. Constructor call: `MyClass()` where MyClass is imported
          4. Method on typed variable: `obj.method()` where obj's type is tracked
        
        Args:
            source_relpath: Relative path of the calling file.
            call_site: The call site to resolve.
            import_map: Import map for name resolution.
            type_map: Type map for variable types.
            
        Returns:
            The callee SymbolNode if resolved, None otherwise.
        """
        callee_name = call_site.callee_name
        receiver = call_site.receiver
        
        # Case 1: Direct call to imported name (no receiver)
        if receiver is None:
            return self._resolve_direct_call(callee_name, import_map)
        
        # Case 2: Method call on module alias (e.g., utils.helper())
        if receiver in import_map.module_aliases:
            target_file = import_map.module_aliases[receiver]
            return self._find_symbol_in_file(target_file, callee_name)
        
        # Case 3: Method call on imported class (e.g., Calculator.add() - static method)
        if receiver in import_map.name_to_source:
            target_file, class_name = import_map.name_to_source[receiver]
            # Look for qualified name like "Calculator.add"
            qname = f"{class_name}.{callee_name}"
            return self._find_symbol_by_qname(target_file, qname)
        
        # Case 4: Method call on typed variable (e.g., obj.add() where obj: Calculator)
        if receiver in type_map.var_to_type:
            class_name = type_map.var_to_type[receiver]
            # Try to find the class in imports
            if class_name in import_map.name_to_source:
                target_file, original_name = import_map.name_to_source[class_name]
                qname = f"{original_name}.{callee_name}"
                return self._find_symbol_by_qname(target_file, qname)
        
        # Case 5: Chained access (e.g., a.b.method()) - try last part as module alias
        # Split receiver on dots and try the first part
        if "." in receiver:
            parts = receiver.split(".")
            first_part = parts[0]
            if first_part in import_map.module_aliases:
                # This is complex - we'd need to resolve the chain
                # For now, skip
                pass
        
        # Couldn't resolve
        return None
    
    def _resolve_direct_call(
        self,
        callee_name: str,
        import_map: LocalImportMap,
    ) -> KnowledgeGraphNode | None:
        """Resolve a direct function call (no receiver).
        
        Args:
            callee_name: Name of the function being called.
            import_map: Import map for resolution.
            
        Returns:
            SymbolNode if found, None otherwise.
        """
        if callee_name not in import_map.name_to_source:
            return None
        
        target_file, original_name = import_map.name_to_source[callee_name]
        return self._find_symbol_in_file(target_file, original_name)
    
    def _find_symbol_in_file(
        self,
        relpath: str,
        name: str,
    ) -> KnowledgeGraphNode | None:
        """Find a symbol by name in a file.
        
        Args:
            relpath: Relative path of the file.
            name: Name of the symbol.
            
        Returns:
            SymbolNode if found, None otherwise.
        """
        key = (relpath, name)
        symbols = self.symbols_by_name_in_file.get(key)
        if symbols and len(symbols) > 0:
            # Return the first match (could be multiple with same name)
            return symbols[0]
        return None
    
    def _find_symbol_by_qname(
        self,
        relpath: str,
        qname: str,
    ) -> KnowledgeGraphNode | None:
        """Find a symbol by qualified name in a file.
        
        Args:
            relpath: Relative path of the file.
            qname: Qualified name of the symbol (e.g., "Class.method").
            
        Returns:
            SymbolNode if found, None otherwise.
        """
        key = (relpath, qname)
        return self.symbols_by_qname_in_file.get(key)

