from typing import List

from temporalio.exceptions import ApplicationError
from src.core.config import settings
from src.core.neo4j import Neo4jConnection
from src.services.indexing.metadata_service import MetadataService
from src.services.indexing.repo_clone_service import RepoCloneService
from temporalio import activity

from src.services.indexing.repo_parsing_service import RepoParsingService
from src.services.kg import KnowledgeGraphService
from src.models.graph.indexing_stats import IndexingStats

# Clone repo activity
@activity.defn
async def clone_repo_activity(repo_request: dict) -> dict:
    """
    Clone repository and resolve commit SHA.
    
    Args:
        repo_request: {
            "installation_id": int,
            "github_repo_name": str,
            "repo_id": str,
            "default_branch": str,
            "repo_url": str
        }
    
    Returns:
        {
            "local_path": str,
            "commit_sha": str
        }
    
    Raises:
        ApplicationError (non_retryable=True): Auth/permission/not-found errors
        ApplicationError (non_retryable=False): Network/transient errors
    """
    activity.logger.info(f"Cloning {repo_request['github_repo_name']}")
    service = RepoCloneService()
    
    try:
        # Service handles token minting, git operations
        result = await service.clone_repo(
            repo_full_name=repo_request['github_repo_name'],
            repo_id=repo_request['repo_id'],
            installation_id=repo_request['installation_id'],
            default_branch=repo_request['default_branch'],
            repo_url=repo_request['repo_url'],
        )
        activity.logger.info(
            f"Successfully cloned {repo_request['github_repo_name']} to {result['local_path']} at {result['commit_sha']}"
        )
        return result
    except Exception as e:
        # Map errors to retryable/non-retryable
            error_msg = str(e).lower()
            
            # Non-retryable: auth, permissions, not found
            if any(x in error_msg for x in ["401", "403", "404", "unauthorized", "forbidden", "not found"]):
                raise ApplicationError(
                    f"Non-retryable error cloning repo: {e}",
                    non_retryable=True,
                ) from e
            
            # Retryable: network, rate limits, etc.
            activity.logger.warning(f"Retryable error cloning repo: {e}")
            raise
        
# Parse repo activity
@activity.defn
async def parse_repo_activity(input_data: dict) -> dict:
    """
    Parse repository using Tree-sitter and build in-memory graph.
    
    Args:
        input_data: {
            "local_path": str,
            "repo_id": str,
            "commit_sha": str
        }
    
    Returns:
        {
            "graph_result": RepoGraphResult (nodes, edges, root),
            "stats": IndexingStats,
            "repo_id": str,
            "commit_sha": str
        }
    """
    activity.logger.info(f"Parsing repo at {input_data['local_path']}")
    
    service = RepoParsingService()
    
    try:
        # Send heartbeat for long operations
        activity.heartbeat("Starting AST parsing")
        
        graph_result = await service.parse_repository(
            local_path=input_data["local_path"],
            repo_id=input_data["repo_id"],
            commit_sha=input_data["commit_sha"],
        )
        
        activity.logger.info(
            f"Parsed {len(graph_result.nodes)} nodes, "
            f"{len(graph_result.edges)} edges"
        )
        
        return {
            "graph_result": graph_result,
            "stats": graph_result.stats.__dict__,
            "repo_id": input_data["repo_id"],
            "commit_sha": input_data["commit_sha"],
        }
        
    except Exception as e:
        activity.logger.error(f"Failed to parse repo: {e}")
        raise ApplicationError(f"Parsing failed: {e}") from e
    
