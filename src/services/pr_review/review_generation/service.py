"""
Review Generation Service

Production-grade high-level service interface for AI-powered code review generation.

This service provides:
- Clean API for review generation
- Configuration management
- Comprehensive error handling
- Metrics and observability
- Integration with Temporal activities
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import UUID
from dataclasses import dataclass, field

from src.models.schemas.pr_review.context_pack import ContextPack
from src.models.schemas.pr_review.pr_patch import PRFilePatch
from src.models.schemas.pr_review.review_output import LLMReviewOutput, Finding

from .review_graph import ReviewGenerationGraph
from .exceptions import ReviewGenerationError, QualityValidationError
from src.services.pr_review.review_generation.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION MODELS
# ============================================================================

@dataclass
class ReviewGenerationConfig:
    """Configuration for review generation service."""

    # LLM Configuration
    llm_provider: str = "claude"  # claude, gemini, openai
    llm_model: Optional[str] = None  # Uses provider default if not specified
    llm_temperature: float = 0.1  # Low temperature for consistent output
    max_tokens: int = 4000

    # Review Generation Limits
    max_findings: int = 20  # Hard limit per TRD
    min_confidence: float = 0.5  # Minimum confidence threshold
    max_findings_per_file: int = 5  # Prevent clustering on single file

    # Anchoring Configuration
    require_anchoring: bool = False  # If True, only anchored findings are returned
    anchoring_fallback: bool = True  # Include unanchored findings in summary

    # Quality Thresholds
    high_confidence_threshold: float = 0.7
    critical_severity_confidence: float = 0.8  # Higher confidence required for blocker/high

    # Circuit Breaker Configuration
    failure_threshold: int = 5
    recovery_timeout: int = 60

    # Timeout Configuration
    workflow_timeout_seconds: float = 300.0  # 5 minutes total
    llm_timeout_seconds: float = 60.0  # 1 minute for LLM calls

    # Feature Flags
    enable_few_shot_examples: bool = True
    enable_anti_hallucination: bool = True
    enable_evidence_validation: bool = True


@dataclass
class ReviewGenerationMetrics:
    """Metrics collected during review generation."""

    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None

    # Input metrics
    input_context_items: int = 0
    input_patch_files: int = 0
    input_total_changes: int = 0

    # Output metrics
    total_findings_generated: int = 0
    anchored_findings: int = 0
    unanchored_findings: int = 0
    high_confidence_findings: int = 0

    # Performance metrics
    context_analysis_time_ms: float = 0.0
    diff_processing_time_ms: float = 0.0
    llm_generation_time_ms: float = 0.0
    anchoring_time_ms: float = 0.0
    validation_time_ms: float = 0.0
    total_time_ms: float = 0.0

    # Cost metrics (if available)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0

    @property
    def duration_seconds(self) -> float:
        """Calculate total processing duration."""
        end = self.end_time or datetime.utcnow()
        return (end - self.start_time).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for serialization."""
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "input": {
                "context_items": self.input_context_items,
                "patch_files": self.input_patch_files,
                "total_changes": self.input_total_changes
            },
            "output": {
                "total_findings": self.total_findings_generated,
                "anchored_findings": self.anchored_findings,
                "unanchored_findings": self.unanchored_findings,
                "high_confidence_findings": self.high_confidence_findings
            },
            "performance_ms": {
                "context_analysis": self.context_analysis_time_ms,
                "diff_processing": self.diff_processing_time_ms,
                "llm_generation": self.llm_generation_time_ms,
                "anchoring": self.anchoring_time_ms,
                "validation": self.validation_time_ms,
                "total": self.total_time_ms
            },
            "cost": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "estimated_cost_usd": self.estimated_cost_usd
            }
        }


# ============================================================================
# MAIN SERVICE CLASS
# ============================================================================

