from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from neo4j import AsyncDriver

from src.services.kg.connection_pool import Neo4jConnectionPool, get_connection_pool
from src.services.kg.query_builder import KGQueryBuilder
from src.services.kg.performance_monitor import get_performance_monitor
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class KGQueryLimits:
    max_symbol_matches_per_seed: int = 10
    max_neighbors_per_seed: int = 20
    max_import_neighbors_per_file: int = 10
    max_text_nodes_per_prefix: int = 10
    

class KGQueryService:
    """
    Optimized Neo4j query service for PR-review context retrieval.

    Features:
    - Connection pooling for improved performance
    - Parameterized queries for better query plan caching
    - Performance monitoring and error handling

    Notes about schema (as persisted by src/services/kg/kg_handler.py):
    - Nodes use :KGNode plus a concrete label (SymbolNode/FileNode/TextNode).
    - Common properties: repo_id, node_id, commit_sha
    - SymbolNode properties: relative_path, name, kind, qualified_name, fingerprint, start_line, end_line, signature, docstring
    - FileNode properties: relative_path, basename
    - TextNode properties: text, relative_path, start_line, end_line
    - Relationships: CALLS, CONTAINS_SYMBOL, IMPORTS, etc.
    """

    def __init__(self, driver: Optional[AsyncDriver] = None, database: str = "neo4j"):
        """
        Initialize KG Query Service.

        Args:
            driver: Optional Neo4j driver (deprecated - use connection pool instead)
            database: Neo4j database name
        """
        self._driver = driver  # Legacy support
        self._database = database
        self._query_builder = KGQueryBuilder()

    async def _execute_query(
        self,
        query: str,
        params: Optional[dict[str, Any]] = None
    ) -> list[dict[str, Any]]:
        """
        Execute a query using connection pool or fallback to direct driver.

        Args:
            query: Cypher query string
            params: Query parameters

        Returns:
            List of query result records

        Raises:
            Exception: If query execution fails
        """
        try:
            # Try to use connection pool first
            pool = await get_connection_pool()
            if pool and pool.is_healthy():
                return await pool.execute_query(query, params, timeout=30)

        except Exception as e:
            logger.debug(f"Connection pool unavailable, falling back to direct driver: {e}")

        # Fallback to direct driver connection
        if not self._driver:
            raise RuntimeError("No Neo4j driver available")

        async with self._driver.session(database=self._database) as session:
            result = await session.run(query, params or {})
            return [dict(record) async for record in result]
        
    async def get_repo_commit_sha(self, repo_id: str) -> Optional[str]:
        """
        Best-effort: return any commit_sha stored on KG nodes for this repo_id.
        (This is expected to differ from PR head SHA.)
        """
        monitor = get_performance_monitor()

        with monitor.track_query("repo_commit_sha") as tracker:
            try:
                # Build parameterized query
                query_params = self._query_builder.build_repo_commit_sha_query(repo_id)

                # Execute query using connection pool
                result = await self._execute_query(query_params.query, query_params.params)

                commit_sha = result[0]["commit_sha"] if result else None

                logger.debug(f"Retrieved repo commit SHA for {repo_id}")
                return commit_sha

            except Exception as e:
                tracker.set_error(str(e))
                logger.error(f"Failed to get repo commit SHA for {repo_id}: {e}", exc_info=True)
                return None
        
    async def find_symbol(
        self,
        *,
        repo_id: str,
        file_path: str,
        name: Optional[str] = None,
        kind: Optional[str] = None,
        qualified_name: Optional[str] = None,
        fingerprint: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Find SymbolNode candidates for a seed symbol with caching and optimization.
        Matching strategy (best-effort, bounded):
        - Always scope by (repo_id, relative_path)
        - Prefer qualified_name if provided, else use (name [+ kind])
        - Optionally narrow by fingerprint if present
        """
        if not file_path:
            return []
        if not qualified_name and not name:
            return []

        start_time = time.time()

        try:
            # Build parameterized query
            query_params = self._query_builder.build_symbol_find_query(
                repo_id=repo_id,
                file_path=file_path,
                name=name,
                kind=kind,
                qualified_name=qualified_name,
                fingerprint=fingerprint,
                limit=limit,
            )

            # Execute query using connection pool
            results = await self._execute_query(query_params.query, query_params.params)

            # Extract nodes from results
            nodes = [result["node"] for result in results if "node" in result]
            converted_nodes = [dict(node) for node in nodes]

            query_time = (time.time() - start_time) * 1000
            logger.debug(
                f"Found {len(converted_nodes)} symbols for {file_path}:{name} in {query_time:.1f}ms"
            )

            return converted_nodes

        except Exception as e:
            logger.error(
                f"Failed to find symbol {file_path}:{name}: {e}",
                exc_info=True
            )
            return []
        
    async def expand_symbol_neighbors(
        self,
        *,
        repo_id: str,
        symbol_node_id: str,
        rel_types: Iterable[str],
        direction: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """
        Expand 1-hop neighbors from a symbol node with caching and optimization.

        direction:
        - 'outgoing': (s)-[:REL]->(n)
        - 'incoming': (s)<-[:REL]-(n)
        """
        # Convert rel_types to list
        rel_types_list = list(rel_types)

        start_time = time.time()

        try:
            # Build parameterized query
            query_params = self._query_builder.build_symbol_neighbors_query(
                repo_id=repo_id,
                symbol_node_id=symbol_node_id,
                rel_types=rel_types_list,
                direction=direction,
                limit=limit,
            )

            # Execute query using connection pool
            results = await self._execute_query(query_params.query, query_params.params)

            # Convert results to expected format
            neighbors = []
            for record in results:
                neighbors.append({
                    "rel_type": record.get("rel_type"),
                    "labels": record.get("labels", []),
                    "node": dict(record.get("node", {})),
                })

            query_time = (time.time() - start_time) * 1000
            logger.debug(
                f"Expanded {len(neighbors)} neighbors for {symbol_node_id} in {query_time:.1f}ms"
            )

            return neighbors

        except Exception as e:
            logger.error(
                f"Failed to expand neighbors for {symbol_node_id}: {e}",
                exc_info=True
            )
            return []
        
    async def get_import_neighborhood(
        self,
        *,
        repo_id: str,
        file_path: str,
        direction: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """
        Import neighborhood for a file node with optimization.
        direction:
        - 'outgoing': file imports others
        - 'incoming': others import file
        """
        start_time = time.time()

        try:
            # Build parameterized query
            query_params = self._query_builder.build_import_neighborhood_query(
                repo_id=repo_id,
                file_path=file_path,
                direction=direction,
                limit=limit,
            )

            # Execute query using connection pool
            results = await self._execute_query(query_params.query, query_params.params)

            # Convert results to expected format
            neighbors = []
            for record in results:
                neighbors.append({
                    "rel_type": record.get("rel_type"),
                    "labels": record.get("labels", []),
                    "node": dict(record.get("node", {})),
                })

            query_time = (time.time() - start_time) * 1000
            logger.debug(
                f"Retrieved {len(neighbors)} import neighbors for {file_path} in {query_time:.1f}ms"
            )

            return neighbors

        except Exception as e:
            logger.error(
                f"Failed to get import neighborhood for {file_path}: {e}",
                exc_info=True
            )
            return []

    async def get_text_nodes(
        self,
        *,
        repo_id: str,
        path_prefix: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """
        Retrieve documentation text nodes by path prefix.
        """
        if not path_prefix:
            return []

        start_time = time.time()

        try:
            # Build parameterized query
            query_params = self._query_builder.build_text_nodes_query(
                repo_id=repo_id,
                path_prefix=path_prefix,
                limit=limit,
            )

            # Execute query using connection pool
            results = await self._execute_query(query_params.query, query_params.params)

            # Extract nodes from results
            nodes = [result["node"] for result in results if "node" in result]
            converted_nodes = [dict(node) for node in nodes]

            query_time = (time.time() - start_time) * 1000
            logger.debug(
                f"Retrieved {len(converted_nodes)} text nodes for {path_prefix} in {query_time:.1f}ms"
            )

            return converted_nodes

        except Exception as e:
            logger.error(
                f"Failed to get text nodes for {path_prefix}: {e}",
                exc_info=True
            )
            return []

    async def batch_find_symbols(
        self,
        symbol_requests: list[dict[str, Any]],
        limit_per_symbol: int = 5
    ) -> dict[int, list[dict[str, Any]]]:
        """
        Batch symbol lookup to reduce N+1 query problem.

        Args:
            symbol_requests: List of symbol search parameters with format:
                [{"repo_id": str, "file_path": str, "name": str, ...}, ...]
            limit_per_symbol: Maximum results per symbol

        Returns:
            Dictionary mapping request index to list of found symbols
        """
        if not symbol_requests:
            return {}

        start_time = time.time()

        try:
            # Build batch query
            query_params = self._query_builder.build_batch_symbol_find_query(
                symbol_requests, limit_per_symbol
            )

            # Execute query using connection pool
            results = await self._execute_query(query_params.query, query_params.params)

            # Group results by request index
            grouped_results = {}
            for record in results:
                request_index = record.get("request_index")
                if request_index is not None:
                    if request_index not in grouped_results:
                        grouped_results[request_index] = []

                    node = record.get("node")
                    if node:
                        grouped_results[request_index].append(dict(node))

            query_time = (time.time() - start_time) * 1000
            total_results = sum(len(symbols) for symbols in grouped_results.values())
            logger.debug(
                f"Batch found {total_results} symbols for {len(symbol_requests)} requests in {query_time:.1f}ms"
            )

            return grouped_results

        except Exception as e:
            logger.error(f"Batch symbol find failed: {e}", exc_info=True)
            return {}