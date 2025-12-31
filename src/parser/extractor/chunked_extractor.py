"""Memory-bounded symbol extraction for large files.

This module provides chunked symbol extraction to handle large files without
excessive memory consumption. The key pattern is:
  1. Parse the full file AST (unavoidable for complete parsing)
  2. Extract and yield symbols in batches
  3. Each batch is persisted immediately
  4. Batch memory is released after persistence
  5. Periodic garbage collection prevents memory buildup

This allows processing very large files (>1MB) that would otherwise cause
memory issues if all symbols were accumulated before persistence.
"""

from __future__ import annotations

import gc
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Sequence

from src.graph.graph_types import (
    FileNode,
    KnowledgeGraphEdge,
    KnowledgeGraphEdgeType,
    KnowledgeGraphNode,
    SymbolNode,
)
from src.graph.utils import (
    generate_ast_fingerprint_from_types,
    generate_stable_symbol_id,
    generate_symbol_version_id,
)
from src.parser import tree_sitter_parser
from src.parser.extractor import ExtractedSymbol, get_symbol_extractor

if TYPE_CHECKING:
    from tree_sitter import Tree


logger = logging.getLogger(__name__)


@dataclass
class SymbolBatch:
    """A batch of symbols ready for persistence.
    
    Attributes:
        nodes: List of KnowledgeGraphNode objects (each wrapping a SymbolNode)
        edges: List of KnowledgeGraphEdge objects for this batch
        batch_number: Sequential batch number for logging/tracking
        symbols_in_batch: Number of symbols in this batch
    """
    nodes: list[KnowledgeGraphNode]
    edges: list[KnowledgeGraphEdge]
    batch_number: int
    symbols_in_batch: int


