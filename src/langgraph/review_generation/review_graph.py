"""
Review Generation Graph - Integration Layer

Provides integration wrapper for review generation workflow with:
- Circuit breaker protection for LLM calls
- Graceful fallback strategies
- Health checks and monitoring
- Configuration-driven behavior
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

from .langgraph_workflow import ReviewGenerationWorkflow
from .exceptions import ReviewGenerationError, LLMGenerationError
from src.langgraph.review_generation.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class ReviewGenerationGraph:
    """
    Integration wrapper for review generation workflow.

    Provides a clean interface for the review generation pipeline with:
    - Circuit breaker protection for fault tolerance
    - Fallback strategies for graceful degradation
    - Health monitoring and metrics collection
    - Configuration-driven behavior

    This class follows the same pattern as ContextAssemblyGraph for consistency.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize review generation graph.

        Args:
            config: Configuration dictionary with the following optional keys:
                - failure_threshold: Circuit breaker failure threshold (default: 5)
                - recovery_timeout: Circuit breaker recovery timeout in seconds (default: 60)
                - workflow_timeout: Total workflow timeout in seconds (default: 300)
                - max_findings: Maximum findings to generate (default: 20)
                - min_confidence: Minimum confidence threshold (default: 0.5)
                - llm_provider: LLM provider to use (default: from environment)
        """
        self.config = config or {}
        self._workflow: Optional[ReviewGenerationWorkflow] = None
        self._circuit_breaker: Optional[CircuitBreaker] = None
        self._initialized_at: Optional[datetime] = None

        # Metrics tracking
        self._total_reviews = 0
        self._successful_reviews = 0
        self._failed_reviews = 0
        self._fallback_reviews = 0

        self._initialize_components()

    def _initialize_components(self) -> None:
        """Initialize workflow components with error handling."""
        try:
            # Initialize circuit breaker for LLM protection
            self._circuit_breaker = CircuitBreaker(
                failure_threshold=self.config.get('failure_threshold', 5),
                recovery_timeout=self.config.get('recovery_timeout', 60),
                name="review_generation"
            )

            # Initialize the 6-node workflow
            self._workflow = ReviewGenerationWorkflow(
                circuit_breaker=self._circuit_breaker,
                timeout_seconds=self.config.get('workflow_timeout', 300.0)
            )

            self._initialized_at = datetime.utcnow()

            logger.info(
                f"Review generation components initialized successfully. "
                f"Workflow timeout: {self.config.get('workflow_timeout', 300)}s, "
                f"Circuit breaker threshold: {self.config.get('failure_threshold', 5)}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize review generation components: {e}")
            self._workflow = None
            self._circuit_breaker = None

    async def generate_review(
        self,
        context_pack: Dict[str, Any],
        pr_patches: List[Dict[str, Any]],
        limits: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate AI-powered code review from assembled context.

        This is the main entry point for review generation. It:
        1. Validates inputs
        2. Executes the 6-node workflow
        3. Handles errors with fallback strategies
        4. Collects metrics for monitoring

        Args:
            context_pack: Rich context from Phase 5 (Context Assembly)
                Required keys: context_items, patches, seed_set
            pr_patches: PR file patches with PRHunk data
            limits: Optional configuration limits:
                - max_findings: Maximum findings to return (default: 20)
                - min_confidence: Minimum confidence threshold (default: 0.5)
                - max_tokens: Maximum LLM tokens (default: 4000)

        Returns:
            Dict containing:
                - success: Whether generation succeeded
                - findings: List of validated, anchored findings
                - summary: Review summary text
                - stats: Generation statistics
                - workflow_metadata: Execution metadata

        Raises:
            ReviewGenerationError: If generation fails and fallback is unavailable
        """
        self._total_reviews += 1
        generation_start = datetime.utcnow()

        # Apply default limits
        effective_limits = {
            "max_findings": self.config.get('max_findings', 20),
            "min_confidence": self.config.get('min_confidence', 0.5),
            "max_tokens": self.config.get('max_tokens', 4000),
            **(limits or {})
        }

        # Check if workflow is available
        if not self._workflow:
            logger.warning("Workflow not available, attempting reinitialization")
            self._initialize_components()

            if not self._workflow:
                logger.error("Workflow reinitialization failed, using fallback")
                self._fallback_reviews += 1
                return await self._fallback_review_generation(
                    context_pack, pr_patches, effective_limits
                )

        try:
            # Execute the 6-node review generation workflow
            result = await self._workflow.execute(
                context_pack=context_pack,
                patches=pr_patches,
                limits=effective_limits
            )

            if result.get("success"):
                self._successful_reviews += 1

                generation_duration = (datetime.utcnow() - generation_start).total_seconds()

                logger.info(
                    f"Review generation completed successfully in {generation_duration:.2f}s. "
                    f"Findings: {result.get('final_review_output', {}).get('total_findings', 0)}"
                )

                return self._format_successful_result(result, generation_duration)

            else:
                # Workflow returned failure
                logger.warning(
                    f"Workflow returned failure: {result.get('error_message', 'Unknown error')}"
                )
                return await self._handle_workflow_failure(
                    result, context_pack, pr_patches, effective_limits
                )

        except ReviewGenerationError as e:
            logger.error(f"Review generation error: {e}")
            self._failed_reviews += 1

            if e.recoverable:
                return await self._fallback_review_generation(
                    context_pack, pr_patches, effective_limits
                )
            raise

        except Exception as e:
            logger.error(f"Unexpected error in review generation: {e}")
            self._failed_reviews += 1

            return await self._fallback_review_generation(
                context_pack, pr_patches, effective_limits
            )

    def _format_successful_result(
        self,
        workflow_result: Dict[str, Any],
        generation_duration: float
    ) -> Dict[str, Any]:
        """Format successful workflow result for API response."""
        final_output = workflow_result.get("final_review_output", {})

        return {
            "success": True,
            "findings": final_output.get("findings", []),
            "summary": final_output.get("summary", ""),
            "total_findings": final_output.get("total_findings", 0),
            "stats": {
                "blocker_count": final_output.get("blocker_count", 0),
                "high_count": final_output.get("high_count", 0),
                "medium_count": final_output.get("medium_count", 0),
                "low_count": final_output.get("low_count", 0),
                "nit_count": final_output.get("nit_count", 0),
                "avg_confidence": final_output.get("avg_confidence", 0.0),
                "generation_duration_seconds": generation_duration,
                "model_used": final_output.get("model_used", "unknown"),
            },
            "workflow_metadata": workflow_result.get("workflow_metadata", {}),
            "quality_metrics": workflow_result.get("quality_metrics", {}),
            "fallback_used": False
        }

    async def _handle_workflow_failure(
        self,
        workflow_result: Dict[str, Any],
        context_pack: Dict[str, Any],
        pr_patches: List[Dict[str, Any]],
        limits: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle workflow failure with appropriate fallback strategy."""
        error_type = workflow_result.get("error", "Unknown")
        error_message = workflow_result.get("error_message", "")

        # Check if this is a timeout - might succeed with retry
        if error_type == "WorkflowTimeout":
            logger.warning("Workflow timed out, using fallback")
            self._failed_reviews += 1
            return await self._fallback_review_generation(context_pack, pr_patches, limits)

        # For other errors, use fallback
        self._failed_reviews += 1
        return await self._fallback_review_generation(context_pack, pr_patches, limits)

    async def _fallback_review_generation(
        self,
        context_pack: Dict[str, Any],
        pr_patches: List[Dict[str, Any]],
        limits: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Fallback review generation when primary workflow fails.

        Provides minimal but useful review output based on:
        - Static analysis of context items
        - Pattern matching for common issues
        - Basic diff analysis

        This ensures users always get some feedback even when LLM fails.
        """
        logger.info("Using fallback review generation")
        self._fallback_reviews += 1

        context_items = context_pack.get("context_items", [])
        seed_set = context_pack.get("seed_set", {})

        # Generate basic findings from static analysis
        fallback_findings = []

        # Analyze changed files for common patterns
        changed_files = set()
        for patch in pr_patches:
            file_path = patch.get("file_path", "")
            if file_path:
                changed_files.add(file_path)

        # Check seed symbols for obvious issues
        seed_symbols = seed_set.get("seed_symbols", [])
        for i, symbol in enumerate(seed_symbols[:5]):  # Limit to first 5 seeds
            symbol_name = symbol.get("name", "unknown")
            file_path = symbol.get("file_path", "")

            # Create a basic finding for review
            if file_path and file_path in changed_files:
                fallback_findings.append({
                    "finding_id": f"finding_{i + 1}",
                    "severity": "medium",
                    "category": "maintainability",
                    "title": f"Review changes to {symbol_name}",
                    "message": f"The symbol '{symbol_name}' in '{file_path}' has been modified. Please verify the changes maintain backward compatibility and follow project conventions.",
                    "suggested_fix": "Manually review the changes and ensure tests cover the modified functionality.",
                    "file_path": file_path,
                    "hunk_id": None,
                    "line_in_hunk": None,
                    "confidence": 0.5,
                    "related_symbols": [symbol_name],
                    "code_examples": []
                })

        # Apply limits
        max_findings = limits.get("max_findings", 20)
        fallback_findings = fallback_findings[:max_findings]

        # Generate fallback summary
        summary = self._generate_fallback_summary(
            context_items, pr_patches, fallback_findings
        )

        return {
            "success": True,
            "findings": fallback_findings,
            "summary": summary,
            "total_findings": len(fallback_findings),
            "stats": {
                "blocker_count": 0,
                "high_count": 0,
                "medium_count": len(fallback_findings),
                "low_count": 0,
                "nit_count": 0,
                "avg_confidence": 0.5,
                "generation_duration_seconds": 0.0,
                "model_used": "fallback_static_analysis",
            },
            "workflow_metadata": {
                "fallback_reason": "Primary workflow unavailable or failed"
            },
            "quality_metrics": {
                "anchoring_success_rate": 0.0,
                "average_confidence_score": 0.5
            },
            "fallback_used": True
        }

    def _generate_fallback_summary(
        self,
        context_items: List[Dict[str, Any]],
        pr_patches: List[Dict[str, Any]],
        findings: List[Dict[str, Any]]
    ) -> str:
        """Generate a fallback summary when LLM is unavailable."""
        file_count = len(pr_patches)
        context_count = len(context_items)
        finding_count = len(findings)

        total_additions = sum(p.get("additions", 0) for p in pr_patches)
        total_deletions = sum(p.get("deletions", 0) for p in pr_patches)

        summary_parts = [
            f"This PR modifies {file_count} file(s) with {total_additions} additions and {total_deletions} deletions.",
            f"Analysis was performed using static analysis (AI review unavailable).",
        ]

        if finding_count > 0:
            summary_parts.append(
                f"{finding_count} area(s) flagged for manual review based on the modified symbols."
            )

        if context_count > 0:
            summary_parts.append(
                f"The changes affect {context_count} related code symbol(s) in the codebase."
            )

        summary_parts.append(
            "Note: This is a fallback review. For full AI-powered analysis, please retry when the service is available."
        )

        return " ".join(summary_parts)

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get current service metrics for monitoring.

        Returns comprehensive metrics including:
        - Review success/failure rates
        - Fallback usage statistics
        - Workflow health status
        - Circuit breaker state
        """
        success_rate = (
            self._successful_reviews / self._total_reviews
            if self._total_reviews > 0 else 1.0
        )

        fallback_rate = (
            self._fallback_reviews / self._total_reviews
            if self._total_reviews > 0 else 0.0
        )

        metrics = {
            "service_metrics": {
                "total_reviews": self._total_reviews,
                "successful_reviews": self._successful_reviews,
                "failed_reviews": self._failed_reviews,
                "fallback_reviews": self._fallback_reviews,
                "success_rate": success_rate,
                "fallback_rate": fallback_rate,
            },
            "config": {
                "workflow_timeout": self.config.get('workflow_timeout', 300),
                "max_findings": self.config.get('max_findings', 20),
                "min_confidence": self.config.get('min_confidence', 0.5),
            },
            "initialized_at": self._initialized_at.isoformat() if self._initialized_at else None,
            "workflow_available": self._workflow is not None
        }

        # Add workflow metrics if available
        if self._workflow:
            metrics["workflow_metrics"] = self._workflow.get_metrics()

        # Add circuit breaker metrics if available
        if self._circuit_breaker:
            metrics["circuit_breaker"] = self._circuit_breaker.get_metrics()

        return metrics

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform comprehensive health check on the review generation system.

        Checks:
        - Workflow availability and health
        - Circuit breaker state
        - Node health status
        - Recent success rates

        Returns:
            Health status dict with status ("healthy", "degraded", "unhealthy")
            and component-level health details
        """
        health = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {},
            "checks": []
        }

        # Check workflow availability
        if self._workflow:
            workflow_health = self._workflow.get_health_status()
            health["components"]["workflow"] = {
                "status": "healthy" if workflow_health.get("workflow_healthy") else "degraded",
                "success_rate": workflow_health.get("success_rate", 0.0),
                "total_executions": workflow_health.get("total_executions", 0)
            }

            if not workflow_health.get("workflow_healthy"):
                health["status"] = "degraded"
                health["checks"].append("Workflow health below threshold")

            # Add node health
            health["components"]["nodes"] = workflow_health.get("node_health", {})

        else:
            health["components"]["workflow"] = {"status": "unavailable"}
            health["status"] = "degraded"
            health["checks"].append("Workflow not initialized")

        # Check circuit breaker
        if self._circuit_breaker:
            cb_health = self._circuit_breaker.health_check()
            health["components"]["circuit_breaker"] = cb_health

            if cb_health.get("status") != "healthy":
                health["status"] = "degraded"
                health["checks"].append("Circuit breaker not healthy")
        else:
            health["components"]["circuit_breaker"] = {"status": "not_configured"}

        # Check recent success rate
        if self._total_reviews > 10:  # Only check if we have enough data
            success_rate = self._successful_reviews / self._total_reviews
            if success_rate < 0.90:
                health["status"] = "degraded"
                health["checks"].append(f"Success rate below 90%: {success_rate:.1%}")
            if success_rate < 0.50:
                health["status"] = "unhealthy"

        # Add fallback availability
        health["components"]["fallback"] = {
            "status": "available",
            "fallback_count": self._fallback_reviews
        }

        return health

    async def reset_metrics(self) -> None:
        """Reset service metrics (for testing or maintenance)."""
        self._total_reviews = 0
        self._successful_reviews = 0
        self._failed_reviews = 0
        self._fallback_reviews = 0
        logger.info("Review generation metrics reset")

    async def reinitialize(self) -> bool:
        """
        Reinitialize workflow components.

        Useful for recovery after configuration changes or failures.

        Returns:
            True if reinitialization succeeded, False otherwise
        """
        logger.info("Reinitializing review generation components")
        self._initialize_components()
        return self._workflow is not None