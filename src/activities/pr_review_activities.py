"""
PR Review Pipeline Activity Stubs

Activity definitions for the PR review Temporal workflow.
These are stubs for Phase 1 - actual implementations will be added in subsequent phases.

Activities follow the existing patterns from indexing_activities.py.
"""

from temporalio import activity
from typing import Dict, Any, Optional
from datetime import datetime
import uuid

from src.models.schemas.pr_review import (
    PRReviewRequest,
    PRFilePatch,
    SeedSetS0,
    ContextPack,
    ContextPackLimits,
    ContextPackStats,
    LLMReviewOutput,
)
from src.core.pr_review_config import pr_review_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# PHASE 1: DATA COLLECTION ACTIVITIES
# ============================================================================

@activity.defn
async def fetch_pr_context_activity(request: PRReviewRequest) -> Dict[str, Any]:
    """
    Fetch PR context from GitHub API including file patches and metadata.

    Phase 2 Implementation:
    - GitHub API integration for PR details
    - Parse unified diff patches into structured hunks
    - Validate PR is suitable for review (size limits, file types)

    Args:
        request: PR review request with GitHub details

    Returns:
        FetchPRContextOutput with patches and metadata
    """
    from src.services.github.pr_api_client import PRApiClient
    from src.services.diff_parsing.unified_diff_parser import UnifiedDiffParser
    from src.exceptions.pr_review_exceptions import (
        PRTooLargeException,
        BinaryFileException,
        InvalidDiffFormatException
    )

    logger.info(
        f"Fetching PR context for {request.github_repo_name}#{request.pr_number}"
    )

    try:
        # Initialize services
        pr_client = PRApiClient()
        diff_parser = UnifiedDiffParser()

        # Fetch PR details and metadata
        pr_details = await pr_client.get_pr_details(
            request.github_repo_name,
            request.pr_number,
            request.installation_id
        )

        # Fetch PR files with diffs
        pr_files = await pr_client.get_pr_files(
            request.github_repo_name,
            request.pr_number,
            request.installation_id
        )

        logger.info(f"Fetched {len(pr_files)} files for PR {request.pr_number}")

        # Validate PR size limits before processing
        if len(pr_files) > pr_review_settings.limits.max_changed_files:
            raise PRTooLargeException(len(pr_files), pr_review_settings.limits.max_changed_files)

        # Parse files into structured patches
        patches = []
        skipped_binary_files = 0
        parsing_errors = 0

        for file_data in pr_files:
            try:
                patch = diff_parser._parse_single_file(file_data)
                if patch:
                    patches.append(patch)
            except BinaryFileException:
                skipped_binary_files += 1
                logger.debug(f"Skipped binary file: {file_data.get('filename')}")
            except (InvalidDiffFormatException, Exception) as e:
                parsing_errors += 1
                logger.warning(
                    f"Failed to parse file {file_data.get('filename', 'unknown')}: {e}"
                )

        # Final validation - ensure we have some parseable files
        if not patches and pr_files:
            raise InvalidDiffFormatException("No files could be parsed from PR")

        # Determine if this is a large PR
        large_pr = (
            len(patches) > pr_review_settings.limits.max_changed_files // 2 or
            sum(patch.changes for patch in patches) > 500  # Total line changes
        )

        logger.info(
            f"Successfully parsed PR context: {len(patches)} patches, "
            f"{skipped_binary_files} binary files skipped, "
            f"{parsing_errors} parsing errors, large_pr={large_pr}"
        )

        return {
            "pr_id": str(pr_details.get("id", uuid.uuid4())),
            "patches": [patch.model_dump() for patch in patches],
            "total_files_changed": len(patches),
            "large_pr": large_pr,
            "pr_metadata": {
                "title": pr_details.get("title", ""),
                "author": pr_details.get("user", {}).get("login", ""),
                "created_at": pr_details.get("created_at", datetime.now().isoformat()),
                "updated_at": pr_details.get("updated_at"),
                "state": pr_details.get("state"),
                "draft": pr_details.get("draft", False),
                "mergeable": pr_details.get("mergeable"),
                "base_ref": pr_details.get("base", {}).get("ref"),
                "head_ref": pr_details.get("head", {}).get("ref"),
            },
            "parsing_stats": {
                "files_fetched": len(pr_files),
                "files_parsed": len(patches),
                "binary_files_skipped": skipped_binary_files,
                "parsing_errors": parsing_errors,
            }
        }

    except Exception as e:
        logger.error(
            f"Failed to fetch PR context for {request.github_repo_name}#{request.pr_number}: {e}",
            exc_info=True
        )
        raise


