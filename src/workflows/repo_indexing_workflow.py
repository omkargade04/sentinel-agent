from datetime import timedelta
from temporalio.common import RetryPolicy
from src.activities.indexing_activities import (
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
    1. Resolve commit SHA from branch
    2. Clone repository
    3. Parse repository (AST + symbols)
    4. Persist metadata to Postgres
    5. Persist knowledge graph to Neo4j
    6. Cleanup local clone
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
            
            # Step 3: Persist metadata to Postgres (snapshot record + last_indexed_at)
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
            
            # Step 4: Persist knowledge graph to Neo4j
            persist_kg_input = {
                "repo_id": repo_request["repository"]["repo_id"],
                "github_repo_id": repo_request["repository"]["github_repo_id"],
                "github_repo_name": repo_request["repository"]["github_repo_name"],
                "graph_result": parse_result["graph_result"],
            }
            await workflow.execute_activity(
                persist_kg_activity,
                persist_kg_input,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry_policy,
            )
            logger.info("Knowledge graph persisted to Neo4j")
            
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