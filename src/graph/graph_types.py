"""Type definitions for nodes and edges in the knowledge graph."""

import dataclasses
import enum
from typing import TypedDict, Union

@dataclasses.dataclass(frozen=True)
class FileNode:
    """ A node representing a file/dir
    
    Attributes:
        basename: The basename of the file/dir
        relative_path: The relative path from the root path, like 'foo/bar/baz.py'
    """
    
    basename: str
    relative_path: str
    
@dataclasses.dataclass(frozen=True)
class SymbolNode:
    """A node representing a higher-level code symbol (function/class/method/etc.).

    It provides
    stable, human-meaningful anchors for:
      - diff hunk -> symbol mapping (by line spans)
      - semantic relationships (CALLS/IMPORTS/DEFINES/CONTAINS_SYMBOL)

    Attributes:
      symbol_version_id: Snapshot-scoped identifier for this symbol instance (per commit).
      stable_symbol_id: Cross-snapshot logical identifier for this symbol (best-effort).
      kind: High-level kind (function/class/method/interface/struct/etc.).
      name: The symbol name as it appears in code.
      qualified_name: Best-effort qualified name (e.g., module.Class.method).
      language: Language identifier used by Tree-sitter language pack.
      relative_path: File path relative to repo root.
      start_line: Start line number (1-indexed, inclusive).
      end_line: End line number (1-indexed, inclusive).
      signature: Best-effort signature line(s) for the symbol.
      docstring: Optional docstring/comment summary (if available).
      fingerprint: Optional AST-derived fingerprint used for cross-snapshot matching.
    """

    symbol_version_id: str
    stable_symbol_id: str
    kind: str
    name: str
    qualified_name: str | None
    language: str
    relative_path: str
    start_line: int
    end_line: int
    signature: str
    docstring: str | None = None
    fingerprint: str | None = None
    
@dataclasses.dataclass(frozen=True)
class TextNode:
    """ A node representing a text node
    
    Attributes:
        text: the text of the node
        start_line: the starting line number, 0-indexed and inclusive
        end_line: the ending line number, 0-indexed and inclusive
    """
    
    text: str
    start_line: int
    end_line: int
    
@dataclasses.dataclass(frozen=True)
class KnowledgeGraphNode:
    """ A node in the knowledge graph
    
    Attributes:
        node_id: the id of the node
        node_data: the data of the node
    """
    
    node_id: str
    node: Union[FileNode, SymbolNode, TextNode]
    
    def to_neo4j_node(self) -> Union["Neo4jFileNode", "Neo4jSymbolNode", "Neo4jTextNode"]:
        """Convert the KnowledgeGraphNode into a Neo4j node format."""
        match self.node:
            case FileNode():
                return Neo4jFileNode(
                    node_id=self.node_id,
                    basename=self.node.basename,
                    relative_path=self.node.relative_path,
                )
            case SymbolNode():
                return Neo4jSymbolNode(
                    node_id=self.node_id,
                    symbol_version_id=self.node.symbol_version_id,
                    stable_symbol_id=self.node.stable_symbol_id,
                    kind=self.node.kind,
                    name=self.node.name,
                    qualified_name=self.node.qualified_name,
                    language=self.node.language,
                    relative_path=self.node.relative_path,
                    start_line=self.node.start_line,
                    end_line=self.node.end_line,
                    signature=self.node.signature,
                    docstring=self.node.docstring,
                    fingerprint=self.node.fingerprint,
                    
                )
            case TextNode():
                return Neo4jTextNode(
                    node_id=self.node_id,
                    text=self.node.text,
                    start_line=self.node.start_line,
                    end_line=self.node.end_line,
                )
            case _:
                raise ValueError(f"Unknown node type: {type(self.node)}")

    @classmethod
    def from_neo4j_file_node(cls, node: "Neo4jFileNode") -> "KnowledgeGraphNode":
        return cls(
            node_id = node["node_id"],
            node = FileNode(
                basename=node["basename"],
                relative_path=node["relative_path"],
            )
        )
    
    @classmethod
    def from_neo4j_symbol_node(cls, node: "Neo4jSymbolNode") -> "KnowledgeGraphNode":
        return cls(
            node_id = node["node_id"],
            node = SymbolNode(
                symbol_version_id=node["symbol_version_id"],
                stable_symbol_id=node["stable_symbol_id"],
                kind=node["kind"],
                name=node["name"],
                qualified_name=node["qualified_name"],
                language=node["language"],
                relative_path=node["relative_path"],
                start_line=node["start_line"],
                end_line=node["end_line"],
                signature=node["signature"],
                docstring=node["docstring"],
                fingerprint=node.get("fingerprint"),
            )
        )
    
    @classmethod
    def from_neo4j_text_node(cls, node: "Neo4jTextNode") -> "KnowledgeGraphNode":
        return cls(
            node_id = node["node_id"],
            node = TextNode(
                text=node["text"],
                start_line=node["start_line"],
                end_line=node["end_line"],
            )
        )
    