@activity.defn
async def clone_pr_head_activity(request: PRReviewRequest) -> Dict[str, Any]:
    """
    Clone repository at PR head SHA to local filesystem (authoritative source).

    Phase 2 Implementation:
    - GitHub App authentication for repository access
    - Secure cloning to isolated temporary directory
    - Validate clone integrity and file permissions

    Args:
        request: PR review request with repository details

    Returns:
        ClonePRHeadOutput with clone path and metadata
    """
    from src.services.cloning.pr_clone_service import PRCloneService
    import os
    import time

    logger.info(
        f"Cloning PR head {request.head_sha[:8]} for {request.github_repo_name}"
    )

    try:
        # Initialize clone service
        clone_service = PRCloneService()

        # Record start time for performance metrics
        start_time = time.time()

        # Clone PR head with security validation
        clone_path = await clone_service.clone_pr_head(
            repo_name=request.github_repo_name,
            head_sha=request.head_sha,
            installation_id=request.installation_id
        )

        # Calculate duration
        clone_duration_ms = int((time.time() - start_time) * 1000)

        # Get clone metadata
        clone_info = await clone_service.get_clone_info(clone_path)
        clone_size_bytes = clone_info.get("size_bytes", 0)
        clone_size_mb = clone_size_bytes / (1024 * 1024)

        # Count files in clone (rough estimate)
        file_count = 0
        try:
            for root, dirs, files in os.walk(clone_path):
                # Skip .git directory
                if '.git' in root:
                    continue
                file_count += len(files)
        except Exception as e:
            logger.warning(f"Failed to count files in clone: {e}")

        logger.info(
            f"Successfully cloned {request.github_repo_name}@{request.head_sha[:8]} "
            f"to {clone_path} ({clone_size_mb:.1f}MB, {file_count} files, {clone_duration_ms}ms)"
        )

        return {
            "clone_path": clone_path,
            "clone_size_mb": clone_size_mb,
            "clone_duration_ms": clone_duration_ms,
            "file_count": file_count,
            "clone_metadata": {
                "current_sha": clone_info.get("current_sha", request.head_sha),
                "commit_message": clone_info.get("commit_message"),
                "author_name": clone_info.get("author_name"),
                "author_email": clone_info.get("author_email"),
                "commit_date": clone_info.get("commit_date"),
            }
        }

    except Exception as e:
        logger.error(
            f"Failed to clone PR head {request.github_repo_name}@{request.head_sha}: {e}",
            exc_info=True
        )
        raise


