"""
Parameterized Neo4j Query Builder

Replaces dynamic string concatenation with parameterized queries
for better performance and query plan caching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class QueryParams:
    """Container for query parameters and the query string."""
    query: str
    params: Dict[str, Any]


class KGQueryBuilder:
    """
    Builder for parameterized Neo4j queries to improve performance.

    Replaces dynamic string concatenation with parameterized queries
    that allow Neo4j to cache execution plans.
    """

    @staticmethod
    def build_symbol_find_query(
        *,
        repo_id: str,
        file_path: str,
        name: Optional[str] = None,
        kind: Optional[str] = None,
        qualified_name: Optional[str] = None,
        fingerprint: Optional[str] = None,
        limit: int = 10,
    ) -> QueryParams:
        """
        Build parameterized query for finding symbol nodes.

        Args:
            repo_id: Repository identifier
            file_path: File path to match
            name: Symbol name (optional)
            kind: Symbol kind (optional)
            qualified_name: Qualified symbol name (optional)
            fingerprint: Symbol fingerprint (optional)
            limit: Result limit

        Returns:
            QueryParams with parameterized query and parameters
        """
        conditions: List[str] = [
            "s.repo_id = $repo_id",
            "s.relative_path = $file_path",
        ]

        params: Dict[str, Any] = {
            "repo_id": repo_id,
            "file_path": file_path,
            "limit": max(1, int(limit))
        }

        # Build conditions based on available parameters
        if qualified_name:
            conditions.append("s.qualified_name = $qualified_name")
            params["qualified_name"] = qualified_name
        elif name:
            conditions.append("s.name = $name")
            params["name"] = name

        if kind:
            conditions.append("s.kind = $kind")
            params["kind"] = kind

        # Fingerprint is optional and may not exist on older graphs
        if fingerprint:
            conditions.append("s.fingerprint = $fingerprint")
            params["fingerprint"] = fingerprint

        where_clause = " AND ".join(conditions)
        query = f"""
        MATCH (s:KGNode:SymbolNode)
        WHERE {where_clause}
        RETURN properties(s) AS node
        LIMIT $limit
        """

        return QueryParams(query=query, params=params)

    @staticmethod
    def build_symbol_neighbors_query(
        *,
        repo_id: str,
        symbol_node_id: str,
        rel_types: Iterable[str],
        direction: str,
        limit: int,
    ) -> QueryParams:
        """
        Build parameterized query for expanding symbol neighbors.

        Uses relationship type arrays instead of dynamic string concatenation
        to enable query plan caching.

        Args:
            repo_id: Repository identifier
            symbol_node_id: Source symbol node ID
            rel_types: List of relationship types
            direction: 'outgoing' or 'incoming'
            limit: Result limit

        Returns:
            QueryParams with parameterized query and parameters

        Raises:
            ValueError: If direction is invalid
        """
        if direction not in ("outgoing", "incoming"):
            raise ValueError("direction must be 'outgoing' or 'incoming'")

        # Clean and normalize relationship types
        clean_rels = [r.strip().upper() for r in rel_types if r and r.strip()]
        if not clean_rels:
            # Return empty result query if no valid relationships
            return QueryParams(
                query="RETURN [] AS result LIMIT 0",
                params={}
            )

        limit = max(1, int(limit))

        # Use parameterized relationship type matching
        if direction == "outgoing":
            pattern = "(s)-[r]->(n)"
            rel_condition = "type(r) IN $rel_types"
        else:
            pattern = "(s)<-[r]-(n)"
            rel_condition = "type(r) IN $rel_types"

        query = f"""
        MATCH (s:KGNode:SymbolNode {{repo_id: $repo_id, node_id: $symbol_node_id}})
        MATCH {pattern}
        WHERE n.repo_id = $repo_id AND {rel_condition}
        RETURN
            type(r) AS rel_type,
            labels(n) AS labels,
            properties(n) AS node
        LIMIT $limit
        """

        params = {
            "repo_id": repo_id,
            "symbol_node_id": symbol_node_id,
            "rel_types": clean_rels,
            "limit": limit,
        }

        return QueryParams(query=query, params=params)

    @staticmethod
    def build_import_neighborhood_query(
        *,
        repo_id: str,
        file_path: str,
        direction: str,
        limit: int,
    ) -> QueryParams:
        """
        Build parameterized query for import neighborhood.

        Args:
            repo_id: Repository identifier
            file_path: File path to match
            direction: 'outgoing' or 'incoming'
            limit: Result limit

        Returns:
            QueryParams with parameterized query and parameters

        Raises:
            ValueError: If direction is invalid
        """
        if direction not in ("outgoing", "incoming"):
            raise ValueError("direction must be 'outgoing' or 'incoming'")

        limit = max(1, int(limit))

        if direction == "outgoing":
            pattern = "(f)-[r:IMPORTS]->(n)"
        else:
            pattern = "(f)<-[r:IMPORTS]-(n)"

        query = f"""
        MATCH (f:KGNode:FileNode {{repo_id: $repo_id, relative_path: $file_path}})
        MATCH {pattern}
        WHERE n.repo_id = $repo_id
        RETURN
            type(r) AS rel_type,
            labels(n) AS labels,
            properties(n) AS node
        LIMIT $limit
        """

        params = {
            "repo_id": repo_id,
            "file_path": file_path,
            "limit": limit,
        }

        return QueryParams(query=query, params=params)

    @staticmethod
    def build_text_nodes_query(
        *,
        repo_id: str,
        path_prefix: str,
        limit: int,
    ) -> QueryParams:
        """
        Build parameterized query for text nodes by path prefix.

        Args:
            repo_id: Repository identifier
            path_prefix: Path prefix to match
            limit: Result limit

        Returns:
            QueryParams with parameterized query and parameters
        """
        if not path_prefix:
            # Return empty result for invalid prefix
            return QueryParams(
                query="RETURN [] AS result LIMIT 0",
                params={}
            )

        limit = max(1, int(limit))

        query = """
        MATCH (t:KGNode:TextNode {repo_id: $repo_id})
        WHERE t.relative_path STARTS WITH $path_prefix
        RETURN properties(t) AS node
        ORDER BY t.relative_path, t.start_line
        LIMIT $limit
        """

        params = {
            "repo_id": repo_id,
            "path_prefix": path_prefix,
            "limit": limit,
        }

        return QueryParams(query=query, params=params)

    @staticmethod
    def build_batch_symbol_find_query(
        symbol_requests: List[Dict[str, Any]],
        limit_per_symbol: int = 5
    ) -> QueryParams:
        """
        Build batched query for multiple symbol lookups to reduce N+1 problem.

        Args:
            symbol_requests: List of symbol search parameters
            limit_per_symbol: Limit per symbol match

        Returns:
            QueryParams with batched query and parameters
        """
        if not symbol_requests:
            return QueryParams(
                query="RETURN [] AS result LIMIT 0",
                params={}
            )

        # Build UNWIND query for batch processing
        query = """
        UNWIND $symbol_requests AS req
        MATCH (s:KGNode:SymbolNode)
        WHERE s.repo_id = req.repo_id
          AND s.relative_path = req.file_path
          AND (
            (req.qualified_name IS NOT NULL AND s.qualified_name = req.qualified_name)
            OR (req.qualified_name IS NULL AND s.name = req.name)
          )
          AND (req.kind IS NULL OR s.kind = req.kind)
          AND (req.fingerprint IS NULL OR s.fingerprint = req.fingerprint)
        WITH req, s
        ORDER BY req.index, s.node_id
        WITH req, COLLECT(s)[0..$limit_per_symbol] AS matches
        UNWIND matches AS match
        RETURN
          req.index AS request_index,
          req AS original_request,
          properties(match) AS node
        ORDER BY req.index
        """

        # Add index to each request for result matching
        indexed_requests = [
            {**req, "index": i}
            for i, req in enumerate(symbol_requests)
        ]

        params = {
            "symbol_requests": indexed_requests,
            "limit_per_symbol": max(1, int(limit_per_symbol))
        }

        return QueryParams(query=query, params=params)

    @staticmethod
    def build_repo_commit_sha_query(repo_id: str) -> QueryParams:
        """
        Build parameterized query for retrieving repository commit SHA.

        Args:
            repo_id: Repository identifier

        Returns:
            QueryParams with query and parameters
        """
        query = """
        MATCH (n:KGNode {repo_id: $repo_id})
        WHERE n.commit_sha IS NOT NULL
        RETURN n.commit_sha AS commit_sha
        LIMIT 1
        """

        params = {"repo_id": repo_id}

        return QueryParams(query=query, params=params)