class ReviewGenerationService:
    """
    Production-grade service for AI-powered code review generation.

    This service orchestrates the complete review generation pipeline:
    1. Context analysis and preparation
    2. Diff processing and mapping
    3. LLM-based review generation
    4. Deterministic diff anchoring
    5. Quality validation and filtering

    Example usage:
        service = ReviewGenerationService(config=ReviewGenerationConfig())
        result = await service.generate_review(
            context_pack=context_pack,
            patches=patches
        )
    """

    def __init__(
        self,
        config: Optional[ReviewGenerationConfig] = None
    ):
        """
        Initialize ReviewGenerationService.

        Args:
            config: Service configuration. Uses defaults if not provided.
        """
        self.config = config or ReviewGenerationConfig()

        # Initialize the review generation graph
        graph_config = {
            "failure_threshold": self.config.failure_threshold,
            "recovery_timeout": self.config.recovery_timeout,
            "workflow_timeout": self.config.workflow_timeout_seconds,
            "max_findings": self.config.max_findings,
            "min_confidence": self.config.min_confidence,
            "max_tokens": self.config.max_tokens,
            "llm_provider": self.config.llm_provider,
        }

        self._review_graph = ReviewGenerationGraph(config=graph_config)

        # Service-level metrics
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0

        logger.info(
            f"Initialized ReviewGenerationService: "
            f"provider={self.config.llm_provider}, "
            f"max_findings={self.config.max_findings}, "
            f"min_confidence={self.config.min_confidence}"
        )

    async def generate_review(
        self,
        context_pack: ContextPack,
        patches: List[PRFilePatch],
        pr_metadata: Optional[Dict[str, Any]] = None
    ) -> LLMReviewOutput:
        """
        Generate AI-powered code review from context pack and patches.

        This is the main entry point for review generation. It takes the
        output from Phase 5 (Context Assembly) and produces structured
        review findings with diff anchoring.

        Args:
            context_pack: Assembled context from Phase 5
            patches: PR file patches with PRHunk data
            pr_metadata: Optional PR metadata (repo name, PR number, etc.)

        Returns:
            LLMReviewOutput with validated, anchored findings

        Raises:
            ReviewGenerationError: If generation fails
            QualityValidationError: If output validation fails
        """
        metrics = ReviewGenerationMetrics()
        self._total_requests += 1

        pr_info = pr_metadata or {}
        pr_identifier = f"{pr_info.get('github_repo_name', 'unknown')}#{pr_info.get('pr_number', '?')}"

        logger.info(
            f"Starting review generation for {pr_identifier} with "
            f"{len(context_pack.context_items)} context items and "
            f"{len(patches)} patches"
        )

        try:
            # Collect input metrics
            metrics.input_context_items = len(context_pack.context_items)
            metrics.input_patch_files = len(patches)
            metrics.input_total_changes = sum(p.additions + p.deletions for p in patches)

            # Convert to serializable format for workflow
            context_pack_dict = self._serialize_context_pack(context_pack)
            patches_dict = self._serialize_patches(patches)

            # Build limits from configuration
            limits = {
                "max_findings": self.config.max_findings,
                "min_confidence": self.config.min_confidence,
                "max_tokens": self.config.max_tokens,
                "require_anchoring": self.config.require_anchoring,
                "high_confidence_threshold": self.config.high_confidence_threshold,
                "critical_severity_confidence": self.config.critical_severity_confidence,
            }

            # Execute review generation via graph
            result = await self._review_graph.generate_review(
                context_pack=context_pack_dict,
                pr_patches=patches_dict,
                limits=limits
            )

            if not result.get("success"):
                raise ReviewGenerationError(
                    f"Review generation failed: {result.get('error_message', 'Unknown error')}",
                    recoverable=result.get("fallback_used", False)
                )

            # Convert to LLMReviewOutput
            review_output = self._build_review_output(result, context_pack, metrics)

            # Complete metrics
            metrics.end_time = datetime.utcnow()
            metrics.total_time_ms = metrics.duration_seconds * 1000
            metrics.total_findings_generated = len(review_output.findings)
            metrics.anchored_findings = len(review_output.anchored_findings)
            metrics.unanchored_findings = len(review_output.unanchored_findings)
            metrics.high_confidence_findings = sum(
                1 for f in review_output.findings if f.confidence >= self.config.high_confidence_threshold
            )

            self._successful_requests += 1

            logger.info(
                f"Review generation completed for {pr_identifier}: "
                f"{metrics.total_findings_generated} findings "
                f"({metrics.anchored_findings} anchored) in {metrics.duration_seconds:.2f}s"
            )

            return review_output

        except ReviewGenerationError:
            self._failed_requests += 1
            raise

        except Exception as e:
            self._failed_requests += 1
            logger.error(f"Review generation failed for {pr_identifier}: {e}")
            raise ReviewGenerationError(
                f"Review generation failed: {str(e)}",
                recoverable=True
            ) from e

    async def generate_review_from_dict(
        self,
        context_pack_dict: Dict[str, Any],
        patches_dict: List[Dict[str, Any]],
        limits: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate review from dictionary inputs (for Temporal activity integration).

        This method provides a simpler interface that accepts and returns
        dictionaries, making it suitable for Temporal activity serialization.

        Args:
            context_pack_dict: Serialized context pack
            patches_dict: Serialized patches list
            limits: Optional limits override

        Returns:
            Dictionary containing review output
        """
        metrics = ReviewGenerationMetrics()
        self._total_requests += 1

        try:
            metrics.input_context_items = len(context_pack_dict.get("context_items", []))
            metrics.input_patch_files = len(patches_dict)

            effective_limits = {
                "max_findings": self.config.max_findings,
                "min_confidence": self.config.min_confidence,
                "max_tokens": self.config.max_tokens,
                **(limits or {})
            }

            result = await self._review_graph.generate_review(
                context_pack=context_pack_dict,
                pr_patches=patches_dict,
                limits=effective_limits
            )

            metrics.end_time = datetime.utcnow()
            metrics.total_time_ms = metrics.duration_seconds * 1000

            if result.get("success"):
                self._successful_requests += 1
            else:
                self._failed_requests += 1

            # Add metrics to result
            result["generation_metrics"] = metrics.to_dict()

            return result

        except Exception as e:
            self._failed_requests += 1
            logger.error(f"Review generation from dict failed: {e}")
            return {
                "success": False,
                "error": type(e).__name__,
                "error_message": str(e),
                "findings": [],
                "summary": "Review generation failed",
                "generation_metrics": metrics.to_dict()
            }

    def _serialize_context_pack(self, context_pack: ContextPack) -> Dict[str, Any]:
        """Serialize ContextPack to dictionary for workflow processing."""
        return {
            "repo_id": str(context_pack.repo_id),
            "github_repo_name": context_pack.github_repo_name,
            "pr_number": context_pack.pr_number,
            "head_sha": context_pack.head_sha,
            "base_sha": context_pack.base_sha,
            "context_items": [
                {
                    "item_id": item.item_id,
                    "source": item.source.value if hasattr(item.source, 'value') else str(item.source),
                    "item_type": item.item_type.value if hasattr(item.item_type, 'value') else str(item.item_type),
                    "file_path": item.file_path,
                    "start_line": item.start_line,
                    "end_line": item.end_line,
                    "title": item.title,
                    "snippet": item.snippet,
                    "code_snippet": item.snippet,  # Alias for compatibility
                    "relevance_score": item.relevance_score,
                    "priority": item.priority,
                    "truncated": item.truncated,
                    "is_seed_symbol": item.item_type.value == "changed_symbol" if hasattr(item.item_type, 'value') else False,
                }
                for item in context_pack.context_items
            ],
            "seed_set": {
                "seed_symbols": [
                    {
                        "name": s.name,
                        "type": s.type,
                        "file_path": s.file_path,
                        "line_number": s.line_number,
                    }
                    for s in context_pack.seed_set.seed_symbols
                ] if context_pack.seed_set else []
            },
            "stats": {
                "total_items": context_pack.stats.total_items if context_pack.stats else 0,
                "total_characters": context_pack.stats.total_characters if context_pack.stats else 0,
            }
        }

    def _serialize_patches(self, patches: List[PRFilePatch]) -> List[Dict[str, Any]]:
        """Serialize PRFilePatch list to dictionaries for workflow processing."""
        serialized = []

        for patch in patches:
            patch_dict = {
                "file_path": patch.file_path,
                "additions": patch.additions,
                "deletions": patch.deletions,
                "changes": patch.changes,
                "status": patch.status,
                "hunks": []
            }

            # Serialize hunks if available
            if hasattr(patch, 'hunks') and patch.hunks:
                for hunk in patch.hunks:
                    hunk_dict = {
                        "hunk_id": hunk.hunk_id,
                        "old_start": hunk.old_start,
                        "old_count": hunk.old_count,
                        "new_start": hunk.new_start,
                        "new_count": hunk.new_count,
                        "lines": hunk.lines if hasattr(hunk, 'lines') else [],
                    }
                    patch_dict["hunks"].append(hunk_dict)

            serialized.append(patch_dict)

        return serialized

    def _build_review_output(
        self,
        result: Dict[str, Any],
        context_pack: ContextPack,
        metrics: ReviewGenerationMetrics
    ) -> LLMReviewOutput:
        """Build LLMReviewOutput from workflow result."""
        findings_data = result.get("findings", [])
        stats = result.get("stats", {})

        # Convert finding dictionaries to Finding objects
        findings = []
        for f_data in findings_data:
            try:
                finding = Finding(
                    finding_id=f_data.get("finding_id", f"finding_{len(findings) + 1}"),
                    severity=f_data.get("severity", "medium"),
                    category=f_data.get("category", "maintainability"),
                    title=f_data.get("title", "Review Finding"),
                    message=f_data.get("message", "Please review this code."),
                    suggested_fix=f_data.get("suggested_fix", "Review and update as needed."),
                    file_path=f_data.get("file_path", ""),
                    hunk_id=f_data.get("hunk_id"),
                    line_in_hunk=f_data.get("line_in_hunk"),
                    confidence=f_data.get("confidence", 0.5),
                    related_symbols=f_data.get("related_symbols", []),
                    code_examples=f_data.get("code_examples", [])
                )
                findings.append(finding)
            except Exception as e:
                logger.warning(f"Failed to create Finding from data: {e}")
                continue

        # Calculate counts
        high_confidence_count = sum(
            1 for f in findings if f.confidence >= self.config.high_confidence_threshold
        )

        return LLMReviewOutput(
            findings=findings,
            summary=result.get("summary", "Review generated successfully."),
            patterns=result.get("patterns", []),
            recommendations=result.get("recommendations", []),
            total_findings=len(findings),
            high_confidence_findings=high_confidence_count,
            stats=None,  # Can be populated with ReviewGenerationStats if needed
            review_timestamp=datetime.utcnow().isoformat(),
            review_version="v1"
        )

    def get_metrics(self) -> Dict[str, Any]:
        """Get current service metrics for monitoring."""
        success_rate = (
            self._successful_requests / self._total_requests
            if self._total_requests > 0 else 1.0
        )

        return {
            "service_metrics": {
                "total_requests": self._total_requests,
                "successful_requests": self._successful_requests,
                "failed_requests": self._failed_requests,
                "success_rate": success_rate,
            },
            "config": {
                "llm_provider": self.config.llm_provider,
                "max_findings": self.config.max_findings,
                "min_confidence": self.config.min_confidence,
                "workflow_timeout": self.config.workflow_timeout_seconds,
            },
            "graph_metrics": self._review_graph.get_metrics()
        }

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform comprehensive health check on the review generation service.

        Returns:
            Health status with component-level details
        """
        service_health = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "service": "review_generation",
            "components": {}
        }

        # Check graph health
        graph_health = await self._review_graph.health_check()
        service_health["components"]["review_graph"] = graph_health

        # Propagate status
        if graph_health.get("status") != "healthy":
            service_health["status"] = graph_health.get("status", "degraded")

        # Check service-level success rate
        if self._total_requests > 10:
            success_rate = self._successful_requests / self._total_requests
            service_health["components"]["success_rate"] = {
                "status": "healthy" if success_rate >= 0.90 else "degraded",
                "value": success_rate,
                "threshold": 0.90
            }

            if success_rate < 0.50:
                service_health["status"] = "unhealthy"
            elif success_rate < 0.90:
                service_health["status"] = "degraded"

        return service_health

    async def reinitialize(self) -> bool:
        """
        Reinitialize service components.

        Useful for recovery after configuration changes.

        Returns:
            True if reinitialization succeeded
        """
        return await self._review_graph.reinitialize()