@activity.defn
async def build_seed_set_activity(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract seed symbols from PR diff hunks using AST analysis.

    Phase 3 Implementation:
    - Tree-sitter integration for multi-language AST parsing
    - Symbol extraction from changed lines in diff hunks
    - Symbol-to-hunk mapping for diff anchoring

    Args:
        input_data: Contains clone_path and patches

    Returns:
        BuildSeedSetOutput with seed symbols and files
    """
    from src.services.seed_generation import SeedSetBuilder
    from src.models.schemas.pr_review.pr_patch import PRFilePatch
    
    clone_path = input_data["clone_path"]
    patches_data = input_data["patches"]

    logger.info(
        f"Building seed set from {len(patches_data)} patches at {clone_path}"
    )

    try:
        # Convert dict patches to PRFilePatch objects
        patches = [PRFilePatch(**p) if isinstance(p, dict) else p for p in patches_data]
        
        # Build seed set using AST analysis
        builder = SeedSetBuilder(
            clone_path=clone_path,
            max_file_size_bytes=pr_review_settings.limits.max_file_size_bytes if hasattr(pr_review_settings.limits, 'max_file_size_bytes') else 1_000_000,
            max_symbols_per_file=pr_review_settings.limits.max_symbols_per_file if hasattr(pr_review_settings.limits, 'max_symbols_per_file') else 200,
        )
        
        seed_set, stats = builder.build_seed_set(patches)
        
        logger.info(
            f"Built seed set: {seed_set.total_symbols} symbols from "
            f"{stats.files_with_symbols} files, {len(seed_set.seed_files)} seed files, "
            f"{stats.parse_errors} parse errors"
        )
        
        return {
            "seed_set": seed_set.model_dump(),
            "stats": {
                "files_processed": stats.files_processed,
                "files_with_symbols": stats.files_with_symbols,
                "files_skipped": stats.files_skipped,
                "symbols_extracted": stats.total_symbols_extracted,
                "symbols_overlapping": stats.total_symbols_overlapping,
                "parse_errors": stats.parse_errors,
                "unsupported_languages": stats.unsupported_languages,
            }
        }
        
    except Exception as e:
        logger.error(
            f"Failed to build seed set at {clone_path}: {e}",
            exc_info=True
        )
        raise


# ============================================================================
# PHASE 2: CONTEXT ASSEMBLY ACTIVITIES (LangGraph)
# ============================================================================

@activity.defn
async def retrieve_and_assemble_context_activity(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Intelligent context assembly using LangGraph for multi-step reasoning.

    Phase 5 Implementation:
    - LangGraph context assembly workflow
    - Neo4j knowledge graph queries
    - Relevance scoring and prioritization
    - Hard limits application

    LangGraph nodes:
    - seed_analyzer: Analyze seed symbols for context needs
    - kg_querier: Query Neo4j with intelligent expansion
    - snippet_extractor: Extract code snippets from PR head
    - context_ranker: Score and prioritize context items
    - pack_assembler: Apply hard limits, build final pack

    Args:
        input_data: Contains repo_id, seed_set, clone_path, limits, kg_query_config

    Returns:
        ContextAssemblyOutput with bounded context pack
    """
    repo_id = input_data["repo_id"]
    seed_set = input_data["seed_set"]
    limits = input_data["limits"]

    logger.info(
        f"[STUB] Assembling context for repo {repo_id} with {len(seed_set.get('seed_symbols', []))} seed symbols"
    )

    # TODO Phase 5: Implement LangGraph context assembly
    # - context_graph = create_context_assembly_graph()
    # - tools = [kg_find_symbol_tool, kg_expand_neighbors_tool, extract_snippet_tool]
    # - result = await context_graph.ainvoke({
    # -     "seed_set": seed_set,
    # -     "repo_id": repo_id,
    # -     "constraints": limits
    # - })

    # Stub implementation - create ContextPackLimits from config
    context_limits = ContextPackLimits(
        max_context_items=limits.get("max_context_items", 35),
        max_total_characters=limits.get("max_total_characters", 120_000),
        max_lines_per_snippet=limits.get("max_lines_per_snippet", 120),
        max_chars_per_item=limits.get("max_chars_per_item", 2000),
        max_hops=limits.get("max_hops", 1),
        max_neighbors_per_seed=limits.get("max_callers_per_seed", 8),
    )
    context_stats = ContextPackStats(
        total_items=0,
        total_characters=0,
        items_by_type={},
        items_by_source={},
    )
    context_pack = ContextPack(
        repo_id=uuid.UUID(repo_id),
        github_repo_name="stub/repo",
        pr_number=123,
        head_sha="a" * 40,
        base_sha="b" * 40,
        patches=[],
        seed_set=SeedSetS0(),
        context_items=[],
        limits=context_limits,
        stats=context_stats,
        assembly_timestamp=datetime.now().isoformat(),
    )

    return {
        "context_pack": context_pack.model_dump(),
        "assembly_stats": {
            "neo4j_queries": 0,
            "kg_symbols_found": 0,
            "kg_symbols_missing": 0,
            "context_items_generated": 0,
            "items_truncated": 0
        },
        "warnings": []
    }


# ============================================================================
# PHASE 3: REVIEW GENERATION ACTIVITIES (LangGraph)
# ============================================================================

@activity.defn
async def generate_review_activity(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI-powered review generation using LangGraph for iterative analysis.

    Phase 6 Implementation:
    - LangGraph review generation workflow
    - Multi-step LLM reasoning with validation loops
    - Structured output with schema enforcement
    - Confidence scoring and quality metrics

    LangGraph nodes:
    - context_analyzer: Deep analysis of changes and patterns
    - finding_generator: Generate potential findings via LLM
    - finding_validator: Validate findings against context
    - suggestion_crafter: Create actionable fix suggestions
    - output_formatter: JSON schema validation

    Args:
        input_data: Contains context_pack for LLM analysis

    Returns:
        ReviewGenerationOutput with structured LLM findings
    """
    context_pack = input_data["context_pack"]

    logger.info(
        f"[STUB] Generating review for context pack with {context_pack.get('stats', {}).get('total_items', 0)} items"
    )

    # TODO Phase 6: Implement LangGraph review generation
    # - review_graph = create_review_generation_graph()
    # - llm_client = create_llm_client(pr_review_settings.llm)
    # - result = await review_graph.ainvoke({
    # -     "context_pack": context_pack,
    # -     "llm_config": pr_review_settings.llm.dict()
    # - })

    # Stub implementation
    review_output = LLMReviewOutput(
        findings=[],
        summary="Stub review summary - actual implementation in Phase 6",
        total_findings=0,
        high_confidence_findings=0,
        review_timestamp=datetime.now().isoformat()
    )

    return {
        "review_output": review_output.model_dump(),
        "generation_stats": {
            "total_findings_generated": 0,
            "high_confidence_findings": 0,
            "anchored_findings": 0,
            "unanchored_findings": 0,
            "generation_duration_ms": 0,
            "model_used": pr_review_settings.llm.model,
            "token_usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        },
        "llm_usage": {
            "total_requests": 0,
            "failed_requests": 0,
            "total_tokens": 0
        }
    }


# ============================================================================
# PHASE 4: PUBLISHING ACTIVITIES
# ============================================================================

@activity.defn
async def anchor_and_publish_activity(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic review publishing with diff anchoring and GitHub API integration.

    Phase 7 Implementation:
    - Diff position calculation for inline comments
    - GitHub API review creation with rate limiting
    - Fallback strategies for unanchorable findings
    - Audit trail persistence

    Args:
        input_data: Contains review_output, patches, and GitHub details

    Returns:
        PublishReviewOutput with publishing results
    """
    review_output = input_data["review_output"]
    github_repo_name = input_data["github_repo_name"]
    pr_number = input_data["pr_number"]

    logger.info(
        f"[STUB] Publishing review for {github_repo_name}#{pr_number} "
        f"with {review_output.get('total_findings', 0)} findings"
    )

    # TODO Phase 7: Implement review publishing
    # - diff_calculator = DiffPositionCalculator()
    # - github_client = GitHubRetryClient(installation_id)
    # - anchored, unanchored = calculate_diff_positions(findings, patches)
    # - review_id = await github_client.create_review(repo, pr_number, comments, summary)

    # Stub implementation - create review run record in database
    review_run_id = str(uuid.uuid4())

    return {
        "published": False,  # Will be True when actually implemented
        "github_review_id": None,
        "review_run_id": review_run_id,
        "anchored_comments": 0,
        "unanchored_findings": review_output.get("total_findings", 0),
        "fallback_used": False,
        "publish_stats": {
            "github_api_calls": 0,
            "rate_limit_delays": 0,
            "retry_attempts": 0,
            "publish_duration_ms": 0
        }
    }


# ============================================================================
# CLEANUP ACTIVITIES
# ============================================================================

@activity.defn
async def cleanup_pr_clone_activity(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clean up temporary clone directory and associated resources.

    Args:
        input_data: Contains clone_path to clean up

    Returns:
        Cleanup confirmation
    """
    from src.services.cloning.pr_clone_service import PRCloneService
    import time

    clone_path = input_data["clone_path"]

    logger.info(f"Cleaning up clone directory: {clone_path}")

    try:
        start_time = time.time()

        # Initialize clone service for proper cleanup
        clone_service = PRCloneService()

        # Perform secure cleanup
        await clone_service.cleanup_clone(clone_path)

        cleanup_duration_ms = int((time.time() - start_time) * 1000)

        logger.info(f"Successfully cleaned up clone directory: {clone_path}")

        return {
            "cleaned_up": True,
            "path": clone_path,
            "cleanup_duration_ms": cleanup_duration_ms
        }

    except Exception as e:
        logger.warning(f"Error during cleanup of {clone_path}: {e}")

        # Don't fail the workflow on cleanup errors - just log them
        return {
            "cleaned_up": False,
            "path": clone_path,
            "cleanup_duration_ms": 0,
            "error": str(e)
        }


# ============================================================================
# UTILITY FUNCTIONS FOR ACTIVITIES
# ============================================================================

def get_activity_retry_policy() -> Dict[str, Any]:
    """Get standard retry policy for PR review activities."""
    return {
        "maximum_attempts": pr_review_settings.timeouts.max_retry_attempts,
        "initial_interval": "5s",
        "maximum_interval": "60s",
        "backoff_coefficient": pr_review_settings.timeouts.retry_backoff_factor,
    }


def get_activity_timeout(activity_name: str) -> int:
    """Get timeout for specific activity in seconds."""
    timeouts = {
        "fetch_pr_context": pr_review_settings.timeouts.fetch_pr_context_timeout,
        "clone_pr_head": pr_review_settings.timeouts.clone_pr_head_timeout,
        "build_seed_set": pr_review_settings.timeouts.build_seed_set_timeout,
        "context_assembly": pr_review_settings.timeouts.context_assembly_timeout,
        "review_generation": pr_review_settings.timeouts.review_generation_timeout,
        "publish_review": pr_review_settings.timeouts.publish_review_timeout,
    }
    return timeouts.get(activity_name, 300)  # Default 5 minutes


# ============================================================================
# ACTIVITY REGISTRATION (for Temporal worker)
# ============================================================================

PR_REVIEW_ACTIVITIES = [
    # Phase 1: Data collection
    fetch_pr_context_activity,
    clone_pr_head_activity,
    build_seed_set_activity,

    # Phase 2: Context assembly (LangGraph)
    retrieve_and_assemble_context_activity,

    # Phase 3: Review generation (LangGraph)
    generate_review_activity,

    # Phase 4: Publishing
    anchor_and_publish_activity,

    # Cleanup
    cleanup_pr_clone_activity,
]