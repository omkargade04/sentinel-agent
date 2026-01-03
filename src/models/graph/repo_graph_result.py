from dataclasses import dataclass, field
from src.graph.helpers.graph_types import (
    FileNode,
    KnowledgeGraphEdge,
    KnowledgeGraphEdgeType,
    KnowledgeGraphNode,
)
from src.models.graph.indexing_stats import IndexingStats

@dataclass
class RepoGraphResult:
    """Result of building a repository knowledge graph.
    
    Attributes:
        root_node: The root FileNode representing the repository root directory.
        nodes: All KnowledgeGraphNode objects (files, directories, symbols, text chunks).
        edges: All KnowledgeGraphEdge objects connecting the nodes.
        stats: Statistics about the indexing process.
    """
    root_node: KnowledgeGraphNode
    nodes: list[KnowledgeGraphNode]
    edges: list[KnowledgeGraphEdge]
    stats: "IndexingStats"