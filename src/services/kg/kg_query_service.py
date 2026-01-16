from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from neo4j import AsyncDriver

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
    Read-only Neo4j query service for PR-review context retrieval.

    Notes about schema (as persisted by src/services/kg/kg_handler.py):
    - Nodes use :KGNode plus a concrete label (SymbolNode/FileNode/TextNode).
    - Common properties: repo_id, node_id, commit_sha
    - SymbolNode properties: relative_path, name, kind, qualified_name, fingerprint, start_line, end_line, signature, docstring
    - FileNode properties: relative_path, basename
    - TextNode properties: text, relative_path, start_line, end_line
    - Relationships: CALLS, CONTAINS_SYMBOL, IMPORTS, etc.
    """
    
    def __init__(self, driver: AsyncDriver, database: str = "neo4j"):
        self._driver = driver
        self._database = database
        
    async def get_repo_commit_sha(self, repo_id: str) -> Optional[str]:
        """
        Best-effort: return any commit_sha stored on KG nodes for this repo_id.
        (This is expected to differ from PR head SHA.)
        """
        
        query = """
            MATCH (n:KGNode {repo_id: $repo_id})
            WHERE n.commit_sha IS NOT NULL
            RETURN n.commit_sha AS commit_sha
            LIMIT 1
            """
        async with self._driver.session(database=self._database) as session:
            res = await session.run(query, repo_id=repo_id)
            rec = await res.single()
            return rec["commit_sha"] if rec else None
        
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
        Find SymbolNode candidates for a seed symbol.
        Matching strategy (best-effort, bounded):
        - Always scope by (repo_id, relative_path)
        - Prefer qualified_name if provided, else use (name [+ kind])
        - Optionally narrow by fingerprint if present
        """
        if not file_path:
            return []
        if not qualified_name and not name:
            return []
        
        limit = max(1, int(limit))
        
        conditions: list[str] = [
            "s.repo_id = $repo_id",
            "s.relative_path = $file_path",
        ]
        params: dict[str, Any] = {"repo_id": repo_id, "file_path": file_path, "limit": limit}

        if qualified_name:
            conditions.append("s.qualified_name = $qualified_name")
            params["qualified_name"] = qualified_name
        else:
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
        
        async with self._driver.session(database=self._database) as session:
            res = await session.run(query, **params)
            rows = [record["node"] async for record in res]
            return [dict(r) for r in rows]
        
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
        Expand 1-hop neighbors from a symbol node.

        direction:
        - 'outgoing': (s)-[:REL]->(n)
        - 'incoming': (s)<-[:REL]-(n)
        """
        rels = [r.strip().upper() for r in rel_types if r and r.strip()]
        if not rels:
            return []
        if direction not in ("outgoing", "incoming"):
            raise ValueError("direction must be 'outgoing' or 'incoming'")

        limit = max(1, int(limit))

        rel_union = "|".join(rels)  # Cypher relationship union syntax
        if direction == "outgoing":
            pattern = f"(s)-[r:{rel_union}]->(n)"
        else:
            pattern = f"(s)<-[r:{rel_union}]-(n)"
            
        query = f"""
        MATCH (s:KGNode:SymbolNode {{repo_id: $repo_id, node_id: $symbol_node_id}})
        MATCH {pattern}
        WHERE n.repo_id = $repo_id
        RETURN
            type(r) AS rel_type,
            labels(n) AS labels,
            properties(n) AS node
        LIMIT $limit
        """
        
        async with self._driver.session(database=self._database) as session:
            res = await session.run(
                query,
                repo_id=repo_id,
                symbol_node_id=symbol_node_id,
                limit=limit,
            )
            out: list[dict[str, Any]] = []
            async for record in res:
                out.append(
                    {
                        "rel_type": record["rel_type"],
                        "labels": record["labels"],
                        "node": dict(record["node"]),
                    }
                )
            return out
        
    async def get_import_neighborhood(
        self,
        *,
        repo_id: str,
        file_path: str,
        direction: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """
        Import neighborhood for a file node.
        direction:
        - 'outgoing': file imports others
        - 'incoming': others import file
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
        
        async with self._driver.session(database=self._database) as session:
            res = await session.run(
                query,
                repo_id=repo_id,
                file_path=file_path,
                limit=limit,
            )
            out: list[dict[str, Any]] = []
            async for record in res:
                out.append(
                    {
                        "rel_type": record["rel_type"],
                        "labels": record["labels"],
                        "node": dict(record["node"]),
                    }
                )
            return out
        
    async def get_text_nodes(
        self,
        *,
        repo_id: str,
        path_prefix: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """
        Retrieve documentation text nodes by path prefix (README, docs/, etc.)
        """
        if not path_prefix:
            return []
        limit = max(1, int(limit))

        query = """
        MATCH (t:KGNode:TextNode {repo_id: $repo_id})
        WHERE t.relative_path STARTS WITH $path_prefix
        RETURN properties(t) AS node
        ORDER BY t.relative_path, t.start_line
        LIMIT $limit
        """

        async with self._driver.session(database=self._database) as session:
            res = await session.run(
                query,
                repo_id=repo_id,
                path_prefix=path_prefix,
                limit=limit,
            )
            rows = [record["node"] async for record in res]
            return [dict(r) for r in rows]