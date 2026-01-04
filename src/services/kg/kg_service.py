"""Knowledge Graph Service - High-level business logic for KG persistence.

This module provides high-level operations for persisting knowledge graphs to Neo4j.
It orchestrates low-level handler operations and provides clean APIs for Temporal
activities with proper error handling and statistics tracking.
"""

from __future__ import annotations

from neo4j import AsyncDriver

from src.graph.helpers.graph_types import KnowledgeGraphEdge, KnowledgeGraphNode
from src.models.graph.indexing_stats import PersistenceStats
from src.services.kg import kg_handler
from src.utils.logging import get_logger

logger = get_logger(__name__)


class KnowledgeGraphService:
    """High-level service for knowledge graph persistence operations.
    
    This service orchestrates low-level Neo4j operations and provides clean APIs
    for Temporal activities. It handles transaction boundaries, error handling,
    and tracks persistence statistics.
    
    Attributes:
        driver: Neo4j AsyncDriver instance
        database: Name of the Neo4j database (default: "neo4j")
    """

    def __init__(
        self,
        driver: AsyncDriver,
        database: str = "neo4j"
    ):
        """Initialize the KnowledgeGraphService.
        
        Args:
            driver: Neo4j AsyncDriver instance
            database: Name of the Neo4j database (default: "neo4j")
        """
        self.driver = driver
        self.database = database
        logger.debug(f"KnowledgeGraphService initialized with database={database}")

    async def persist_kg(
        self,
        repo_id: str,
        github_repo_id: int,
        nodes: list[KnowledgeGraphNode],
        edges: list[KnowledgeGraphEdge],
    ) -> PersistenceStats:
        """Persist a complete knowledge graph for a repository.
        
        This method orchestrates the batch upsert of nodes and edges to Neo4j.
        It tracks statistics about created/updated nodes and edges by comparing
        counts before and after the upsert operations.
        
        Args:
            repo_id: Repository identifier
            gtihub_repo_id: Github Repo ID
            nodes: List of knowledge graph nodes to persist
            edges: List of knowledge graph edges to persist
            
        Returns:
            PersistenceStats containing counts of created/updated nodes and edges
            
        Raises:
            neo4j.exceptions.Neo4jError: If persistence operations fail
            Exception: If any unexpected error occurs during persistence
        """
        logger.info(
            f"Persisting knowledge graph for repo_id={repo_id}: "
            f"{len(nodes)} nodes, {len(edges)} edges"
        )
        
        stats = PersistenceStats()
        
        try:
            # Get initial counts to calculate created vs updated
            initial_node_count = await self._count_nodes(repo_id)
            initial_edge_count = await self._count_edges(repo_id)
            
            # Batch upsert nodes (all existing symbols get refreshed timestamps)
            if nodes:
                await kg_handler.batch_upsert_nodes(
                    self.driver,
                    nodes,
                    repo_id,
                    self.database
                )
                logger.debug(f"Upserted {len(nodes)} nodes for repo_id={repo_id}")
            
            # Batch upsert edges
            if edges:
                await kg_handler.batch_upsert_edges(
                    self.driver,
                    edges,
                    repo_id,
                    self.database
                )
                logger.debug(f"Upserted {len(edges)} edges for repo_id={repo_id}")
            
            # Get final counts to calculate statistics
            final_node_count = await self._count_nodes(repo_id)
            final_edge_count = await self._count_edges(repo_id)
            
            # Calculate created vs updated
            # Note: This is an approximation - we can't perfectly distinguish
            # created vs updated without tracking individual node IDs
            nodes_created = max(0, final_node_count - initial_node_count)
            nodes_updated = max(0, len(nodes) - nodes_created)
            
            edges_created = max(0, final_edge_count - initial_edge_count)
            edges_updated = max(0, len(edges) - edges_created)
            
            stats.nodes_created = nodes_created
            stats.nodes_updated = nodes_updated
            stats.edges_created = edges_created
            stats.edges_updated = edges_updated
            
            logger.info(
                f"Persistence complete for repo_id={repo_id}: "
                f"nodes_created={nodes_created}, nodes_updated={nodes_updated}, "
                f"edges_created={edges_created}, edges_updated={edges_updated}"
            )
            
        except Exception as e:
            error_msg = f"Failed to persist knowledge graph for repo_id={repo_id}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            stats.errors.append(error_msg)
            raise
        
        return stats

    async def cleanup_stale_nodes(
        self,
        repo_id: str,
        ttl_days: int = 30,
    ) -> int:
        """Clean up nodes deleted from codebase after TTL.
        
        This method removes knowledge graph nodes that haven't been refreshed
        during re-indexing for the specified TTL period. These nodes represent
        code symbols/files that were deleted from the codebase.
        
        Args:
            repo_id: Repository identifier to scope cleanup operation
            ttl_days: Number of days since last_indexed_at before node is considered
                     stale (default: 30)
            
        Returns:
            Number of nodes deleted
            
        Raises:
            neo4j.exceptions.Neo4jError: If cleanup operation fails
            Exception: If any unexpected error occurs during cleanup
        """
        logger.info(
            f"Cleaning up stale nodes for repo_id={repo_id} (TTL: {ttl_days} days)"
        )
        
        try:
            deleted_count = await kg_handler.cleanup_stale_nodes(
                self.driver,
                repo_id,
                ttl_days,
                self.database
            )
            
            logger.info(
                f"Cleanup complete for repo_id={repo_id}: "
                f"deleted {deleted_count} stale nodes"
            )
            
            return deleted_count
            
        except Exception as e:
            error_msg = (
                f"Failed to cleanup stale nodes for repo_id={repo_id}: {str(e)}"
            )
            logger.error(error_msg, exc_info=True)
            raise

    async def clear_repo_graph(
        self,
        repo_id: str,
    ) -> int:
        """Delete all nodes/edges for a repository (nuclear option).
        
        This method performs a complete deletion of all knowledge graph nodes
        and edges for the specified repository. Use with caution as this operation
        cannot be undone.
        
        Args:
            repo_id: Repository identifier to delete
            
        Returns:
            Number of nodes deleted
            
        Raises:
            neo4j.exceptions.Neo4jError: If deletion operation fails
            Exception: If any unexpected error occurs during deletion
        """
        logger.warning(
            f"Clearing entire knowledge graph for repo_id={repo_id} "
            f"(nuclear option - cannot be undone)"
        )
        
        try:
            async with self.driver.session(database=self.database) as session:
                # DETACH DELETE removes nodes and all their relationships
                query = """
                MATCH (n:KGNode {repo_id: $repo_id})
                DETACH DELETE n
                RETURN count(n) as deleted_count
                """
                
                logger.debug(f"Executing full graph deletion for repo_id={repo_id}")
                result = await session.run(query, repo_id=repo_id)
                
                # Extract the deleted count from the result
                record = await result.single()
                deleted_count = record["deleted_count"] if record else 0
                
                logger.info(
                    f"Graph cleared for repo_id={repo_id}: "
                    f"deleted {deleted_count} nodes"
                )
                
                return deleted_count
                
        except Exception as e:
            error_msg = (
                f"Failed to clear graph for repo_id={repo_id}: {str(e)}"
            )
            logger.error(error_msg, exc_info=True)
            raise

    async def _count_nodes(self, repo_id: str) -> int:
        """Count total nodes for a repository.
        
        Args:
            repo_id: Repository identifier
            
        Returns:
            Total number of nodes for the repository
        """
        async with self.driver.session(database=self.database) as session:
            query = """
            MATCH (n:KGNode {repo_id: $repo_id})
            RETURN count(n) as node_count
            """
            result = await session.run(query, repo_id=repo_id)
            record = await result.single()
            return record["node_count"] if record else 0

    async def _count_edges(self, repo_id: str) -> int:
        """Count total edges for a repository.
        
        Args:
            repo_id: Repository identifier
            
        Returns:
            Total number of edges for the repository
        """
        async with self.driver.session(database=self.database) as session:
            query = """
            MATCH (source:KGNode {repo_id: $repo_id})-[r]->(target:KGNode {repo_id: $repo_id})
            RETURN count(r) as edge_count
            """
            result = await session.run(query, repo_id=repo_id)
            record = await result.single()
            return record["edge_count"] if record else 0