class KnowledgeGraphEdgeType(enum.StrEnum):
    """ The type of an edge in the knowledge graph """
    
    parent_of = "PARENT_OF"
    has_file = "HAS_FILE"
    has_symbol = "HAS_SYMBOL"
    has_text = "HAS_TEXT"
    next_chunk = "NEXT_CHUNK"
    defines = "DEFINES"
    calls = "CALLS"
    imports = "IMPORTS"
    contains_symbol = "CONTAINS_SYMBOL"
    
@dataclasses.dataclass(frozen=True)
class KnowledgeGraphEdge:
    """ An edge in the knowledge graph
    
    Attributes:
        source_node: the source node of the edge
        target_node: the target node of the edge
        edge_type: the type of the edge
    """
    
    source_node: KnowledgeGraphNode
    target_node: KnowledgeGraphNode
    edge_type: KnowledgeGraphEdgeType
    
    def to_neo4j_edge(self) -> Union[
        "Neo4jHasFileEdge",
        "Neo4jHasSymbolEdge",
        "Neo4jHasTextEdge",
        "Neo4jNextChunkEdge",
        "Neo4jDefinesEdge",
        "Neo4jContainsSymbolEdge",
        "Neo4jCallsEdge",
        "Neo4jImportsEdge",
    ]:
        """Convert the KnowledgeGraphEdge into a Neo4j edge format."""
        match self.edge_type:
            case KnowledgeGraphEdgeType.has_file:
                return Neo4jHasFileEdge(
                    source=self.source_node.to_neo4j_node(),
                    target=self.target_node.to_neo4j_node(),
                )
            case KnowledgeGraphEdgeType.has_symbol:
                return Neo4jHasSymbolEdge(
                    source=self.source_node.to_neo4j_node(),
                    target=self.target_node.to_neo4j_node(),
                )
            case KnowledgeGraphEdgeType.has_text:
                return Neo4jHasTextEdge(
                    source=self.source_node.to_neo4j_node(),
                    target=self.target_node.to_neo4j_node(),
                )
            case KnowledgeGraphEdgeType.next_chunk:
                return Neo4jNextChunkEdge(
                    source=self.source_node.to_neo4j_node(),
                    target=self.target_node.to_neo4j_node(),
                )
            case KnowledgeGraphEdgeType.defines:
                return Neo4jDefinesEdge(
                    source=self.source_node.to_neo4j_node(),
                    target=self.target_node.to_neo4j_node(),
                )
            case KnowledgeGraphEdgeType.contains_symbol:
                return Neo4jContainsSymbolEdge(
                    source=self.source_node.to_neo4j_node(),
                    target=self.target_node.to_neo4j_node(),
                )
            case KnowledgeGraphEdgeType.calls:
                return Neo4jCallsEdge(
                    source=self.source_node.to_neo4j_node(),
                    target=self.target_node.to_neo4j_node(),
                )
            case KnowledgeGraphEdgeType.imports:
                return Neo4jImportsEdge(
                    source=self.source_node.to_neo4j_node(),
                    target=self.target_node.to_neo4j_node(),
                )
            case _:
                raise ValueError(f"Unknown edge type: {self.edge_type}")
    
    
class Neo4jMetadataNode(TypedDict):
    codebase_source: str
    local_path: str
    https_url: str
    commit_id: str
    
class Neo4jFileNode(TypedDict):
    node_id: int
    basename: str
    relative_path: str
    
class Neo4jTextNode(TypedDict):
    node_id: int
    text: str
    start_line: int
    end_line: int
    
class Neo4jSymbolNode(TypedDict):
    node_id: int
    symbol_version_id: str
    stable_symbol_id: str
    kind: str
    name: str
    qualified_name: str | None
    language: str
    relative_path: str
    start_line: int
    end_line: int
    signature: str
    docstring: str | None
    fingerprint: str | None
    
class Neo4jHasFileEdge(TypedDict):
    source: Neo4jFileNode
    target: Neo4jFileNode


class Neo4jHasSymbolEdge(TypedDict):
    source: Neo4jFileNode
    target: Neo4jSymbolNode


class Neo4jHasTextEdge(TypedDict):
    source: Neo4jFileNode
    target: Neo4jTextNode
    
class Neo4jNextChunkEdge(TypedDict):
    source: Neo4jTextNode
    target: Neo4jTextNode
    
class Neo4jDefinesEdge(TypedDict):
    source: Neo4jFileNode
    target: Neo4jSymbolNode
    
class Neo4jContainsSymbolEdge(TypedDict):
    source: Neo4jSymbolNode
    target: Neo4jSymbolNode
    
class Neo4jCallsEdge(TypedDict):
    source: Neo4jSymbolNode
    target: Neo4jSymbolNode

class Neo4jImportsEdge(TypedDict):
    source: Neo4jFileNode
    target: Union[Neo4jFileNode, Neo4jSymbolNode]