# Postgres metadata persistence activity
@activity.defn
async def persist_metadata_activity(input_data: dict) -> dict:
    """
    Persist indexing metadata to Postgres.
    
    Writes:
    - repo_snapshots (commit_sha record)
    - indexed_files (file metadata)
    - repositories (update last_indexed_sha, last_indexed_at)
    
    Args:
        input_data: {
            "repo_id": str,
            "commit_sha": str,
            "parse_result": dict with graph_result and stats
        }
    
    Returns:
        {"status": "success", "snapshot_id": str}
    """
    activity.logger.info(
        f"Persisting metadata for repo {input_data['repo_id']} "
        f"at {input_data['commit_sha']}"
    )
    
    service = MetadataService()
    
    try:
        # Reconstruct IndexingStats from dict (Temporal serializes it as dict)
        stats_dict = input_data["parse_result"]["stats"]
        stats = IndexingStats(**stats_dict) if isinstance(stats_dict, dict) else stats_dict
        
        snapshot_id = await service.persist_indexing_metadata(
            repo_id=input_data["repo_id"],
            commit_sha=input_data["commit_sha"],
            graph_result=input_data["parse_result"]["graph_result"],
            stats=stats,
        )
        
        activity.logger.info(f"Created snapshot {snapshot_id}")
        
        return {"status": "success", "snapshot_id": snapshot_id}
        
    except Exception as e:
        activity.logger.error(f"Failed to persist metadata: {e}")
        raise ApplicationError(f"Metadata persistence failed: {e}") from e

# Neo4j Knowledge Graph persistence activity
@activity.defn
async def persist_kg_activity(input_data: dict) -> dict:
    """
    Persist knowledge graph to Neo4j.
    
    Args:
        input_data: {
            "repo_id": str,
            "github_repo_name": str,
            "graph_result": RepoGraphResult
        }
    
    Returns:
        {"nodes_created": int, "edges_created": int}
    """
    activity.logger.info(
        f"Persisting KG for {input_data['github_repo_name']}"
    )
    
    service = KnowledgeGraphService(driver=Neo4jConnection.get_driver(), database=settings.NEO4J_DATABASE)
    
    try:
        activity.heartbeat("Starting Neo4j persistence")
        
        result = await service.persist_kg(
            repo_id=input_data["repo_id"],
            nodes=input_data["graph_result"].nodes,
            edges=input_data["graph_result"].edges,
        )
        
        activity.logger.info(
            f"Persisted {result.nodes_created} nodes, "
            f"{result.edges_created} edges to Neo4j"
        )
        
        return result.__dict__
    except Exception as e:
        activity.logger.error(f"Failed to persist KG: {e}")
        raise ApplicationError(f"Neo4j persistence failed: {e}") from e
    
# Cleanup repo activity
@activity.defn
async def cleanup_repo_activity(local_path: str) -> dict:
    """
    Cleanup cloned repository directory.
    
    Args:
        local_path: str
    
    Returns:
        {"status": "cleaned"}
    """
    activity.logger.info(f"Cleaning up {local_path}")
    
    service = RepoCloneService()
    
    try:
        await service.cleanup_repo(local_path=local_path)
        return {"status": "cleaned"}
    except Exception as e:
        # Log but don't fail the workflow on cleanup errors
        activity.logger.warning(f"Cleanup failed: {e}")
        return {"status": "cleanup_failed", "error": str(e)}

# Cleanup stale KG nodes activity
@activity.defn
async def cleanup_stale_kg_nodes_activity(input_data: dict) -> dict:
    """
    Cleanup stale knowledge graph nodes for a repository.
    
    Removes nodes that haven't been refreshed during re-indexing
    (nodes representing deleted code symbols/files).
    
    Args:
        input_data: {
            "repo_id": str,
            "ttl_days": int (optional, default: 30)
        }
    
    Returns:
        {"nodes_deleted": int}
    """
    repo_id = input_data["repo_id"]
    ttl_days = input_data.get("ttl_days", 30)
    
    activity.logger.info(
        f"Cleaning up stale KG nodes for repo {repo_id} (TTL: {ttl_days} days)"
    )
    
    service = KnowledgeGraphService(
        driver=Neo4jConnection.get_driver(),
        database=settings.NEO4J_DATABASE
    )
    
    try:
        nodes_deleted = await service.cleanup_stale_nodes(
            repo_id=repo_id,
            ttl_days=ttl_days,
        )
        
        activity.logger.info(
            f"Cleaned up {nodes_deleted} stale nodes for repo {repo_id}"
        )
        
        return {"nodes_deleted": nodes_deleted}
    except Exception as e:
        activity.logger.error(f"Failed to cleanup stale KG nodes: {e}")
        raise ApplicationError(f"Stale nodes cleanup failed: {e}") from e