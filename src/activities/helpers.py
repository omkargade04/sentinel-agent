from src.graph.helpers.graph_types import (
    KnowledgeGraphNode,
    KnowledgeGraphEdge,
    KnowledgeGraphEdgeType,
    FileNode,
    SymbolNode,
    TextNode,
)
from src.utils.logging import get_logger
logger = get_logger(__name__)

# =============================================================================
# Deserialization helpers for Temporal activity data
# =============================================================================
# Temporal serializes Python dataclasses to plain dicts when passing between
# activities. These helpers reconstruct the proper objects with their methods.

def _deserialize_inner_node(node_dict: dict) -> FileNode | SymbolNode | TextNode:
    """Reconstruct the inner node (FileNode/SymbolNode/TextNode) from a dict."""
    # SymbolNode has 'symbol_version_id' field
    if "symbol_version_id" in node_dict:
        return SymbolNode(**node_dict)
    # TextNode has 'text' field but not 'basename'
    elif "text" in node_dict:
        return TextNode(**node_dict)
    # FileNode has 'basename' and 'relative_path'
    else:
        return FileNode(**node_dict)


def _deserialize_node(node_dict: dict) -> KnowledgeGraphNode:
    """Reconstruct KnowledgeGraphNode from serialized dict."""
    return KnowledgeGraphNode(
        node_id=node_dict["node_id"],
        node=_deserialize_inner_node(node_dict["node"]),
    )


def _deserialize_edge(edge_dict: dict) -> KnowledgeGraphEdge:
    """Reconstruct KnowledgeGraphEdge from serialized dict."""
    return KnowledgeGraphEdge(
        edge_type=KnowledgeGraphEdgeType(edge_dict["edge_type"]),
        source_node=_deserialize_node(edge_dict["source_node"]),
        target_node=_deserialize_node(edge_dict["target_node"]),
    )