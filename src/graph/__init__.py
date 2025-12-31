"""Knowledge Graph building and management.

This module provides classes for building and managing knowledge graphs
from repository source code.

Main components:
  - RepoGraphBuilder: Builds complete repository knowledge graphs
  - FileGraphBuilder: Builds file-specific subgraphs (symbols, text chunks)
  - ChunkedSymbolExtractor: Memory-bounded extraction for large files
  - Graph types: FileNode, SymbolNode, TextNode, etc.
"""

from src.parser.extractor.chunked_extractor import ChunkedSymbolExtractor, SymbolBatch
from src.graph.file_graph_builder import FileGraphBuilder
from src.graph.graph_types import (
    FileNode,
    KnowledgeGraphEdge,
    KnowledgeGraphEdgeType,
    KnowledgeGraphNode,
    SymbolNode,
    TextNode,
)
from src.graph.repo_graph_builder import RepoGraphBuilder

__all__ = [
    "ChunkedSymbolExtractor",
    "FileGraphBuilder",
    "FileNode",
    "KnowledgeGraphEdge",
    "KnowledgeGraphEdgeType",
    "KnowledgeGraphNode",
    "RepoGraphBuilder",
    "SymbolBatch",
    "SymbolNode",
    "TextNode",
]