@dataclass
class ChunkedExtractionResult:
    """Final result after processing all batches.
    
    Attributes:
        total_symbols: Total number of symbols extracted
        total_batches: Number of batches processed
        next_node_id: Updated next_node_id after all processing
        all_symbol_nodes: List of all symbol KG nodes (for hierarchy building)
        errors: Any errors encountered during extraction
    """
    total_symbols: int = 0
    total_batches: int = 0
    next_node_id: int = 0
    all_symbol_nodes: list[KnowledgeGraphNode] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ChunkedSymbolExtractor:
    """Extract symbols from large files in memory-bounded batches.
    
    This extractor is designed for large code files where accumulating all
    symbols at once would cause memory issues. It parses the file once,
    then yields symbols in configurable batch sizes.
    
    Memory pattern:
      - Parse AST (held temporarily in tree-sitter's memory)
      - Extract symbols using language-specific extractor
      - Yield batches of N symbols
      - Caller persists batch to Neo4j
      - Batch memory released
      - Periodic GC triggered
      - Repeat until all symbols processed
      
    Example usage:
        extractor = ChunkedSymbolExtractor(batch_size=50)
        for batch in extractor.extract_symbols_chunked(...):
            neo4j_writer.write_batch(batch)
            # batch memory automatically released
    """
    
    def __init__(
        self,
        batch_size: int = 50,
        force_gc_interval: int = 5,
    ):
        """Initialize the chunked extractor.
        
        Args:
            batch_size: Number of symbols per batch. Smaller batches = lower
                memory but more frequent writes. Default 50 is a good balance.
            force_gc_interval: Force garbage collection every N batches.
                This helps prevent memory buildup from fragmentation.
        """
        self.batch_size = batch_size
        self.force_gc_interval = force_gc_interval
        self._batches_processed = 0
    
    def extract_symbols_chunked(
        self,
        file_path: Path,
        parent_kg_node: KnowledgeGraphNode,
        repo_id: str,
        commit_sha: str | None,
        next_node_id: int,
    ) -> Iterator[SymbolBatch]:
        """Parse file and yield symbol batches one at a time.
        
        This method parses the file once with tree-sitter, extracts all symbols
        using the language-specific extractor, then yields them in batches.
        Each batch can be immediately persisted to Neo4j, after which the
        batch memory is released.
        
        Note: We still need to hold all ExtractedSymbols temporarily to build
        the symbol hierarchy (parent-child relationships). However, we batch
        the conversion to KnowledgeGraphNodes and the persistence.
        
        Args:
            file_path: Path to the source file
            parent_kg_node: Parent KG node (FileNode) that contains this file
            repo_id: Repository ID for stable symbol ID generation
            commit_sha: Commit SHA for version ID generation
            next_node_id: Starting node ID (will be incremented)
            
        Yields:
            SymbolBatch objects containing nodes and edges ready for persistence
            
        Raises:
            ValueError: If parent_kg_node doesn't wrap a FileNode
            RuntimeError: If file parsing or reading fails
        """
        # Validate parent node
        if not isinstance(parent_kg_node.node, FileNode):
            raise ValueError("parent_kg_node must wrap a FileNode")
        
        file_node: FileNode = parent_kg_node.node
        
        # Step 1: Parse the file with Tree-sitter
        try:
            tree, language = tree_sitter_parser.get_parser(file_path)
        except tree_sitter_parser.UnsupportedLanguageError:
            logger.debug(f"Unsupported language for {file_path}, skipping")
            return
        except tree_sitter_parser.ParseError as e:
            raise RuntimeError(f"Failed to parse file {file_path}: {e}") from e
        
        # Validate parse result
        if tree.root_node.has_error or tree.root_node.child_count == 0:
            logger.debug(f"Parse error or empty file: {file_path}")
            return
        
        # Step 2: Get language-specific symbol extractor
        extractor = get_symbol_extractor(language)
        if not extractor:
            logger.debug(f"No symbol extractor for language {language}")
            return
        
        # Step 3: Read file content
        try:
            file_content = file_path.read_bytes()
        except (IOError, OSError) as e:
            raise RuntimeError(f"Failed to read file {file_path}: {e}") from e
        
        # Step 4: Extract ALL symbols (we need the full list for hierarchy)
        # This is the memory-intensive part we can't avoid
        extracted_symbols = extractor.extract_symbols(tree, file_path, file_content)
        
        if not extracted_symbols:
            # Release resources
            del tree, file_content
            gc.collect()
            return
        
        # Step 5: Build hierarchy BEFORE batching (requires full symbol list)
        hierarchy = extractor.build_symbol_hierarchy(extracted_symbols)
        
        # Step 6: Yield symbols in batches
        current_batch_nodes: list[KnowledgeGraphNode] = []
        current_batch_edges: list[KnowledgeGraphEdge] = []
        batch_number = 0
        
        # Track all symbol KG nodes for hierarchy edges (we build these after)
        all_symbol_kg_nodes: list[KnowledgeGraphNode] = []
        
        for idx, extracted in enumerate(extracted_symbols):
            # Generate fingerprint from AST node types
            fingerprint = None
            if extracted.node_types:
                fingerprint = generate_ast_fingerprint_from_types(extracted.node_types)
            
            # Generate dual IDs
            symbol_version_id = generate_symbol_version_id(
                commit_sha=commit_sha,
                relative_path=file_node.relative_path,
                kind=extracted.kind,
                name=extracted.name,
                qualified_name=extracted.qualified_name,
                start_line=extracted.start_line,
                end_line=extracted.end_line,
            )
            
            stable_symbol_id = generate_stable_symbol_id(
                repo_id=repo_id,
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
            
            current_batch_nodes.append(kg_node)
            all_symbol_kg_nodes.append(kg_node)
            next_node_id += 1
            
            # Create HAS_SYMBOL edge from file to symbol
            current_batch_edges.append(KnowledgeGraphEdge(
                source_node=parent_kg_node,
                target_node=kg_node,
                edge_type=KnowledgeGraphEdgeType.has_symbol,
            ))
            
            # When batch is full, yield it
            if len(current_batch_nodes) >= self.batch_size:
                yield SymbolBatch(
                    nodes=current_batch_nodes,
                    edges=current_batch_edges,
                    batch_number=batch_number,
                    symbols_in_batch=len(current_batch_nodes),
                )
                
                # Clear local references (memory released)
                current_batch_nodes = []
                current_batch_edges = []
                batch_number += 1
                self._batches_processed += 1
                
                # Periodic GC
                if self._batches_processed % self.force_gc_interval == 0:
                    gc.collect()
        
        # Yield remaining symbols
        if current_batch_nodes:
            yield SymbolBatch(
                nodes=current_batch_nodes,
                edges=current_batch_edges,
                batch_number=batch_number,
                symbols_in_batch=len(current_batch_nodes),
            )
            batch_number += 1
        
        # Step 7: Yield hierarchy edges as a separate batch
        if hierarchy and all_symbol_kg_nodes:
            hierarchy_edges: list[KnowledgeGraphEdge] = []
            
            for rel in hierarchy:
                if 0 <= rel.parent_index < len(all_symbol_kg_nodes) and \
                   0 <= rel.child_index < len(all_symbol_kg_nodes):
                    hierarchy_edges.append(KnowledgeGraphEdge(
                        source_node=all_symbol_kg_nodes[rel.parent_index],
                        target_node=all_symbol_kg_nodes[rel.child_index],
                        edge_type=KnowledgeGraphEdgeType.contains_symbol,
                    ))
            
            if hierarchy_edges:
                yield SymbolBatch(
                    nodes=[],  # No new nodes, just edges
                    edges=hierarchy_edges,
                    batch_number=batch_number,
                    symbols_in_batch=0,
                )
        
        # Step 8: Final cleanup
        del tree, file_content, extracted_symbols, hierarchy
        gc.collect()
        
        logger.debug(
            f"Chunked extraction complete for {file_path}: "
            f"{len(all_symbol_kg_nodes)} symbols in {batch_number + 1} batches"
        )
    
    def get_total_batches_processed(self) -> int:
        """Return total batches processed across all files."""
        return self._batches_processed
    
    def reset_stats(self) -> None:
        """Reset internal statistics."""
        self._batches_processed = 0
