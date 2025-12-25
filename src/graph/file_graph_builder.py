"""Building knowledge graph for a file.

This module constructs knowledge graph subgraphs from individual files. For source code files,
it uses Tree-sitter to parse the AST and extract symbols (functions/classes/methods/etc.)
into SymbolNodes. For documentation files, it extracts text chunks into TextNodes.

In the knowledge graph, we have the following node types:
  * FileNode: Represents a file or directory
  * SymbolNode: Represents a code symbol (function/class/method/etc.)
  * TextNode: Represents a chunk of text (for documentation)

And the following edge types:
  * HAS_FILE: FileNode -> FileNode (parent directory contains child)
  * HAS_SYMBOL: FileNode -> SymbolNode (file contains symbol)
  * HAS_TEXT: FileNode -> TextNode (file contains text chunk)
  * NEXT_CHUNK: TextNode -> TextNode (sequential text chunks)
  * CONTAINS_SYMBOL: SymbolNode -> SymbolNode (nested symbol relationship)
  * CALLS: SymbolNode -> SymbolNode (function/method call relationship)
  * IMPORTS: FileNode -> FileNode/SymbolNode (import relationship)

Note: Raw AST nodes (ASTNode) are NOT persisted. Tree-sitter is used ephemerally
to extract SymbolNodes with stable identities and spans.
"""

from pathlib import Path
from typing import Sequence, Tuple

from src.graph.graph_types import (
    FileNode,
    KnowledgeGraphEdge,
    KnowledgeGraphEdgeType,
    KnowledgeGraphNode,
    SymbolNode,
    TextNode,
)
from src.graph.utils import (
    generate_ast_fingerprint_from_types,
    generate_stable_symbol_id,
    generate_symbol_version_id,
)
from src.parser import tree_sitter_parser
from src.parser.tree_sitter_parser import ParseError, UnsupportedLanguageError
from src.parser.extractor import get_symbol_extractor


