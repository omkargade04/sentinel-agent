from datetime import timedelta
from temporalio.common import RetryPolicy
from src.activities.indexing_activities import (
    check_indexing_needed_activity,
    clone_repo_activity,
    parse_repo_activity,
    persist_metadata_activity,
    persist_kg_activity,
    cleanup_repo_activity,
    cleanup_stale_kg_nodes_activity,
)
from temporalio import workflow
from src.utils.logging import get_logger
logger = get_logger(__name__)

@workflow.defn
class RepoIndexingWorkflow:
    """
    Durable workflow for repository indexing.
    
    Steps:
    0. Check if indexing needed (skip if SHA unchanged)
    1. Resolve commit SHA from branch
    2. Clone repository
    3. Parse repository (AST + symbols)
    4. Persist metadata to Postgres
    5. Persist knowledge graph to Neo4j
    6. Cleanup stale nodes
    7. Cleanup local clone
    """
    @workflow.run
    async def run(self, repo_request: dict):
        """
        Orchestrate repository indexing.
        
        Args:
            repo_request: {
                "installation_id": int,
                "repository": {
                    "github_repo_name": str,
                    "github_repo_id": int,
                    "repo_id": str,
                    "default_branch": str,
                    "repo_url": str
                }
            }
        """
        logger.info(f"Starting repository indexing workflow for {repo_request['repository']['github_repo_name']}")
        
        # Retry policy
        retry_policy = RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=10),
            maximum_interval=timedelta(seconds=30),
            backoff_coefficient=2.0,
        )
        
        # Non-retryable policy for auth/not-found errors
        no_retry_policy = RetryPolicy(maximum_attempts=1)
        
        # Step 0: Check if indexing is needed (skip if SHA unchanged)
        precheck_result = await workflow.execute_activity(
            check_indexing_needed_activity,
            repo_request,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=retry_policy
        )
        
        if not precheck_result['indexing_needed']:
            logger.info(
                f"Skipping indexing for {repo_request['repository']['github_repo_name']}: "
                f"{precheck_result['reason']} (SHA: {precheck_result['current_sha'][:8] if precheck_result['current_sha'] else 'None'})"
            )
            return {
                "status": "skipped",
                "repo": repo_request["repository"]["github_repo_name"],
                "reason": precheck_result["reason"],
                "current_sha": precheck_result["current_sha"],
                "latest_snapshot_sha": precheck_result["latest_snapshot_sha"],
            }
        
        logger.info(
            f"Indexing required for {repo_request['repository']['github_repo_name']}: "
            f"{precheck_result['reason']} "
            f"(current SHA: {precheck_result['current_sha'][:8] if precheck_result['current_sha'] else 'None'})"
        )
        
        clone_result = None
        try:
           # Step 1: Clone the repo
           # Uses no_retry for auth/404 errors (those are permanent)
            clone_result = await workflow.execute_activity(
                clone_repo_activity,
                repo_request,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy
            )
            commit_info = clone_result.get('commit_sha') or 'branch-based'
            logger.info(
                f"Cloned to {clone_result['local_path']} (identifier: {commit_info})"
            )
            
            # Setp 2: Parse repo (AST + symbols)
            parse_input = {
                "local_path": clone_result['local_path'],
                "github_repo_id": repo_request['repository']['github_repo_id'],
                "repo_id": repo_request['repository']['repo_id'],
                "commit_sha": clone_result['commit_sha'],
            }
            parse_result = await workflow.execute_activity(
                parse_repo_activity,
                parse_input,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy
            )
            logger.info(
                f"Parsed {parse_result['stats']['total_symbols']} symbols "
                f"from {parse_result['stats']['indexed_files']} files"
            )
            
            # Step 3: Persist knowledge graph to Neo4j (delete-then-write)
            persist_kg_input = {
                "repo_id": repo_request["repository"]["repo_id"],
                "github_repo_id": repo_request["repository"]["github_repo_id"],
                "github_repo_name": repo_request["repository"]["github_repo_name"],
                "graph_result": parse_result["graph_result"],
                "commit_sha": clone_result["commit_sha"],
            }
            persist_kg_result = await workflow.execute_activity(
                persist_kg_activity,
                persist_kg_input,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry_policy,
            )
            logger.info(
                f"Knowledge graph persisted to Neo4j "
                f"(deleted {persist_kg_result.get('nodes_deleted', 0)} old nodes, "
                f"created {persist_kg_result.get('nodes_created', 0)} new nodes)"
            )
            
            # Step 4: Persist metadata to Postgres (snapshot record + last_indexed_at)
            persist_input = {
                "repo_id": repo_request["repository"]["repo_id"],
                "github_repo_id": repo_request["repository"]["github_repo_id"],
                "commit_sha": clone_result["commit_sha"],
            }
            await workflow.execute_activity(
                persist_metadata_activity,
                persist_input,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )
            logger.info("Metadata persisted to Postgres")
            
            # Step 5: Cleanup stale KG nodes (nodes from previous commits that no longer exist)
            cleanup_kg_input = {
                "repo_id": repo_request["repository"]["repo_id"],
                "ttl_days": 7,  # Remove nodes not refreshed in last 7 days
            }
            cleanup_result = await workflow.execute_activity(
                cleanup_stale_kg_nodes_activity,
                cleanup_kg_input,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )
            logger.info(
                f"Cleaned up {cleanup_result['nodes_deleted']} stale KG nodes"
            )
            
            return {
                "status": "success",
                "repo": repo_request["repository"]["github_repo_name"],
                "commit_sha": clone_result["commit_sha"],
                "stats": parse_result["stats"],
                "nodes_deleted_before_write": persist_kg_result.get("nodes_deleted", 0),
                "stale_nodes_deleted": cleanup_result["nodes_deleted"],
            }
        except Exception as e:
            logger.error(f"Failed to clone repository: {str(e)}")
            raise
        finally:
            # Step 5: Always cleanup (even on failure)
            if clone_result:
                try:
                    await workflow.execute_activity(
                        cleanup_repo_activity,
                        clone_result["local_path"],
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                    logger.info(f"Cleaned up {clone_result['local_path']}")
                except Exception as e:
                    logger.warning(f"Cleanup failed: {e}")