from temporalio.exceptions import ApplicationError
from src.core.config import settings
from src.core.neo4j import Neo4jConnection
from src.services.indexing.metadata_service import MetadataService
from src.services.indexing.repo_clone_service import RepoCloneService
from temporalio import activity
from src.activities.helpers import _deserialize_node, _deserialize_edge
from src.services.indexing.repo_parsing_service import RepoParsingService
from src.services.kg import KnowledgeGraphService
from src.utils.logging import get_logger
logger = get_logger(__name__)


# Clone repo activity
@activity.defn
async def clone_repo_activity(repo_request: dict) -> dict:
    """
    Clone repository and optionally resolve commit SHA.
    
    Args:
        repo_request: {
            "installation_id": int,
            "repository": {
                "github_repo_name": str,
                "github_repo_id": int,
                "repo_id": str,
                "default_branch": str,
                "repo_url": str,
                "commit_sha": str | None (optional)
            }
        }
    
    Returns:
        {
            "local_path": str,
            "commit_sha": str | None
        }
    
    Raises:
        ApplicationError (non_retryable=True): Auth/permission/not-found errors
        ApplicationError (non_retryable=False): Network/transient errors
    """
    repo_info = repo_request['repository']
    logger.info(
        f"Cloning {repo_info['github_repo_name']} "
        f"(branch: {repo_info['default_branch']}, "
        f"commit_sha: {repo_info.get('commit_sha', 'not provided')})"
    )
    service = RepoCloneService()
    
    try:
        # Service handles token minting, git operations
        result = await service.clone_repo(
            repo_full_name=repo_info['github_repo_name'],
            github_repo_id=repo_info['github_repo_id'],
            repo_id=repo_info['repo_id'],
            installation_id=repo_request['installation_id'],
            default_branch=repo_info['default_branch'],
            repo_url=repo_info['repo_url'],
            commit_sha=repo_info.get('commit_sha'),  # Optional
        )
        commit_info = result.get('commit_sha') or 'branch-based'
        logger.info(
            f"Successfully cloned {repo_info['github_repo_name']} to {result['local_path']} "
            f"(identifier: {commit_info})"
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
            logger.warning(f"Retryable error cloning repo: {e}")
            raise
        
# Parse repo activity
@activity.defn
async def parse_repo_activity(input_data: dict) -> dict:
    """
    Parse repository using Tree-sitter and build in-memory graph.
    
    Args:
        input_data: {
            "local_path": str,
            "github_repo_id": int,
            "repo_id": str,
            "commit_sha": str | None (optional)
        }
    
    Returns:
        {
            "graph_result": RepoGraphResult (nodes, edges, root),
            "stats": IndexingStats,
            "github_repo_id": int,
            "repo_id": str,
            "commit_sha": str | None
        }
    """
    logger.info(f"Parsing repo at {input_data['local_path']}")
    
    service = RepoParsingService()
    
    try:
        # Send heartbeat for long operations
        activity.heartbeat("Starting AST parsing")
        
        commit_sha = input_data.get("commit_sha")  # May be None
        graph_result = await service.parse_repository(
            local_path=input_data["local_path"],
            github_repo_id=input_data["github_repo_id"],
            repo_id=input_data["repo_id"],
            commit_sha=commit_sha,
        )
        
        logger.info(
            f"Parsed {len(graph_result.nodes)} nodes, "
            f"{len(graph_result.edges)} edges"
        )
        
        return {
            "graph_result": graph_result,
            "stats": graph_result.stats.__dict__,
            "github_repo_id": input_data["github_repo_id"],
            "repo_id": input_data["repo_id"],
            "commit_sha": commit_sha,
        }
        
    except Exception as e:
        logger.error(f"Failed to parse repo: {e}")
        raise ApplicationError(f"Parsing failed: {e}") from e
    
# Postgres metadata persistence activity
@activity.defn
async def persist_metadata_activity(input_data: dict) -> dict:
    """
    Persist indexing metadata to Postgres.
    
    Creates a snapshot record to track this indexing run and updates
    the repository's last_indexed_at timestamp. This allows linking
    PR reviews to specific indexing snapshots.
    
    Note: The actual code graph data (files, symbols, edges) is stored in Neo4j
    via persist_kg_activity. This activity only stores lightweight metadata.
    
    Args:
        input_data: {
            "repo_id": str,
            "github_repo_id": int,
            "commit_sha": str | None (optional)
        }
    
    Returns:
        {"status": "success", "snapshot_id": str}
    """
    commit_sha = input_data.get("commit_sha")
    commit_info = commit_sha or "branch-based (no commit SHA)"
    logger.info(
        f"Persisting metadata for repo {input_data['repo_id']} "
        f"(identifier: {commit_info})"
    )
    
    service = MetadataService()
    
    try:
        snapshot_id = await service.persist_indexing_metadata(
            repo_id=input_data["repo_id"],
            github_repo_id=input_data["github_repo_id"],
            commit_sha=commit_sha,
        )
        
        logger.info(f"Created snapshot {snapshot_id}")
        
        return {"status": "success", "snapshot_id": snapshot_id}
        
    except Exception as e:
        logger.error(f"Failed to persist metadata: {e}")
        raise ApplicationError(f"Metadata persistence failed: {e}") from e

# Neo4j Knowledge Graph persistence activity
@activity.defn
async def persist_kg_activity(input_data: dict) -> dict:
    """
    Persist knowledge graph to Neo4j.
    
    Args:
        input_data: {
            "repo_id": str,
            "github_repo_id": int,
            "github_repo_name": str,
            "graph_result": RepoGraphResult
        }
    
    Returns:
        {"nodes_created": int, "edges_created": int}
    """
    logger.info(
        f"Persisting KG for {input_data['github_repo_name']}"
    )
    
    service = KnowledgeGraphService(driver=Neo4jConnection.get_driver(), database=settings.NEO4J_DATABASE)
    
    try:
        activity.heartbeat("Starting Neo4j persistence")
        
        # Deserialize nodes and edges from dicts back to proper Python objects
        # (Temporal serializes dataclasses to dicts when passing between activities)
        nodes = [_deserialize_node(n) for n in input_data["graph_result"]["nodes"]]
        edges = [_deserialize_edge(e) for e in input_data["graph_result"]["edges"]]
        
        result = await service.persist_kg(
            repo_id=input_data["repo_id"],
            github_repo_id=input_data["github_repo_id"],
            nodes=nodes,
            edges=edges,
        )
        
        logger.info(
            f"Persisted {result.nodes_created} nodes, "
            f"{result.edges_created} edges to Neo4j"
        )
        
        return result.__dict__
    except Exception as e:
        logger.error(f"Failed to persist KG: {e}")
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
    logger.info(f"Cleaning up {local_path}")
    
    service = RepoCloneService()
    
    try:
        await service.cleanup_repo(local_path=local_path)
        return {"status": "cleaned"}
    except Exception as e:
        # Log but don't fail the workflow on cleanup errors
        logger.warning(f"Cleanup failed: {e}")
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
    
    logger.info(
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
        
        logger.info(
            f"Cleaned up {nodes_deleted} stale nodes for repo {repo_id}"
        )
        
        return {"nodes_deleted": nodes_deleted}
    except Exception as e:
        logger.error(f"Failed to cleanup stale KG nodes: {e}")
        raise ApplicationError(f"Stale nodes cleanup failed: {e}") from e