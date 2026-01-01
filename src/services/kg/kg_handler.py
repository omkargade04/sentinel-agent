"""Knowledge Graph Handler - Low-level Neo4j operations.

This module provides low-level operations for persisting knowledge graph
nodes and edges to Neo4j. It handles constraint/index creation, batch upserts,
and cleanup of stale nodes.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from neo4j import AsyncDriver

from src.graph.graph_types import (
    KnowledgeGraphEdge,
    KnowledgeGraphEdgeType,
    KnowledgeGraphNode,
    Neo4jFileNode,
    Neo4jSymbolNode,
    Neo4jTextNode,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


async def init_database(driver: AsyncDriver, database: str = "neo4j") -> None:
    """Create constraints and indexes for KG nodes.

    This function should be called once during application startup to ensure
    the required database schema elements exist. All operations are idempotent
    (IF NOT EXISTS).

    Creates:
        - Uniqueness constraint on (:KGNode {repo_id, node_id})
        - Index on (:KGNode {repo_id}) for filtering by repository
        - Index on (:KGNode {last_indexed_at}) for cleanup queries

    Args:
        driver: Neo4j AsyncDriver instance
        database: Name of the Neo4j database (default: "neo4j")

    Raises:
        neo4j.exceptions.Neo4jError: If constraint/index creation fails
    """
    logger.info("Initializing Neo4j database schema for KGNode")

    async with driver.session(database=database) as session:
        # Create uniqueness constraint on repo_id + node_id combination
        # This ensures each node is unique within a repository
        logger.debug("Creating uniqueness constraint on KGNode (repo_id, node_id)")
        await session.run(
            """
            CREATE CONSTRAINT kg_node_unique IF NOT EXISTS
            FOR (n:KGNode)
            REQUIRE (n.repo_id, n.node_id) IS UNIQUE
            """
        )

        # Create index on repo_id for efficient repository-scoped queries
        logger.debug("Creating index on KGNode (repo_id)")
        await session.run(
            """
            CREATE INDEX kg_node_repo_id IF NOT EXISTS
            FOR (n:KGNode)
            ON (n.repo_id)
            """
        )

        # Create index on last_indexed_at for efficient cleanup queries
        logger.debug("Creating index on KGNode (last_indexed_at)")
        await session.run(
            """
            CREATE INDEX kg_node_last_indexed_at IF NOT EXISTS
            FOR (n:KGNode)
            ON (n.last_indexed_at)
            """
        )

    logger.info("Neo4j database schema initialization complete")

async def batch_upsert_nodes(
    driver: AsyncDriver, 
    nodes: list[KnowledgeGraphNode], 
    repo_id: str, 
    database: str = "neo4j"
) -> None:
    """Batch upsert nodes using UNWIND pattern with ON CREATE/ON MATCH.
    
    This function efficiently upserts a batch of knowledge graph nodes to Neo4j.
    All nodes are tagged with the repository ID and get their `last_indexed_at`
    timestamp refreshed (even if unchanged), ensuring cleanup queries can
    accurately identify stale nodes.
    
    The function handles three node types:
    - FileNode: Labeled as :KGNode:FileNode
    - SymbolNode: Labeled as :KGNode:SymbolNode  
    - TextNode: Labeled as :KGNode:TextNode
    
    Args:
        driver: Neo4j AsyncDriver instance
        nodes: List of KnowledgeGraphNode objects to upsert
        repo_id: Repository identifier (required for all nodes)
        database: Name of the Neo4j database (default: "neo4j")
    
    Raises:
        neo4j.exceptions.Neo4jError: If the batch upsert operation fails
        ValueError: If a node type is not recognized
    """
    
    if not nodes:
        logger.debug("No nodes to upsert")
        return
    
    logger.info(f"Upserting {len(nodes)} nodes for repo_id={repo_id}")

    # Convert nodes to Neo4j node format and prepare for batch data
    batch_data: list[dict[str, Any]] = []
    current_time = datetime.now(timezone.utc)
    
    for kg_node in nodes:
        neo4j_node = kg_node.to_neo4j_node()
        
        # Determine node type and labels
        node_type: str
        node_properties: dict[str, Any]
        
        if isinstance(neo4j_node, Neo4jFileNode):
            node_type = "file"
            node_properties = {
                "node_id": str(kg_node.node_id),  # Ensure string type
                "repo_id": repo_id,
                "basename": neo4j_node["basename"],
                "relative_path": neo4j_node["relative_path"],
                "node_type": node_type,
                "last_indexed_at": current_time,
            }
        elif isinstance(neo4j_node, Neo4jSymbolNode):
            node_type = "symbol"
            node_properties = {
                "node_id": str(kg_node.node_id),
                "repo_id": repo_id,
                "symbol_version_id": neo4j_node["symbol_version_id"],
                "stable_symbol_id": neo4j_node["stable_symbol_id"],
                "kind": neo4j_node["kind"],
                "name": neo4j_node["name"],
                "qualified_name": neo4j_node.get("qualified_name"),
                "language": neo4j_node["language"],
                "relative_path": neo4j_node["relative_path"],
                "start_line": neo4j_node["start_line"],
                "end_line": neo4j_node["end_line"],
                "signature": neo4j_node["signature"],
                "docstring": neo4j_node.get("docstring"),
                "fingerprint": neo4j_node.get("fingerprint"),
                "node_type": node_type,
                "last_indexed_at": current_time,
            }
        elif isinstance(neo4j_node, Neo4jTextNode):
            node_type = "text"
            node_properties = {
                "node_id": str(kg_node.node_id),
                "repo_id": repo_id,
                "text": neo4j_node["text"],
                "start_line": neo4j_node["start_line"],
                "end_line": neo4j_node["end_line"],
                "node_type": node_type,
                "last_indexed_at": current_time,
            }
        else:
            raise ValueError(f"Unknown node type: {type(neo4j_node)}")
        
        batch_data.append(node_properties)
        
    # Build dynamic label based on node type
    # We'll process nodes in batches by type for efficiency
    nodes_by_type: dict[str, list[dict[str, Any]]] = {}
    for node_data in batch_data:
        node_type = node_data["node_type"]
        if node_type not in nodes_by_type:
            nodes_by_type[node_type] = []
        nodes_by_type[node_type].append(node_data)
        
    # Process each node type in separate batches
    async with driver.session(database=database) as session:
        for node_type, type_nodes in nodes_by_type.items():
            label = node_type.capitalize() + "Node"  # FileNode, SymbolNode, TextNode
            
            # Build the MERGE query with dynamic properties
            # Cypher syntax: ON CREATE SET and ON MATCH SET are part of the same MERGE statement
            if node_type == "file":
                query = f"""
                UNWIND $nodes AS node
                MERGE (n:KGNode:{label} {{repo_id: node.repo_id, node_id: node.node_id}})
                ON CREATE SET
                    n.basename = node.basename,
                    n.relative_path = node.relative_path,
                    n.node_type = node.node_type,
                    n.last_indexed_at = node.last_indexed_at
                ON MATCH SET
                    n.basename = node.basename,
                    n.relative_path = node.relative_path,
                    n.node_type = node.node_type,
                    n.last_indexed_at = node.last_indexed_at
                """
            elif node_type == "symbol":
                query = f"""
                UNWIND $nodes AS node
                MERGE (n:KGNode:{label} {{repo_id: node.repo_id, node_id: node.node_id}})
                ON CREATE SET
                    n.symbol_version_id = node.symbol_version_id,
                    n.stable_symbol_id = node.stable_symbol_id,
                    n.kind = node.kind,
                    n.name = node.name,
                    n.qualified_name = node.qualified_name,
                    n.language = node.language,
                    n.relative_path = node.relative_path,
                    n.start_line = node.start_line,
                    n.end_line = node.end_line,
                    n.signature = node.signature,
                    n.docstring = node.docstring,
                    n.fingerprint = node.fingerprint,
                    n.node_type = node.node_type,
                    n.last_indexed_at = node.last_indexed_at
                ON MATCH SET
                    n.symbol_version_id = node.symbol_version_id,
                    n.stable_symbol_id = node.stable_symbol_id,
                    n.kind = node.kind,
                    n.name = node.name,
                    n.qualified_name = node.qualified_name,
                    n.language = node.language,
                    n.relative_path = node.relative_path,
                    n.start_line = node.start_line,
                    n.end_line = node.end_line,
                    n.signature = node.signature,
                    n.docstring = node.docstring,
                    n.fingerprint = node.fingerprint,
                    n.node_type = node.node_type,
                    n.last_indexed_at = node.last_indexed_at
                """
            elif node_type == "text":
                query = f"""
                UNWIND $nodes AS node
                MERGE (n:KGNode:{label} {{repo_id: node.repo_id, node_id: node.node_id}})
                ON CREATE SET
                    n.text = node.text,
                    n.start_line = node.start_line,
                    n.end_line = node.end_line,
                    n.node_type = node.node_type,
                    n.last_indexed_at = node.last_indexed_at
                ON MATCH SET
                    n.text = node.text,
                    n.start_line = node.start_line,
                    n.end_line = node.end_line,
                    n.node_type = node.node_type,
                    n.last_indexed_at = node.last_indexed_at
                """
            else:
                raise ValueError(f"Unknown node type: {node_type}")
            
            logger.debug(f"Upserting {len(type_nodes)} {node_type} nodes")
            result = await session.run(query, nodes=type_nodes)
            await result.consume()  # Consume result to ensure query completes
    
    logger.info(f"Successfully upserted {len(nodes)} nodes for repo_id={repo_id}")
    
async def batch_upsert_edges(
    driver: AsyncDriver, 
    edges: list[KnowledgeGraphEdge], 
    repo_id: str, 
    database: str = "neo4j"
) -> None:
    """Batch upsert edges using UNWIND pattern with MERGE.
    
    This function efficiently upserts a batch of knowledge graph edges to Neo4j.
    All edges are tagged with the repository ID and relationships are created
    between existing nodes using MERGE semantics (idempotent).
    
    The function handles all edge types:
    - PARENT_OF: FileNode -> FileNode (directory hierarchy)
    - HAS_FILE: FileNode -> FileNode (file containment)
    - HAS_SYMBOL: FileNode -> SymbolNode (file contains symbol)
    - HAS_TEXT: FileNode -> TextNode (file contains text chunk)
    - NEXT_CHUNK: TextNode -> TextNode (sequential text chunks)
    - DEFINES: FileNode -> SymbolNode (file defines symbol)
    - CALLS: SymbolNode -> SymbolNode (function/method calls)
    - IMPORTS: FileNode -> FileNode | SymbolNode (import relationships)
    - CONTAINS_SYMBOL: SymbolNode -> SymbolNode (symbol containment)
    
    Args:
        driver: Neo4j AsyncDriver instance
        edges: List of KnowledgeGraphEdge objects to upsert
        repo_id: Repository identifier (required for all edges)
        database: Name of the Neo4j database (default: "neo4j")
    
    Raises:
        neo4j.exceptions.Neo4jError: If the batch upsert operation fails
        ValueError: If an edge type is not recognized
    """
    if not edges:
        logger.debug("No edges to upsert")
        return

    logger.info(f"Upserting {len(edges)} edges for repo_id={repo_id}")
    
    # Group edges by type and prepare batch data
    edges_by_type: dict[KnowledgeGraphEdgeType, list[dict[str, Any]]] = {}
    
    for kg_edge in edges:
        edge_type = kg_edge.edge_type
        
        # Extract source and target node ids
        source_node_id = str(kg_edge.source_node.node_id)
        target_node_id = str(kg_edge.target_node.node_id)
        
        # Build edge data dict
        edge_data = {
            "repo_id": repo_id,
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
        }
        
        if edge_type not in edges_by_type:
            edges_by_type[edge_type] = []
        edges_by_type[edge_type].append(edge_data)
        
    # Process each edge type in separate batches
    async with driver.session(database=database) as session:
        for edge_type, type_edges in edges_by_type.items():
            
            # Map edge type enum to Cypher relationship type name
            relationship_type = edge_type.value  # e.g., "HAS_FILE", "CALLS", etc.
            
            # Build the MERGE query
            # All edges get repo_id property; CALLS/IMPORTS can optionally get confidence
            if edge_type in (KnowledgeGraphEdgeType.calls, KnowledgeGraphEdgeType.imports):
                query = f"""
                UNWIND $edges AS edge
                MATCH (source:KGNode {{repo_id: edge.repo_id, node_id: edge.source_node_id}})
                MATCH (target:KGNode {{repo_id: edge.repo_id, node_id: edge.target_node_id}})
                MERGE (source)-[r:{relationship_type}]->(target)
                ON CREATE SET
                    r.repo_id = edge.repo_id
                ON MATCH SET
                    r.repo_id = edge.repo_id
            """
            else:
                query = f"""
                UNWIND $edges AS edge
                MATCH (source:KGNode {{repo_id: edge.repo_id, node_id: edge.source_node_id}})
                MATCH (target:KGNode {{repo_id: edge.repo_id, node_id: edge.target_node_id}})
                MERGE (source)-[r:{relationship_type}]->(target)
                ON CREATE SET
                    r.repo_id = edge.repo_id
                ON MATCH SET
                    r.repo_id = edge.repo_id
                """
            logger.debug(f"Upserting {len(type_edges)} {edge_type.value} edges")
            result = await session.run(query, edges=type_edges)
            await result.consume()  # Consume result to ensure query completes
    
    logger.info(f"Successfully upserted {len(edges)} edges for repo_id={repo_id}")


async def cleanup_stale_nodes(
    driver: AsyncDriver,
    repo_id: str,
    ttl_days: int = 7,
    database: str = "neo4j"
) -> int:
    """Delete nodes that haven't been seen for TTL days.
    
    This function removes knowledge graph nodes that haven't been refreshed
    during re-indexing for the specified TTL period. These nodes represent
    code symbols/files that were deleted from the codebase and are no longer
    present in the latest commit.
    
    The cleanup uses `DETACH DELETE` to remove nodes and all their relationships,
    ensuring no orphaned edges remain in the graph.
    
    Args:
        driver: Neo4j AsyncDriver instance
        repo_id: Repository identifier to scope cleanup operation
        ttl_days: Number of days since last_indexed_at before node is considered stale (default: 7)
        database: Name of the Neo4j database (default: "neo4j")
    
    Returns:
        Number of nodes deleted
    
    Raises:
        neo4j.exceptions.Neo4jError: If the cleanup operation fails
    """
    logger.info(f"Cleaning up stale nodes for repo_id={repo_id} (TTL: {ttl_days} days)")
    
    async with driver.session(database=database) as session:
        # Build Cypher query to delete nodes older than TTL
        # DETACH DELETE removes the node and all its relationships
        query = """
        MATCH (n:KGNode {repo_id: $repo_id})
        WHERE n.last_indexed_at < datetime() - duration({days: $ttl_days})
        DETACH DELETE n
        RETURN count(n) as deleted_count
        """
        
        logger.debug(f"Executing cleanup query for repo_id={repo_id}, ttl_days={ttl_days}")
        result = await session.run(
            query,
            repo_id=repo_id,
            ttl_days=ttl_days
        )
        
        # Extract the deleted count from the result
        record = await result.single()
        deleted_count = record["deleted_count"] if record else 0
        
        logger.info(
            f"Cleanup complete for repo_id={repo_id}: "
            f"deleted {deleted_count} stale nodes (TTL: {ttl_days} days)"
        )
        
        return deleted_count