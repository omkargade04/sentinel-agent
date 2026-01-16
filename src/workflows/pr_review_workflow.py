"""
PR Review Pipeline Temporal Workflow

Durable workflow for automated pull request code reviews using AI.
Follows established patterns from repo_indexing_workflow.py.
"""

from datetime import timedelta
from temporalio.common import RetryPolicy
from temporalio import workflow
from typing import Optional

from src.models.schemas.pr_review import (
    PRReviewRequest,
    PRReviewResult
)
from src.core.pr_review_config import pr_review_settings
from src.utils.logging import get_logger

# Activity imports (stubs for now - will be implemented in Phase 2-7)
from src.activities.pr_review_activities import (
    fetch_pr_context_activity,
    clone_pr_head_activity,
    build_seed_set_activity,
    retrieve_kg_candidates_activity,
    retrieve_and_assemble_context_activity,
    generate_review_activity,
    anchor_and_publish_activity,
    cleanup_pr_clone_activity,
)

logger = get_logger(__name__)


@workflow.defn
class PRReviewWorkflow:
    """
    Durable workflow for automated PR code reviews.

    Architecture:
    - Phase 1: Data Collection (deterministic) - GitHub API, cloning, AST analysis
    - Phase 2: Intelligent Context Assembly (LangGraph) - Neo4j query + context building
    - Phase 3: AI Review Generation (LangGraph) - LLM analysis + structured output
    - Phase 4: Publishing (deterministic with retry) - Diff anchoring + GitHub API

    Guarantees:
    - Resource cleanup (clone directories) in all scenarios
    - Idempotent execution (can retry safely)
    - Complete audit trail via database persistence
    """

    @workflow.run
    async def run(self, request: PRReviewRequest) -> PRReviewResult:
        """
        Orchestrate automated PR review generation and publishing.

        Args:
            request: PRReviewRequest containing GitHub PR details and repository context

        Returns:
            PRReviewResult with execution status and metrics

        Raises:
            Various exceptions for different failure modes (handled by Temporal retries)
        """
        workflow_id = workflow.info().workflow_id
        logger.info(
            f"Starting PR review workflow {workflow_id} for "
            f"{request.github_repo_name}#{request.pr_number} "
            f"(head: {request.head_sha[:8]})"
        )

        # ========================================================================
        # RETRY POLICIES
        # ========================================================================

        # Standard retry for transient failures
        standard_retry = RetryPolicy(
            maximum_attempts=pr_review_settings.timeouts.max_retry_attempts,
            initial_interval=timedelta(seconds=5),
            maximum_interval=timedelta(seconds=60),
            backoff_coefficient=pr_review_settings.timeouts.retry_backoff_factor,
        )

        # Limited retry for expensive operations
        expensive_retry = RetryPolicy(
            maximum_attempts=2,  # LLM calls are expensive
            initial_interval=timedelta(seconds=10),
            maximum_interval=timedelta(seconds=30),
            backoff_coefficient=2.0,
        )

        # No retry for permanent failures (auth, not found, etc.)
        no_retry = RetryPolicy(maximum_attempts=1)

        # ========================================================================
        # WORKFLOW STATE
        # Initialize all result variables to prevent NameError in error handling
        # ========================================================================

        clone_path: Optional[str] = None
        review_run_id: Optional[str] = None
        
        # Activity result variables (initialized to None for error stage detection)
        pr_context = None
        clone_result = None
        seed_set_result = None
        kg_result = None
        context_result = None
        review_result = None
        publish_result = None

        try:
            # ====================================================================
            # PHASE 1: DATA COLLECTION (Deterministic)
            # ====================================================================

            logger.info("Phase 1: Starting data collection")

            # Step 1.1: Fetch PR context from GitHub API
            pr_context = await workflow.execute_activity(
                fetch_pr_context_activity,
                request,
                start_to_close_timeout=timedelta(
                    seconds=pr_review_settings.timeouts.fetch_pr_context_timeout
                ),
                retry_policy=standard_retry
            )
            logger.info(
                f"Fetched PR context: {pr_context['total_files_changed']} files changed, "
                f"large_pr={pr_context['large_pr']}"
            )

            # Step 1.2: Clone PR head repository (authoritative source)
            clone_result = await workflow.execute_activity(
                clone_pr_head_activity,
                request,
                start_to_close_timeout=timedelta(
                    seconds=pr_review_settings.timeouts.clone_pr_head_timeout
                ),
                retry_policy=standard_retry  # Auth failures will surface here
            )
            clone_path = clone_result["clone_path"]
            logger.info(
                f"Cloned PR head to {clone_path} "
                f"({clone_result['clone_size_mb']:.1f}MB in {clone_result['clone_duration_ms']}ms)"
            )

            # Step 1.3: Build seed set (AST analysis of diff hunks)
            seed_set_input = {
                "clone_path": clone_path,
                "patches": pr_context["patches"]
            }
            seed_set_result = await workflow.execute_activity(
                build_seed_set_activity,
                seed_set_input,
                start_to_close_timeout=timedelta(
                    seconds=pr_review_settings.timeouts.build_seed_set_timeout
                ),
                retry_policy=standard_retry
            )
            seed_set = seed_set_result["seed_set"]
            logger.info(
                f"Built seed set: {seed_set.get('total_symbols', len(seed_set.get('seed_symbols', [])))} symbols, "
                f"{seed_set.get('total_files', len(set(s.get('file_path') for s in seed_set.get('seed_symbols', []))))} files affected"
            )
            
            # ====================================================================
            # KG CANDIDATE RETRIEVAL (Neo4j)
            # ====================================================================

            logger.info("Starting KG candidate retrieval")

            kg_input = {
                "repo_id": str(request.repo_id),
                "pr_head_sha": request.head_sha,
                "seed_set": seed_set,
            }
            kg_result = await workflow.execute_activity(
                retrieve_kg_candidates_activity,
                kg_input,
                start_to_close_timeout=timedelta(
                    seconds=pr_review_settings.timeouts.context_assembly_timeout // 2  # Half of context timeout
                ),
                retry_policy=standard_retry
            )
            logger.info(
                f"KG retrieval: {kg_result['stats']['total_candidates']} candidates, "
                f"{kg_result['stats']['kg_symbols_found']} symbols found, "
                f"drift={kg_result['has_drift']}"
            )

            # ====================================================================
            # PHASE 2: INTELLIGENT CONTEXT ASSEMBLY (LangGraph)
            # ====================================================================

            logger.info("Phase 2: Starting intelligent context assembly")

            context_input = {
                "repo_id": str(request.repo_id),
                "github_repo_name": request.github_repo_name,
                "pr_number": request.pr_number,

                "pr_head_sha": request.head_sha,
                "pr_base_sha": request.base_sha,

                "seed_set": seed_set,
                "kg_candidates": kg_result["kg_candidates"],  # From Phase 4
                "kg_commit_sha": kg_result["kg_commit_sha"],  # From Phase 4
                "patches": pr_context["patches"],
                "clone_path": clone_path,

                "limits": pr_review_settings.limits.model_dump(),
            }
            
            context_result = await workflow.execute_activity(
                retrieve_and_assemble_context_activity,
                context_input,
                start_to_close_timeout=timedelta(
                    seconds=pr_review_settings.timeouts.context_assembly_timeout
                ),
                retry_policy=standard_retry  # Neo4j/file system operations
            )
            context_pack = context_result["context_pack"]
            context_stats = context_pack.get("stats", {})
            logger.info(
                f"Assembled context pack: {context_stats.get('total_items', 0)} items, "
                f"{context_pack.get('total_context_characters', 0)} chars, "
                f"kg_drift={context_pack.get('kg_commit_sha') != request.head_sha if context_pack.get('kg_commit_sha') else False}"
            )

            # ====================================================================
            # PHASE 3: AI REVIEW GENERATION (LangGraph)
            # ====================================================================

            logger.info("Phase 3: Starting AI review generation")

            review_generation_input = {
                "context_pack": context_pack
            }
            review_result = await workflow.execute_activity(
                generate_review_activity,
                review_generation_input,
                start_to_close_timeout=timedelta(
                    seconds=pr_review_settings.timeouts.review_generation_timeout
                ),
                retry_policy=expensive_retry  # LLM calls are expensive, limit retries
            )
            review_output = review_result["review_output"]
            generation_stats = review_result.get("generation_stats", {})
            anchored_count = generation_stats.get("anchored_findings", 0)
            logger.info(
                f"Generated review: {review_output.get('total_findings', 0)} findings, "
                f"{anchored_count} anchorable, "
                f"confidence_rate={generation_stats.get('confidence_rate', 0):.1f}%"
            )

            # ====================================================================
            # PHASE 4: PUBLISHING (Deterministic with Retry)
            # ====================================================================

            logger.info("Phase 4: Starting review publishing")

            publish_input = {
                "review_output": review_output,
                "patches": pr_context["patches"],
                "github_repo_name": request.github_repo_name,
                "pr_number": request.pr_number,
                "head_sha": request.head_sha,
                "installation_id": request.installation_id
            }
            publish_result = await workflow.execute_activity(
                anchor_and_publish_activity,
                publish_input,
                start_to_close_timeout=timedelta(
                    seconds=pr_review_settings.timeouts.publish_review_timeout
                ),
                retry_policy=standard_retry  # GitHub API retry with rate limiting
            )
            review_run_id = publish_result["review_run_id"]
            logger.info(
                f"Published review: github_review_id={publish_result.get('github_review_id')}, "
                f"anchored={publish_result.get('anchored_comments', 0)}, "
                f"unanchored={publish_result.get('unanchored_findings', 0)}"
            )

            # ====================================================================
            # SUCCESS RESULT
            # ====================================================================

            result = PRReviewResult(
                status="completed",
                review_run_id=review_run_id,
                pr_number=request.pr_number,
                head_sha=request.head_sha,
                published=publish_result.get("published", False),
                github_review_id=publish_result.get("github_review_id"),
                total_findings=review_output.get("total_findings", 0),
                anchored_findings=publish_result.get("anchored_comments", 0),
                processing_duration_ms=int(
                    (workflow.now() - workflow.info().start_time).total_seconds() * 1000
                ),
                completed_at=workflow.now()
            )

            logger.info(
                f"PR review workflow completed successfully for "
                f"{request.github_repo_name}#{request.pr_number}"
            )
            return result

        except Exception as e:
            # ====================================================================
            # ERROR HANDLING
            # ====================================================================

            logger.error(
                f"PR review workflow failed for {request.github_repo_name}#{request.pr_number}: {e}",
                exc_info=True
            )

            # Determine error stage for debugging
            error_stage = "unknown"
            if not pr_context:
                error_stage = "fetch_pr_context"
            elif not clone_path:
                error_stage = "clone_pr_head"
            elif not seed_set_result:
                error_stage = "build_seed_set"
            elif not kg_result:
                error_stage = "kg_retrieval" 
            elif not context_result:
                error_stage = "context_assembly"
            elif not review_result:
                error_stage = "review_generation"
            elif not publish_result:
                error_stage = "publish_review"

            # Return failure result (don't re-raise - let Temporal handle workflow completion)
            result = PRReviewResult(
                status="failed",
                review_run_id=review_run_id or "unknown",
                pr_number=request.pr_number,
                head_sha=request.head_sha,
                published=False,
                error_message=str(e),
                error_stage=error_stage,
                completed_at=workflow.now()
            )
            return result

        finally:
            # ====================================================================
            # GUARANTEED CLEANUP
            # ====================================================================

            if clone_path:
                try:
                    await workflow.execute_activity(
                        cleanup_pr_clone_activity,
                        {"clone_path": clone_path},
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(maximum_attempts=2)  # Best effort cleanup
                    )
                    logger.info(f"Cleaned up clone directory: {clone_path}")
                except Exception as cleanup_error:
                    logger.warning(
                        f"Failed to cleanup clone directory {clone_path}: {cleanup_error}"
                    )
                    # Don't fail the workflow on cleanup errors


