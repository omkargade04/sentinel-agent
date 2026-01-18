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

from src.langgraph.context_assembly import ContextAssemblyService
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


@activity.defn
async def retrieve_kg_candidates_activity(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retrieve context candidates from Neo4j Knowledge Graph.

    Phase 4 Implementation:
    - Query KG for seed symbol matches
    - Expand symbol neighbors (callers, callees, contains)
    - Retrieve import neighborhood for seed files
    - Fetch relevant documentation nodes

    Args:
        input_data: Contains repo_id, seed_set

    Returns:
        KG candidates with drift metadata and stats
    """
    from src.models.schemas.pr_review.seed_set import SeedSetS0

    repo_id = input_data["repo_id"]
    pr_head_sha = input_data["pr_head_sha"]
    seed_set_data = input_data["seed_set"]

    logger.info(f"Retrieving KG candidates for repo {repo_id}")

    # Reconstruct seed set from serialized data
    seed_set = SeedSetS0(**seed_set_data) if isinstance(seed_set_data, dict) else seed_set_data

    # Initialize result
    result = {
        "kg_candidates": None,
        "kg_commit_sha": None,
        "has_drift": False,
        "stats": {
            "kg_symbols_found": 0,
            "kg_symbols_missing": 0,
            "total_candidates": 0,
            "retrieval_duration_ms": 0,
        },
        "warnings": []
    }

    # Early exit if no seeds
    if not seed_set.seed_symbols and not seed_set.seed_files:
        logger.info(f"No seeds for repo {repo_id}, skipping KG retrieval")
        return result

    try:
        from src.core.neo4j import get_neo4j_driver
        from src.services.kg.kg_query_service import KGQueryService
        from src.services.kg.kg_candidate_retriever import KGCandidateRetriever

        driver = get_neo4j_driver()
        if not driver:
            result["warnings"].append("neo4j_driver_unavailable")
            logger.warning("Neo4j driver not available, returning empty candidates")
            return result

        kg_service = KGQueryService(driver)
        retriever = KGCandidateRetriever(kg_service)

        kg_result = await retriever.retrieve_candidates(
            repo_id=repo_id,
            seed_set=seed_set,
        )

        # Populate result
        result["kg_candidates"] = kg_result.to_dict()
        result["kg_commit_sha"] = kg_result.kg_commit_sha
        result["stats"] = {
            "kg_symbols_found": kg_result.stats.kg_symbols_found,
            "kg_symbols_missing": kg_result.stats.kg_symbols_missing,
            "total_candidates": kg_result.stats.total_candidates,
            "retrieval_duration_ms": kg_result.stats.retrieval_duration_ms,
        }
        result["warnings"] = kg_result.warnings

        # Check for drift
        if kg_result.kg_commit_sha and kg_result.kg_commit_sha != pr_head_sha:
            result["has_drift"] = True
            result["warnings"].append(
                f"kg_drift: KG at {kg_result.kg_commit_sha[:8]}, PR head at {pr_head_sha[:8]}"
            )
            logger.warning(
                f"KG drift detected: KG={kg_result.kg_commit_sha[:8]}, PR={pr_head_sha[:8]}"
            )

        logger.info(
            f"KG retrieval complete: {kg_result.stats.total_candidates} candidates, "
            f"{kg_result.stats.kg_symbols_found} symbols found"
        )

    except Exception as e:
        result["warnings"].append(f"kg_retrieval_error: {type(e).__name__}")
        logger.error(f"KG candidate retrieval failed: {e}", exc_info=True)
        # Graceful degradation - return empty candidates

    return result

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
    - candidate_enricher: Enrich candidates with seed context and prioritization
    - snippet_extractor: Extract code snippets from PR head
    - context_ranker: Score and prioritize context items
    - pack_assembler: Apply hard limits, build final pack

    Args:
        input_data: Contains repo_id, seed_set, clone_path, limits, kg_query_config

    Returns:
        ContextAssemblyOutput with bounded context pack
    """
    from src.models.schemas.pr_review.seed_set import SeedSetS0
    from src.models.schemas.pr_review.pr_patch import PRFilePatch

    # Extract inputs
    repo_id = input_data["repo_id"]
    github_repo_name = input_data["github_repo_name"]
    pr_number = input_data["pr_number"]
    pr_head_sha = input_data["pr_head_sha"]
    pr_base_sha = input_data.get("pr_base_sha", "")
    seed_set_data = input_data["seed_set"]
    kg_candidates = input_data.get("kg_candidates")  # From Phase 4 activity
    kg_commit_sha = input_data.get("kg_commit_sha")
    patches_data = input_data["patches"]
    limits = input_data["limits"]

    logger.info(
        f"Assembling context for {github_repo_name}#{pr_number} "
        f"with {len(seed_set_data.get('seed_symbols', []))} seeds, "
        f"{kg_candidates.get('stats', {}).get('total_candidates', 0) if kg_candidates else 0} KG candidates"
    )

    # Reconstruct typed objects
    seed_set = SeedSetS0(**seed_set_data) if isinstance(seed_set_data, dict) else seed_set_data
    patches = [PRFilePatch(**p) if isinstance(p, dict) else p for p in patches_data]

    # Phase 5: LangGraph context assembly implementation
    try:
        from src.langgraph.context_assembly import ContextAssemblyService, AssemblyConfig
        from src.models.schemas.pr_review.context_pack import ContextPackLimits

        # Build context limits
        context_limits = ContextPackLimits(
            max_context_items=limits.get("max_context_items", 35),
            max_total_characters=limits.get("max_total_characters", 120_000),
            max_lines_per_snippet=limits.get("max_lines_per_snippet", 120),
            max_chars_per_item=limits.get("max_chars_per_item", 2000),
            max_hops=limits.get("max_hops", 1),
            max_neighbors_per_seed=limits.get("max_callers_per_seed", 8),
        )

        # Build service config
        service_config = AssemblyConfig(
            failure_threshold=5,
            recovery_timeout=60,
            operation_timeout_seconds=300,
            max_context_items=context_limits.max_context_items,
            max_total_characters=context_limits.max_total_characters,
            max_lines_per_snippet=context_limits.max_lines_per_snippet,
            max_chars_per_item=context_limits.max_chars_per_item,
            max_hops=context_limits.max_hops,
            max_neighbors_per_seed=context_limits.max_neighbors_per_seed,
        )

        # Create service and execute context assembly
        context_service = ContextAssemblyService(config=service_config)

        kg_candidates_count = len(kg_candidates.get("candidates", [])) if kg_candidates else 0
        logger.info(
            f"Starting context assembly via service for {github_repo_name}#{pr_number} "
            f"with {len(seed_set.seed_symbols)} seeds, {kg_candidates_count} KG candidates"
        )

        # Delegate to service - returns ContextPack directly
        context_pack = await context_service.assemble_context(
            repo_id=uuid.UUID(repo_id),
            github_repo_name=github_repo_name,
            pr_number=pr_number,
            head_sha=pr_head_sha,
            base_sha=pr_base_sha,
            seed_set=seed_set,
            patches=patches,
            kg_candidates=kg_candidates or {"candidates": []},
            limits=context_limits,
            clone_path=input_data.get("clone_path"),
            kg_commit_sha=kg_commit_sha
        )

        logger.info(
            f"Context assembly completed for {github_repo_name}#{pr_number}: "
            f"{len(context_pack.context_items)} items, "
            f"{context_pack.total_context_characters} chars"
        )

        # Build assembly stats from context pack
        assembly_stats = {
            "kg_candidates_received": kg_candidates_count,
            "context_items_generated": len(context_pack.context_items),
            "items_truncated": context_pack.stats.items_truncated if context_pack.stats else 0,
            "total_characters": context_pack.total_context_characters,
            "execution_time_seconds": context_pack.assembly_duration_ms / 1000.0 if context_pack.assembly_duration_ms else 0,
            "fallback_used": False,
            "degradation_used": False,
        }

        return {
            "context_pack": context_pack.model_dump(),
            "assembly_stats": assembly_stats,
            "warnings": []
        }

    except Exception as context_assembly_error:
        # Comprehensive error handling with fallback
        logger.error(f"Context assembly failed for {github_repo_name}#{pr_number}: {context_assembly_error}")

        try:
            # Attempt graceful fallback with stub implementation
            kg_stats = kg_candidates.get("stats", {}) if kg_candidates else {}

            fallback_context_limits = ContextPackLimits(
                max_context_items=limits.get("max_context_items", 35),
                max_total_characters=limits.get("max_total_characters", 120_000),
                max_lines_per_snippet=limits.get("max_lines_per_snippet", 120),
                max_chars_per_item=limits.get("max_chars_per_item", 2000),
                max_hops=limits.get("max_hops", 1),
                max_neighbors_per_seed=limits.get("max_callers_per_seed", 8),
            )

            fallback_context_stats = ContextPackStats(
                total_items=0,
                total_characters=0,
                items_by_type={},
                items_by_source={},
                kg_symbols_found=kg_stats.get("kg_symbols_found", 0),
                kg_symbols_missing=kg_stats.get("kg_symbols_missing", 0),
            )

            fallback_context_pack = ContextPack(
                repo_id=uuid.UUID(repo_id),
                github_repo_name=github_repo_name,
                pr_number=pr_number,
                head_sha=pr_head_sha,
                base_sha=pr_base_sha,
                kg_commit_sha=kg_commit_sha,
                patches=patches,
                seed_set=seed_set,
                context_items=[],  # Empty due to failure
                limits=fallback_context_limits,
                stats=fallback_context_stats,
                assembly_timestamp=datetime.now().isoformat(),
                assembly_duration_ms=0,
            )

            fallback_assembly_stats = {
                "kg_candidates_received": kg_stats.get("total_candidates", 0),
                "context_items_generated": 0,
                "items_truncated": 0,
                "total_characters": 0,
                "execution_time_seconds": 0.0,
                "llm_requests_made": 0,
                "workflow_id": None,
                "quality_metrics": {},
                "fallback_used": True,
                "error_occurred": True,
                "error_type": type(context_assembly_error).__name__,
                "error_message": str(context_assembly_error)
            }

            logger.warning(
                f"Using fallback context pack for {github_repo_name}#{pr_number} "
                f"due to assembly error: {context_assembly_error}"
            )

            return {
                "context_pack": fallback_context_pack.model_dump(),
                "assembly_stats": fallback_assembly_stats,
                "warnings": [
                    f"Context assembly failed: {context_assembly_error}",
                    "Using empty context pack as fallback"
                ]
            }

        except Exception as fallback_error:
            # If even fallback fails, return minimal response
            logger.error(f"Fallback context assembly also failed: {fallback_error}")

            minimal_stats = {
                "kg_candidates_received": 0,
                "context_items_generated": 0,
                "items_truncated": 0,
                "total_characters": 0,
                "execution_time_seconds": 0.0,
                "llm_requests_made": 0,
                "workflow_id": None,
                "quality_metrics": {},
                "fallback_used": True,
                "error_occurred": True,
                "error_type": f"{type(context_assembly_error).__name__} -> {type(fallback_error).__name__}",
                "error_message": f"Primary: {context_assembly_error}, Fallback: {fallback_error}"
            }

            return {
                "context_pack": None,
                "assembly_stats": minimal_stats,
                "warnings": [
                    f"Context assembly completely failed: {context_assembly_error}",
                    f"Fallback also failed: {fallback_error}",
                    "Unable to generate context pack"
                ]
            }


# ============================================================================
# PHASE 3: REVIEW GENERATION ACTIVITIES (LangGraph)
# ============================================================================

@activity.defn
async def generate_review_activity(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI-powered review generation using LangGraph for iterative analysis.

    This activity orchestrates the 6-node review generation LangGraph workflow:
    1. ContextAnalyzerNode: Analyze context for patterns and focus areas
    2. DiffProcessorNode: Build diff mappings for anchoring
    3. PromptBuilderNode: Construct anti-hallucination LLM prompt
    4. LLMGeneratorNode: Generate findings via LLM
    5. FindingAnchorerNode: Anchor findings to diff positions
    6. QualityValidatorNode: Filter, validate, produce final output

    Args:
        input_data: Contains context_pack for LLM analysis

    Returns:
        ReviewGenerationOutput with structured LLM findings
    """
    from src.langgraph.review_generation import (
        ReviewGenerationService,
        ReviewGenerationConfig,
    )
    import time

    context_pack = input_data["context_pack"]
    patches = context_pack.get("patches", [])

    # Extract PR metadata for logging
    pr_info = f"{context_pack.get('github_repo_name', 'unknown')}#{context_pack.get('pr_number', '?')}"
    context_items_count = len(context_pack.get("context_items", []))

    logger.info(
        f"Starting review generation for {pr_info} with "
        f"{context_items_count} context items and {len(patches)} patches"
    )

    start_time = time.time()

    try:
        # Initialize review generation service with configuration from settings
        config = ReviewGenerationConfig(
            llm_provider=pr_review_settings.llm.provider,
            llm_model=pr_review_settings.llm.model,
            llm_temperature=0.1,  # Low temperature for consistent output
            max_tokens=pr_review_settings.llm.max_tokens,
            max_findings=pr_review_settings.limits.max_findings,
            min_confidence=0.5,
            workflow_timeout_seconds=pr_review_settings.timeouts.review_generation_timeout,
        )

        service = ReviewGenerationService(config=config)

        # Build limits from config
        limits = {
            "max_findings": config.max_findings,
            "min_confidence": config.min_confidence,
            "max_tokens": config.max_tokens,
        }

        # Execute review generation via the LangGraph workflow
        result = await service.generate_review_from_dict(
            context_pack_dict=context_pack,
            patches_dict=patches,
            limits=limits
        )

        generation_duration_ms = int((time.time() - start_time) * 1000)

        # Extract findings from result
        # Note: ReviewGenerationGraph._format_successful_result returns
        # findings/summary at top level, not under final_review_output
        findings = result.get("findings", [])
        summary = result.get("summary", "Review generated successfully.")

        # Build LLMReviewOutput
        review_output = LLMReviewOutput(
            findings=findings,
            summary=summary,
            patterns=result.get("patterns"),
            recommendations=result.get("recommendations"),
            total_findings=result.get("total_findings", len(findings)),
            high_confidence_findings=result.get("stats", {}).get("high_confidence", 0),
            review_timestamp=datetime.now().isoformat()
        )

        # Extract stats from result
        stats = result.get("stats", {})
        generation_metrics = result.get("generation_metrics", {})

        # Calculate anchored vs unanchored
        anchored_count = sum(1 for f in findings if f.get("hunk_id"))
        unanchored_count = len(findings) - anchored_count

        logger.info(
            f"Review generation completed for {pr_info}: "
            f"{len(findings)} findings ({anchored_count} anchored) "
            f"in {generation_duration_ms}ms"
        )

        return {
            "review_output": review_output.model_dump(),
            "generation_stats": {
                "total_findings_generated": len(findings),
                "high_confidence_findings": sum(1 for f in findings if f.get("confidence", 0) >= 0.7),
                "anchored_findings": anchored_count,
                "unanchored_findings": unanchored_count,
                "confidence_rate": (
                    sum(1 for f in findings if f.get("confidence", 0) >= 0.7) / max(len(findings), 1) * 100
                ),
                "generation_duration_ms": generation_duration_ms,
                "model_used": stats.get("model_used", config.llm_model),
                "severity_breakdown": {
                    "blocker_count": stats.get("blocker_count", 0),
                    "high_count": stats.get("high_count", 0),
                    "medium_count": stats.get("medium_count", 0),
                    "low_count": stats.get("low_count", 0),
                    "nit_count": stats.get("nit_count", 0),
                },
            },
            "llm_usage": {
                "total_requests": 1,
                "failed_requests": 0 if result.get("success", True) else 1,
                "total_tokens": generation_metrics.get("cost", {}).get("total_tokens", 0) if generation_metrics else 0
            },
            "workflow_metadata": result.get("workflow_metadata", {}),
            "quality_metrics": result.get("quality_metrics", {}),
            "fallback_used": result.get("fallback_used", False),
        }

    except Exception as e:
        generation_duration_ms = int((time.time() - start_time) * 1000)

        logger.error(
            f"Review generation failed for {pr_info}: {e}",
            exc_info=True
        )

        # Return graceful degradation output
        review_output = LLMReviewOutput(
            findings=[],
            summary=f"Review generation failed: {str(e)[:200]}",
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
                "confidence_rate": 0.0,
                "generation_duration_ms": generation_duration_ms,
                "model_used": pr_review_settings.llm.model,
                "token_usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                },
                "error": str(e),
                "error_type": type(e).__name__,
            },
            "llm_usage": {
                "total_requests": 1,
                "failed_requests": 1,
                "total_tokens": 0
            },
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
    
    # Phase 2: KG retrieval
    retrieve_kg_candidates_activity,

    # Phase 3: Context assembly (LangGraph)
    retrieve_and_assemble_context_activity,

    # Phase 4: Review generation (LangGraph)
    generate_review_activity,

    # Phase 5: Publishing
    anchor_and_publish_activity,

    # Cleanup
    cleanup_pr_clone_activity,
]