class FileGraphBuilder:
    """A class for building knowledge graphs from individual files.
    
    This class processes files and creates knowledge graph representation using different
    strategies based on the file type. For source code files, it uses tree-sitter to create
    an Abstract Syntax Tree (AST) and extracts symbols (functions/classes/methods/etc.).
    For documentation files, it extracts text chunks and creates text nodes.
    It also handles directory structure and file relationships.

    The resulting knowledge graph consists of nodes (KnowledgeGraphNode) connected by
    edges (KnowledgeGraphEdge) with different relationship types (KnowledgeGraphEdgeType).
    
    Key design decisions:
      - Raw AST nodes are NOT stored; Tree-sitter is used ephemerally for symbol extraction
      - Symbols get dual IDs: snapshot-scoped (symbol_version_id) and stable (stable_symbol_id)
      - Fingerprinting is used for cross-snapshot symbol identity matching
    """
    
    def __init__(
        self,
        repo_id: str,
        commit_sha: str | None = None,
        max_symbols: int = 500,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        """Initialize the FileGraphBuilder.
        
        Args:
            repo_id: Unique identifier for the repository (used in stable_symbol_id)
            commit_sha: Current commit SHA (used in symbol_version_id for snapshot scoping)
            max_symbols: Maximum number of symbols to extract from a single source file
            chunk_size: The chunk size for text files (in characters)
            chunk_overlap: The overlap size between text chunks
        """
        self.repo_id = repo_id
        self.commit_sha = commit_sha
        self.max_symbols = max_symbols
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
    def support_code_file(self, file_path: Path) -> bool:
        return tree_sitter_parser.support_file(file_path)
    
    def support_text_file(self, file_path: Path) -> bool:
        return file_path.suffix in [".md", ".txt", ".rst", ".markdown"]
    
    def support_file(self, file_path: Path) -> bool:
        """Check if we support building knowledge graphs for this file"""
        return self.support_code_file(file_path) or self.support_text_file(file_path)
    
    def build_file_graph(
        self, 
        parent_node: KnowledgeGraphNode, 
        file_path: Path, 
        next_node_id: int
        ) -> Tuple[int, Sequence[KnowledgeGraphNode], Sequence[KnowledgeGraphEdge]]:
        """Build knowledge graph for a single file.

        Args:
          parent_node: The parent knowledge graph node that represent the file.
            The node attribute should have type FileNode.
          file: The file to build knowledge graph.
          next_node_id: The next available node id.

        Returns:
          A tuple of (next_node_id, kg_nodes, kg_edges), where next_node_id is the
          new next_node_id, kg_nodes is a list of all nodes created for the file,
          and kg_edges is a list of all edges created for this file.
        """
        # In this case, it is a file that tree sitter can parse (source code)
        if self.support_code_file(file_path):
            return self._tree_sitter_file_graph(parent_node, file_path, next_node_id)
        # otherwise, it's a text file that we can parse using langchain text splitter
        else:
            return self._text_file_graph(parent_node, file_path, next_node_id)

    def _tree_sitter_file_graph(
        self, 
        parent_node: KnowledgeGraphNode, 
        file_path: Path, 
        next_node_id: int
    ) -> Tuple[int, Sequence[KnowledgeGraphNode], Sequence[KnowledgeGraphEdge]]:
        """Parse a source code file with Tree-sitter and build the file's SymbolNode subgraph.

        Sentinel does not persist raw AST nodes in the knowledge graph for PR review. Instead, Tree-sitter is used
        at indexing time to extract higher-level definition anchors (SymbolNode) with stable spans and identities.

        This method constructs a subgraph where:
          - The file (parent FileNode) is connected to each extracted SymbolNode via an edge of type HAS_SYMBOL.
            This is the primary connection used for PR diff hunk -> symbol mapping (via start_line/end_line spans).
          - Nested symbols are connected via CONTAINS_SYMBOL (e.g., class -> method).
          - Optional best-effort semantic edges may be emitted:
            - CALLS: SymbolNode -> SymbolNode (or unresolved callee name with confidence metadata)
            - IMPORTS: FileNode -> FileNode/SymbolNode (best-effort, with confidence/import_text metadata)
            
        Args:
            parent_node: The parent knowledge graph node representing the file (should wrap a FileNode).
            file_path: The file to be parsed and included in the knowledge graph.
            next_node_id: The next available node id (to ensure global uniqueness in the graph).

        Returns:
            Tuple containing:
                - The next available node id after all nodes are created.
                - A list of all SymbolNode-related KnowledgeGraphNode objects for this file.
                - A list of all edges created for this file's symbol subgraph (HAS_SYMBOL, CONTAINS_SYMBOL,
                  and optionally CALLS/IMPORTS).

        Algorithm:
            1. Parse the file with Tree-sitter to obtain a syntax tree.
            2. Get the language-specific symbol extractor and extract symbols.
            3. For each extracted symbol:
               - Generate symbol_version_id (snapshot-scoped) and stable_symbol_id (cross-snapshot)
               - Generate AST fingerprint from node types for stable matching
               - Create a SymbolNode wrapped in a KnowledgeGraphNode
            4. Add HAS_SYMBOL edges from the parent FileNode to every extracted SymbolNode.
            5. Build nesting (CONTAINS_SYMBOL) using the extractor's hierarchy builder.

        Notes:
            - The Tree-sitter AST is used ephemerally; it is not stored as ASTNode graph nodes.
            - This function only builds the per-file symbol subgraph; repo integration is done by caller.
        """
        nodes: list[KnowledgeGraphNode] = []
        edges: list[KnowledgeGraphEdge] = []
        
        # Validate parent node
        if not isinstance(parent_node.node, FileNode):
            raise ValueError("parent_node must wrap a FileNode")
        
        file_node: FileNode = parent_node.node
        
        # Parse the file with Tree-sitter and get language
        try:
            tree, language = tree_sitter_parser.get_parser(file_path)
        except UnsupportedLanguageError:
            # File type not supported by tree-sitter, skip gracefully
            return next_node_id, nodes, edges
        except ParseError as e:
            raise RuntimeError(f"Failed to parse file {file_path}: {e}") from e
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Source file not found: {file_path}") from e
        
        # Validate parse result
        if tree.root_node.has_error or tree.root_node.child_count == 0:
            return next_node_id, nodes, edges
        
        # Get language-specific symbol extractor
        extractor = get_symbol_extractor(language)
        if not extractor:
            # Language not supported for symbol extraction yet
            return next_node_id, nodes, edges
        
        # Read file content for extraction
        try:
            file_content = file_path.read_bytes()
        except (IOError, OSError) as e:
            raise RuntimeError(f"Failed to read file {file_path}: {e}") from e
        
        # Extract symbols using the language-specific extractor
        extracted_symbols = extractor.extract_symbols(tree, file_path, file_content)
        
        # Limit to max_symbols if needed
        if len(extracted_symbols) > self.max_symbols:
            extracted_symbols = extracted_symbols[:self.max_symbols]
        
        # Build symbol hierarchy (CONTAINS_SYMBOL relationships)
        hierarchy = extractor.build_symbol_hierarchy(extracted_symbols)
        
        # Create KnowledgeGraphNodes for each symbol
        symbol_kg_nodes: list[KnowledgeGraphNode] = []
        
        for extracted in extracted_symbols:
            # Generate fingerprint from AST node types
            fingerprint = None
            if extracted.node_types:
                fingerprint = generate_ast_fingerprint_from_types(extracted.node_types)
            
            # Generate dual IDs
            symbol_version_id = generate_symbol_version_id(
                commit_sha=self.commit_sha,
                relative_path=file_node.relative_path,
                kind=extracted.kind,
                name=extracted.name,
                qualified_name=extracted.qualified_name,
                start_line=extracted.start_line,
                end_line=extracted.end_line,
            )
            
            stable_symbol_id = generate_stable_symbol_id(
                repo_id=self.repo_id,
                kind=extracted.kind,
                qualified_name=extracted.qualified_name,
                name=extracted.name,
                fingerprint=fingerprint,
            )
            
            # Create SymbolNode
            symbol_node = SymbolNode(
                symbol_version_id=symbol_version_id,
                stable_symbol_id=stable_symbol_id,
                kind=extracted.kind,
                name=extracted.name,
                qualified_name=extracted.qualified_name,
                language=language,
                relative_path=file_node.relative_path,
                start_line=extracted.start_line,
                end_line=extracted.end_line,
                signature=extracted.signature,
                docstring=extracted.docstring,
                fingerprint=fingerprint,
            )
            
            # Wrap in KnowledgeGraphNode
            kg_node = KnowledgeGraphNode(
                node_id=str(next_node_id),
                node=symbol_node,
            )
            symbol_kg_nodes.append(kg_node)
            nodes.append(kg_node)
            next_node_id += 1
            
            # Create HAS_SYMBOL edge from file to symbol
            edges.append(KnowledgeGraphEdge(
                source_node=parent_node,
                target_node=kg_node,
                edge_type=KnowledgeGraphEdgeType.has_symbol,
            ))
        
        # Create CONTAINS_SYMBOL edges for nesting
        for rel in hierarchy:
            if 0 <= rel.parent_index < len(symbol_kg_nodes) and 0 <= rel.child_index < len(symbol_kg_nodes):
                edges.append(KnowledgeGraphEdge(
                    source_node=symbol_kg_nodes[rel.parent_index],
                    target_node=symbol_kg_nodes[rel.child_index],
                    edge_type=KnowledgeGraphEdgeType.contains_symbol,
                ))
        
        return next_node_id, nodes, edges

    def _text_file_graph(
        self,
        parent_node: KnowledgeGraphNode,
        file_path: Path,
        next_node_id: int,
    ) -> Tuple[int, Sequence[KnowledgeGraphNode], Sequence[KnowledgeGraphEdge]]:
        """Build knowledge graph for a text/documentation file.
        
        For documentation files (markdown, text, rst), this method splits the content
        into chunks and creates TextNode objects connected via NEXT_CHUNK edges.
        
        Args:
            parent_node: The parent knowledge graph node representing the file.
            file_path: The file to be parsed and chunked.
            next_node_id: The next available node id.
            
        Returns:
            Tuple containing:
                - The next available node id after all nodes are created.
                - A list of all TextNode-related KnowledgeGraphNode objects.
                - A list of all edges (HAS_TEXT, NEXT_CHUNK) for this file.
        """
        nodes: list[KnowledgeGraphNode] = []
        edges: list[KnowledgeGraphEdge] = []
        
        if not isinstance(parent_node.node, FileNode):
            raise ValueError("parent_node must wrap a FileNode")
        
        # Read file content
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Text file not found: {file_path}") from e
        except (IOError, OSError) as e:
            raise RuntimeError(f"Failed to read text file {file_path}: {e}") from e
        
        if not content.strip():
            return next_node_id, nodes, edges
        
        # Split into chunks with overlap
        chunks = self._split_text_into_chunks(content)
        
        prev_kg_node: KnowledgeGraphNode | None = None
        current_line = 0
        
        for chunk_text in chunks:
            # Calculate line numbers for this chunk
            chunk_lines = chunk_text.count("\n")
            start_line = current_line
            end_line = current_line + chunk_lines
            
            text_node = TextNode(
                text=chunk_text,
                start_line=start_line,
                end_line=end_line,
            )
            
            kg_node = KnowledgeGraphNode(
                node_id=str(next_node_id),
                node=text_node,
            )
            nodes.append(kg_node)
            next_node_id += 1
            
            # Create HAS_TEXT edge from file to this text chunk
            edges.append(KnowledgeGraphEdge(
                source_node=parent_node,
                target_node=kg_node,
                edge_type=KnowledgeGraphEdgeType.has_text,
            ))
            
            # Create NEXT_CHUNK edge from previous chunk
            if prev_kg_node is not None:
                edges.append(KnowledgeGraphEdge(
                    source_node=prev_kg_node,
                    target_node=kg_node,
                    edge_type=KnowledgeGraphEdgeType.next_chunk,
                ))
            
            prev_kg_node = kg_node
            # Advance line counter (accounting for overlap)
            current_line = end_line
        
        return next_node_id, nodes, edges
    
    def _split_text_into_chunks(self, text: str) -> list[str]:
        """Split text into chunks with overlap.
        
        Uses a simple character-based splitting with the configured
        chunk_size and chunk_overlap.
        
        Args:
            text: The text content to split.
            
        Returns:
            List of text chunks.
        """
        if len(text) <= self.chunk_size:
            return [text]
        
        chunks: list[str] = []
        start = 0
        
        while start < len(text):
            end = start + self.chunk_size
            
            # Try to break at a natural boundary (newline or space)
            if end < len(text):
                # Look for newline within last 20% of chunk
                boundary_search_start = end - (self.chunk_size // 5)
                newline_pos = text.rfind("\n", boundary_search_start, end)
                if newline_pos > start:
                    end = newline_pos + 1
                else:
                    # Fall back to space
                    space_pos = text.rfind(" ", boundary_search_start, end)
                    if space_pos > start:
                        end = space_pos + 1
            
            chunks.append(text[start:end])
            start = end - self.chunk_overlap
            
            # Avoid getting stuck
            if start <= 0 or start >= len(text):
                break
        
        return chunks
