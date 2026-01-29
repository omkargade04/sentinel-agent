from temporalio.exceptions import ApplicationError
from src.core.config import settings
from src.core.neo4j import Neo4jConnection
from src.services.persist_metadata.persist_metadata_service import MetadataService
from src.services.indexing.repo_clone_service import RepoCloneService
from temporalio import activity
from src.activities.helpers import _deserialize_node, _deserialize_edge
from src.services.indexing.repo_parsing_service import RepoParsingService
from src.services.kg import KnowledgeGraphService
from src.services.workflow_events import WorkflowEventEmitter
from src.utils.logging import get_logger
logger = get_logger(__name__)


# SHA precheck activity
@activity.defn
async def check_indexing_needed_activity(repo_request: dict) -> dict:
    """
    Check if indexing is needed by comparing current commit SHA with latest snapshot.

    This precheck prevents unnecessary re-indexing when the branch head hasn't changed.

    Args:
        repo_request: {
            "installation_id": int,
            "event_context": dict (optional),
            "repository": {
                "github_repo_name": str,
                "github_repo_id": int,
                "repo_id": str,
                "default_branch": str,
                "repo_url": str
            }
        }

    Returns:
        {
            "indexing_needed": bool,
            "current_sha": str | None,
            "latest_snapshot_sha": str | None,
            "reason": str
        }
    """
    repo_info = repo_request['repository']
    repo_id = repo_info['repo_id']

    # Initialize event emitter if context provided
    event_context = repo_request.get("event_context")
    emitter = WorkflowEventEmitter(**event_context) if event_context else None

    if emitter:
        try:
            await emitter.emit_started(
                "check_indexing_needed_activity",
                f"Checking if indexing needed for {repo_info['github_repo_name']}..."
            )
        except Exception as e:
            logger.warning(f"Failed to emit started event: {e}")

    logger.info(
        f"Checking if indexing needed for {repo_info['github_repo_name']} "
        f"(repo_id={repo_id})"
    )
    
    # Step 1: Resolve current commit SHA from branch head
    clone_service = RepoCloneService()
    metadata_service = MetadataService()

    try:
        token = await clone_service.helpers.generate_installation_token(repo_request['installation_id'])
        # Use the same SHA resolution logic as clone
        current_sha = await clone_service._resolve_commit_sha(
            repo_full_name=repo_info['github_repo_name'],
            default_branch=repo_info['default_branch'],
            token=token,
            repo_url=repo_info['repo_url'],
        )
    except Exception as e:
        # If we can't resolve SHA, we must index (can't skip)
        logger.warning(
            f"Failed to resolve current SHA for {repo_info['github_repo_name']}: {e}. "
            f"Will proceed with indexing."
        )
        result = {
            "indexing_needed": True,
            "current_sha": None,
            "latest_snapshot_sha": None,
            "reason": "sha_resolution_failed"
        }
        if emitter:
            try:
                await emitter.emit_completed(
                    "check_indexing_needed_activity",
                    f"Indexing required: SHA resolution failed",
                    metadata={"reason": "sha_resolution_failed"}
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit completed event: {emit_err}")
        return result
    
    # Step 2: Get latest snapshot SHA from Postgres
    try:
        latest_snapshot_sha = await metadata_service.get_latest_snapshot_sha(repo_id)
    except Exception as e:
        logger.warning(
            f"Failed to fetch latest snapshot for {repo_id}: {e}. "
            f"Will proceed with indexing."
        )
        result = {
            "indexing_needed": True,
            "current_sha": current_sha,
            "latest_snapshot_sha": None,
            "reason": "snapshot_query_failed"
        }
        if emitter:
            try:
                await emitter.emit_completed(
                    "check_indexing_needed_activity",
                    f"Indexing required: snapshot query failed",
                    metadata={"reason": "snapshot_query_failed", "current_sha": current_sha}
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit completed event: {emit_err}")
        return result
    
    # Step 3: Compare SHAs
    if latest_snapshot_sha is None:
        # No previous snapshot - must index
        logger.info(
            f"No previous snapshot found for {repo_info['github_repo_name']}. "
            f"Indexing required."
        )
        result = {
            "indexing_needed": True,
            "current_sha": current_sha,
            "latest_snapshot_sha": None,
            "reason": "no_previous_snapshot"
        }
        if emitter:
            try:
                await emitter.emit_completed(
                    "check_indexing_needed_activity",
                    f"Indexing required: no previous snapshot",
                    metadata={"reason": "no_previous_snapshot", "current_sha": current_sha}
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit completed event: {emit_err}")
        return result

    if current_sha == latest_snapshot_sha:
        # SHAs match - skip indexing
        logger.info(
            f"Current SHA ({current_sha[:8]}) matches latest snapshot. "
            f"Skipping indexing for {repo_info['github_repo_name']}."
        )
        result = {
            "indexing_needed": False,
            "current_sha": current_sha,
            "latest_snapshot_sha": latest_snapshot_sha,
            "reason": "sha_unchanged"
        }
        if emitter:
            try:
                await emitter.emit_completed(
                    "check_indexing_needed_activity",
                    f"No indexing needed: SHA unchanged ({current_sha[:8]})",
                    metadata={"reason": "sha_unchanged", "current_sha": current_sha}
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit completed event: {emit_err}")
        return result

    # SHAs differ - must index
    logger.info(
        f"SHA changed for {repo_info['github_repo_name']}: "
        f"{latest_snapshot_sha[:8] if latest_snapshot_sha else 'None'} -> {current_sha[:8]}. "
        f"Indexing required."
    )
    result = {
        "indexing_needed": True,
        "current_sha": current_sha,
        "latest_snapshot_sha": latest_snapshot_sha,
        "reason": "sha_changed"
    }
    if emitter:
        try:
            await emitter.emit_completed(
                "check_indexing_needed_activity",
                f"Indexing required: SHA changed from {latest_snapshot_sha[:8] if latest_snapshot_sha else 'None'} to {current_sha[:8]}",
                metadata={"reason": "sha_changed", "current_sha": current_sha, "previous_sha": latest_snapshot_sha}
            )
        except Exception as emit_err:
            logger.warning(f"Failed to emit completed event: {emit_err}")
    return result


# Clone repo activity
@activity.defn
async def clone_repo_activity(repo_request: dict) -> dict:
    """
    Clone repository and optionally resolve commit SHA.

    Args:
        repo_request: {
            "installation_id": int,
            "event_context": dict (optional),
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

    # Initialize event emitter if context provided
    event_context = repo_request.get("event_context")
    emitter = WorkflowEventEmitter(**event_context) if event_context else None

    if emitter:
        try:
            await emitter.emit_started(
                "clone_repo_activity",
                f"Cloning {repo_info['github_repo_name']}..."
            )
        except Exception as e:
            logger.warning(f"Failed to emit started event: {e}")

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

        if emitter:
            try:
                await emitter.emit_completed(
                    "clone_repo_activity",
                    f"Cloned {repo_info['github_repo_name']} to {result['local_path']}",
                    metadata={"commit_sha": result.get('commit_sha'), "local_path": result['local_path']}
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit completed event: {emit_err}")

        return result
    except Exception as e:
        # Emit failed event
        if emitter:
            try:
                await emitter.emit_failed(
                    "clone_repo_activity",
                    f"Clone failed: {str(e)}",
                    metadata={"error": str(e)}
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit failed event: {emit_err}")

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
            "commit_sha": str | None (optional),
            "event_context": dict (optional)
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
    # Initialize event emitter if context provided
    event_context = input_data.get("event_context")
    emitter = WorkflowEventEmitter(**event_context) if event_context else None

    if emitter:
        try:
            await emitter.emit_started(
                "parse_repo_activity",
                f"Parsing repository at {input_data['local_path']}..."
            )
        except Exception as e:
            logger.warning(f"Failed to emit started event: {e}")

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

        result = {
            "graph_result": graph_result,
            "stats": graph_result.stats.__dict__,
            "github_repo_id": input_data["github_repo_id"],
            "repo_id": input_data["repo_id"],
            "commit_sha": commit_sha,
        }

        if emitter:
            try:
                await emitter.emit_completed(
                    "parse_repo_activity",
                    f"Parsed {graph_result.stats.total_symbols} symbols from {graph_result.stats.indexed_files} files",
                    metadata={
                        "total_symbols": graph_result.stats.total_symbols,
                        "indexed_files": graph_result.stats.indexed_files,
                        "nodes": len(graph_result.nodes),
                        "edges": len(graph_result.edges),
                    }
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit completed event: {emit_err}")

        return result

    except Exception as e:
        if emitter:
            try:
                await emitter.emit_failed(
                    "parse_repo_activity",
                    f"Parsing failed: {str(e)}",
                    metadata={"error": str(e)}
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit failed event: {emit_err}")

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
            "commit_sha": str | None (optional),
            "event_context": dict (optional)
        }

    Returns:
        {"status": "success", "snapshot_id": str}
    """
    commit_sha = input_data.get("commit_sha")
    commit_info = commit_sha or "branch-based (no commit SHA)"

    # Initialize event emitter if context provided
    event_context = input_data.get("event_context")
    emitter = WorkflowEventEmitter(**event_context) if event_context else None

    if emitter:
        try:
            await emitter.emit_started(
                "persist_metadata_activity",
                f"Saving metadata to Postgres..."
            )
        except Exception as e:
            logger.warning(f"Failed to emit started event: {e}")

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

        result = {"status": "success", "snapshot_id": snapshot_id}

        if emitter:
            try:
                await emitter.emit_completed(
                    "persist_metadata_activity",
                    f"Saved metadata snapshot {snapshot_id[:8]}...",
                    metadata={"snapshot_id": snapshot_id}
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit completed event: {emit_err}")

        return result

    except Exception as e:
        if emitter:
            try:
                await emitter.emit_failed(
                    "persist_metadata_activity",
                    f"Metadata persistence failed: {str(e)}",
                    metadata={"error": str(e)}
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit failed event: {emit_err}")

        logger.error(f"Failed to persist metadata: {e}")
        raise ApplicationError(f"Metadata persistence failed: {e}") from e

# Neo4j Knowledge Graph persistence activity
@activity.defn
async def persist_kg_activity(input_data: dict) -> dict:
    """
    Persist knowledge graph to Neo4j using delete-then-write pattern.

    Deletes existing graph for the repo before writing new graph to enforce
    latest-only semantics (no mixed state from multiple commits).
    All nodes and edges are tagged with commit_sha for provenance.

    Args:
        input_data: {
            "repo_id": str,
            "github_repo_id": int,
            "github_repo_name": str,
            "graph_result": RepoGraphResult,
            "commit_sha": str | None,
            "event_context": dict (optional)
        }

    Returns:
        {
            "nodes_created": int,
            "edges_created": int,
            "nodes_deleted": int
        }
    """
    commit_sha = input_data.get("commit_sha")
    commit_info = commit_sha[:8] if commit_sha else "NULL"

    # Initialize event emitter if context provided
    event_context = input_data.get("event_context")
    emitter = WorkflowEventEmitter(**event_context) if event_context else None

    if emitter:
        try:
            await emitter.emit_started(
                "persist_kg_activity",
                f"Persisting knowledge graph to Neo4j..."
            )
        except Exception as e:
            logger.warning(f"Failed to emit started event: {e}")

    logger.info(
        f"Persisting KG for {input_data['github_repo_name']} (delete-then-write, commit: {commit_info})"
    )

    service = KnowledgeGraphService(driver=Neo4jConnection.get_driver(), database=settings.NEO4J_DATABASE)

    try:
        activity.heartbeat("Starting Neo4j persistence")
        
        # Delete existing graph for this repo (latest-only enforcement)
        deleted_count = await service.delete_repo_graph(
            repo_id=input_data["repo_id"]
        )
        logger.info(
            f"Deleted {deleted_count} existing nodes for {input_data['github_repo_name']}"
        )

        if emitter:
            try:
                await emitter.emit_progress(
                    "persist_kg_activity",
                    f"Deleted {deleted_count} old nodes, creating new graph...",
                    metadata={"nodes_deleted": deleted_count}
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit progress event: {emit_err}")

        # Deserialize nodes and edges from dicts back to proper Python objects
        # (Temporal serializes dataclasses to dicts when passing between activities)
        nodes = [_deserialize_node(n) for n in input_data["graph_result"]["nodes"]]
        edges = [_deserialize_edge(e) for e in input_data["graph_result"]["edges"]]

        # Persist new graph
        result = await service.persist_kg(
            repo_id=input_data["repo_id"],
            github_repo_id=input_data["github_repo_id"],
            nodes=nodes,
            edges=edges,
            commit_sha=commit_sha,
        )

        logger.info(
            f"Persisted {result.nodes_created} nodes, "
            f"{result.edges_created} edges to Neo4j for {input_data['github_repo_name']}"
        )

        # Include deletion count in result
        result_dict = {
            **result.__dict__,
            "nodes_deleted": deleted_count,
        }

        if emitter:
            try:
                await emitter.emit_completed(
                    "persist_kg_activity",
                    f"Created {result.nodes_created} nodes, {result.edges_created} edges in Neo4j",
                    metadata={
                        "nodes_created": result.nodes_created,
                        "edges_created": result.edges_created,
                        "nodes_deleted": deleted_count,
                    }
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit completed event: {emit_err}")

        return result_dict

    except Exception as e:
        if emitter:
            try:
                await emitter.emit_failed(
                    "persist_kg_activity",
                    f"Neo4j persistence failed: {str(e)}",
                    metadata={"error": str(e)}
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit failed event: {emit_err}")

        logger.error(f"Failed to persist KG: {e}")
        raise ApplicationError(f"Neo4j persistence failed: {e}") from e
    
# Cleanup repo activity
@activity.defn
async def cleanup_repo_activity(local_path: str) -> dict:
    """
    Cleanup cloned repository directory.

    Args:
        local_path: str (can be dict with local_path key if event_context is included)

    Returns:
        {"status": "cleaned"}
    """
    # Handle both string and dict inputs (dict if event_context was added by workflow)
    if isinstance(local_path, dict):
        actual_path = local_path.get("local_path", local_path)
        event_context = local_path.get("event_context")
    else:
        actual_path = local_path
        event_context = None

    emitter = WorkflowEventEmitter(**event_context) if event_context else None

    if emitter:
        try:
            await emitter.emit_started(
                "cleanup_repo_activity",
                f"Cleaning up repository clone..."
            )
        except Exception as e:
            logger.warning(f"Failed to emit started event: {e}")

    logger.info(f"Cleaning up {actual_path}")

    service = RepoCloneService()

    try:
        await service.cleanup_repo(local_path=actual_path)

        if emitter:
            try:
                await emitter.emit_completed(
                    "cleanup_repo_activity",
                    f"Cleaned up repository clone",
                    metadata={"local_path": actual_path}
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit completed event: {emit_err}")

        return {"status": "cleaned"}
    except Exception as e:
        if emitter:
            try:
                await emitter.emit_failed(
                    "cleanup_repo_activity",
                    f"Cleanup failed: {str(e)}",
                    metadata={"error": str(e)}
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit failed event: {emit_err}")

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
            "ttl_days": int (optional, default: 30),
            "event_context": dict (optional)
        }

    Returns:
        {"nodes_deleted": int}
    """
    repo_id = input_data["repo_id"]
    ttl_days = input_data.get("ttl_days", 30)

    # Initialize event emitter if context provided
    event_context = input_data.get("event_context")
    emitter = WorkflowEventEmitter(**event_context) if event_context else None

    if emitter:
        try:
            await emitter.emit_started(
                "cleanup_stale_kg_nodes_activity",
                f"Cleaning up stale nodes from Neo4j..."
            )
        except Exception as e:
            logger.warning(f"Failed to emit started event: {e}")

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

        result = {"nodes_deleted": nodes_deleted}

        if emitter:
            try:
                await emitter.emit_completed(
                    "cleanup_stale_kg_nodes_activity",
                    f"Removed {nodes_deleted} stale nodes from Neo4j",
                    metadata={"nodes_deleted": nodes_deleted, "ttl_days": ttl_days}
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit completed event: {emit_err}")

        return result

    except Exception as e:
        if emitter:
            try:
                await emitter.emit_failed(
                    "cleanup_stale_kg_nodes_activity",
                    f"Stale nodes cleanup failed: {str(e)}",
                    metadata={"error": str(e)}
                )
            except Exception as emit_err:
                logger.warning(f"Failed to emit failed event: {emit_err}")

        logger.error(f"Failed to cleanup stale KG nodes: {e}")
        raise ApplicationError(f"Stale nodes cleanup failed: {e}") from e