# ============================================================================
# WORKFLOW HELPER FUNCTIONS
# ============================================================================

def create_pr_review_workflow_id(repo_id: str, pr_number: int) -> str:
    """
    Create deterministic workflow ID for PR reviews.
    Ensures idempotency - same PR will have same workflow ID.
    """
    return f"pr-review:{repo_id}:{pr_number}"


def create_pr_review_task_queue() -> str:
    """Get the task queue name for PR review workflows."""
    return pr_review_settings.temporal_task_queue


async def start_pr_review_workflow(
    temporal_client,
    request: PRReviewRequest,
    workflow_id: Optional[str] = None
) -> str:
    """
    Start a PR review workflow with proper configuration.

    Args:
        temporal_client: Connected Temporal client
        request: PR review request
        workflow_id: Optional workflow ID (auto-generated if None)

    Returns:
        Workflow ID of the started workflow
    """
    if not workflow_id:
        workflow_id = create_pr_review_workflow_id(
            str(request.repo_id),
            request.pr_number
        )

    handle = await temporal_client.start_workflow(
        PRReviewWorkflow.run,
        request,
        id=workflow_id,
        task_queue=create_pr_review_task_queue(),
        # Workflow-level timeout (should be longer than sum of activity timeouts)
        execution_timeout=timedelta(minutes=30),
        # Allow workflow to run for up to 1 hour total (including retries)
        run_timeout=timedelta(hours=1),
    )

    logger.info(
        f"Started PR review workflow {workflow_id} for "
        f"{request.github_repo_name}#{request.pr_number}"
    )
    return workflow_id


# ============================================================================
# WORKFLOW QUERIES (for monitoring and debugging)
# ============================================================================

async def get_pr_review_workflow_status(
    temporal_client,
    workflow_id: str
) -> dict:
    """
    Get the status of a PR review workflow.

    Returns:
        Dictionary with workflow status information
    """
    try:
        handle = temporal_client.get_workflow_handle(workflow_id)
        result = await handle.result()
        return {
            "status": "completed",
            "result": result.dict() if result else None
        }
    except Exception as e:
        return {
            "status": "failed" if "failed" in str(e).lower() else "running",
            "error": str(e) if "failed" in str(e).lower() else None
        }


async def cancel_pr_review_workflow(
    temporal_client,
    workflow_id: str,
    reason: str = "Manual cancellation"
) -> bool:
    """
    Cancel a running PR review workflow.

    Returns:
        True if cancellation was successful
    """
    try:
        handle = temporal_client.get_workflow_handle(workflow_id)
        await handle.cancel()
        logger.info(f"Cancelled PR review workflow {workflow_id}: {reason}")
        return True
    except Exception as e:
        logger.error(f"Failed to cancel workflow {workflow_id}: {e}")
        return False