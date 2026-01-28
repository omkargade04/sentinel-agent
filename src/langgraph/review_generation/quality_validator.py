"""
Quality Validator Node Implementation

Node 6 in the Review Generation workflow.
Validates output quality, applies filters, and produces final publishable output.
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict

from src.langgraph.review_generation.base_node import BaseReviewGenerationNode
from src.langgraph.review_generation.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


# Configuration constants
MIN_CONFIDENCE_THRESHOLD = 0.5
MAX_FINDINGS_LIMIT = 20
DUPLICATE_SIMILARITY_THRESHOLD = 0.8


class QualityValidatorNode(BaseReviewGenerationNode):
    """
    Node 6: Validate output quality, anchoring validity, and publishability.
    
    This node:
    - Filters findings by confidence threshold (>= 0.5)
    - Deduplicates similar findings (same file + similar title)
    - Enforces max 20 findings limit (TRD requirement)
    - Prioritizes by severity (blocker > high > medium > low > nit)
    - Assigns system-computed fields (finding_id, totals, timestamps)
    - Builds comprehensive summary including unanchored findings
    - Produces final LLMReviewOutput ready for publishing
    """

    SEVERITY_PRIORITY = {
        "blocker": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
        "nit": 4,
    }

    def __init__(
        self,
        circuit_breaker: Optional[CircuitBreaker] = None,
        min_confidence: float = MIN_CONFIDENCE_THRESHOLD,
        max_findings: int = MAX_FINDINGS_LIMIT,
    ):
        super().__init__(
            name="quality_validator",
            timeout_seconds=25.0,
            circuit_breaker=circuit_breaker,
            max_retries=2
        )
        self.min_confidence = min_confidence
        self.max_findings = max_findings

    async def _execute_node_logic(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and finalize review output.
        
        Args:
            state: Workflow state containing anchored/unanchored findings
            
        Returns:
            Dict with final_review_output ready for publishing
        """
        self.logger.info("Validating and finalizing review output")
        
        anchored_findings = state.get("anchored_findings", [])
        unanchored_findings = state.get("unanchored_findings", [])
        raw_llm_output = state.get("raw_llm_output", {})
        llm_token_usage = state.get("llm_token_usage", {})
        anchoring_stats = state.get("anchoring_stats", {})
        
        # Step 1: Filter by confidence
        filtered_anchored = self._filter_by_confidence(anchored_findings)
        filtered_unanchored = self._filter_by_confidence(unanchored_findings)
        
        confidence_filtered_count = (
            len(anchored_findings) - len(filtered_anchored) +
            len(unanchored_findings) - len(filtered_unanchored)
        )
        
        # Step 2: Deduplicate
        deduped_anchored = self._deduplicate_findings(filtered_anchored)
        deduped_unanchored = self._deduplicate_findings(filtered_unanchored)
        
        duplicate_count = (
            len(filtered_anchored) - len(deduped_anchored) +
            len(filtered_unanchored) - len(deduped_unanchored)
        )
        
        # Step 3: Sort by severity priority
        sorted_anchored = self._sort_by_severity(deduped_anchored)
        sorted_unanchored = self._sort_by_severity(deduped_unanchored)
        
        # Step 4: Apply max findings limit (prioritize anchored over unanchored)
        limited_findings = self._apply_limit(sorted_anchored, sorted_unanchored)
        truncated_count = (
            len(sorted_anchored) + len(sorted_unanchored) - len(limited_findings)
        )
        
        # Step 5: Assign finding IDs (system-computed)
        final_findings = self._assign_finding_ids(limited_findings)
        
        # Step 6: Compute severity counts
        severity_counts = self._count_by_severity(final_findings)
        
        # Step 7: Build comprehensive summary
        original_summary = raw_llm_output.get("summary", "No summary provided.")
        final_summary = self._build_comprehensive_summary(
            original_summary, sorted_unanchored, final_findings
        )
        
        # Step 8: Compute statistics
        validation_stats = {
            "total_candidates": len(anchored_findings) + len(unanchored_findings),
            "confidence_filtered": confidence_filtered_count,
            "duplicates_removed": duplicate_count,
            "truncated_count": truncated_count,
            "final_count": len(final_findings),
            "anchored_in_final": sum(1 for f in final_findings if f.get("hunk_id")),
            "unanchored_in_summary": len(sorted_unanchored),
        }
        
        # Step 9: Build final output
        final_review_output = {
            "findings": final_findings,
            "summary": final_summary,
            "total_findings": len(final_findings),
            "high_confidence_findings": sum(
                1 for f in final_findings if f.get("confidence", 0) >= 0.7
            ),
            # Severity breakdown
            "blocker_count": severity_counts.get("blocker", 0),
            "high_count": severity_counts.get("high", 0),
            "medium_count": severity_counts.get("medium", 0),
            "low_count": severity_counts.get("low", 0),
            "nit_count": severity_counts.get("nit", 0),
            # Metadata
            "review_timestamp": datetime.utcnow().isoformat() + "Z",
            "review_version": "v1",
            "model_used": llm_token_usage.get("model", "unknown"),
            # Optional fields from LLM
            "patterns": raw_llm_output.get("patterns"),
            "recommendations": raw_llm_output.get("recommendations"),
            # Statistics
            "stats": {
                "total_findings_generated": len(anchored_findings) + len(unanchored_findings),
                "high_confidence_findings": sum(
                    1 for f in final_findings if f.get("confidence", 0) >= 0.7
                ),
                "anchored_findings": sum(1 for f in final_findings if f.get("hunk_id")),
                "unanchored_findings": len(sorted_unanchored),
                "findings_by_severity": severity_counts,
                "findings_by_category": self._count_by_category(final_findings),
                "model_used": llm_token_usage.get("model"),
                "token_usage": {
                    "prompt_tokens": llm_token_usage.get("input_tokens", 0),
                    "completion_tokens": llm_token_usage.get("output_tokens", 0),
                    "total_tokens": llm_token_usage.get("total_tokens", 0),
                },
            },
            "validation_stats": validation_stats,
        }
        
        self.logger.info(
            f"Quality validation complete: {len(final_findings)} findings "
            f"(filtered {confidence_filtered_count}, deduped {duplicate_count}, "
            f"truncated {truncated_count})"
        )
        
        return {"final_review_output": final_review_output}

    def _get_required_state_keys(self) -> List[str]:
        return ["anchored_findings", "unanchored_findings", "raw_llm_output"]

    def _get_state_type_requirements(self) -> Dict[str, type]:
        return {
            "anchored_findings": list,
            "unanchored_findings": list,
            "raw_llm_output": dict,
        }

    # ========================================================================
    # FILTERING
    # ========================================================================

    def _filter_by_confidence(
        self,
        findings: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Filter out findings below confidence threshold."""
        return [
            f for f in findings
            if f.get("confidence", 0) >= self.min_confidence
        ]

    def _deduplicate_findings(
        self,
        findings: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Remove duplicate findings based on file + title similarity.
        
        Keeps the finding with higher confidence when duplicates found.
        """
        seen: Dict[str, Dict[str, Any]] = {}
        
        for finding in findings:
            # Create a key based on file + normalized title
            file_path = finding.get("file_path", "")
            title = finding.get("title", "").lower().strip()
            
            # Simple dedup key - could be enhanced with fuzzy matching
            key = f"{file_path}::{title[:50]}"
            
            if key not in seen:
                seen[key] = finding
            else:
                # Keep the one with higher confidence
                if finding.get("confidence", 0) > seen[key].get("confidence", 0):
                    seen[key] = finding
        
        return list(seen.values())

    def _sort_by_severity(
        self,
        findings: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Sort findings by severity priority (blocker first)."""
        return sorted(
            findings,
            key=lambda f: (
                self.SEVERITY_PRIORITY.get(f.get("severity", "medium"), 2),
                -f.get("confidence", 0)  # Higher confidence first within same severity
            )
        )

    def _apply_limit(
        self,
        anchored: List[Dict[str, Any]],
        unanchored: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Apply max findings limit, prioritizing anchored findings.
        
        Strategy:
        1. Take as many anchored findings as possible (up to limit)
        2. Fill remaining slots with unanchored findings if any room
        """
        result = []
        
        # Prioritize anchored findings
        for finding in anchored:
            if len(result) >= self.max_findings:
                break
            result.append(finding)
        
        # Add unanchored findings if room
        remaining_slots = self.max_findings - len(result)
        if remaining_slots > 0:
            for finding in unanchored[:remaining_slots]:
                result.append(finding)
        
        return result

    # ========================================================================
    # FINDING FINALIZATION
    # ========================================================================

    def _assign_finding_ids(
        self,
        findings: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Assign sequential finding IDs (finding_1, finding_2, etc.)."""
        result = []
        
        for i, finding in enumerate(findings, start=1):
            finalized = {
                "finding_id": f"finding_{i}",
                "severity": finding.get("severity", "medium"),
                "category": finding.get("category", "style"),
                "title": finding.get("title", ""),
                "message": finding.get("message", ""),
                "suggested_fix": finding.get("suggested_fix", ""),
                "file_path": finding.get("file_path", ""),
                "confidence": finding.get("confidence", 0.5),
                "related_symbols": finding.get("related_symbols", [])[:10],
                "code_examples": finding.get("code_examples", [])[:3],
            }
            
            # Only include anchoring fields if anchored
            if finding.get("hunk_id"):
                finalized["hunk_id"] = finding["hunk_id"]
                finalized["line_in_hunk"] = finding.get("line_in_hunk", 0)
            
            result.append(finalized)
        
        return result

    # ========================================================================
    # SUMMARY BUILDING
    # ========================================================================

    def _build_comprehensive_summary(
        self,
        original_summary: str,
        unanchored_findings: List[Dict[str, Any]],
        final_findings: List[Dict[str, Any]]
    ) -> str:
        """
        Build comprehensive summary including unanchored findings.
        
        Unanchored findings that didn't make it into the final list
        are summarized here so they're not lost.
        """
        parts = [original_summary.strip()]
        
        # Count unanchored findings not in final output
        final_file_titles: Set[str] = {
            f"{f.get('file_path')}::{f.get('title', '')[:30]}"
            for f in final_findings
        }
        
        unanchored_not_in_final = [
            f for f in unanchored_findings
            if f"{f.get('file_path')}::{f.get('title', '')[:30]}" not in final_file_titles
        ]
        
        if unanchored_not_in_final:
            parts.append("\n\n---\n\n**Additional Issues (not anchored to specific lines):**\n")
            
            for finding in unanchored_not_in_final[:5]:  # Limit to 5 in summary
                severity = finding.get("severity", "medium").upper()
                title = finding.get("title", "Unknown issue")
                file_path = finding.get("file_path", "")
                message = finding.get("message", "")[:200]
                
                parts.append(f"\n- **[{severity}]** `{file_path}`: {title}")
                if message:
                    parts.append(f"\n  {message}")
            
            remaining = len(unanchored_not_in_final) - 5
            if remaining > 0:
                parts.append(f"\n\n*...and {remaining} more issues not shown.*")
        
        return "".join(parts)

    # ========================================================================
    # STATISTICS
    # ========================================================================

    def _count_by_severity(
        self,
        findings: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """Count findings by severity level."""
        counts: Dict[str, int] = defaultdict(int)
        for finding in findings:
            severity = finding.get("severity", "medium")
            counts[severity] += 1
        return dict(counts)

    def _count_by_category(
        self,
        findings: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """Count findings by category."""
        counts: Dict[str, int] = defaultdict(int)
        for finding in findings:
            category = finding.get("category", "style")
            counts[category] += 1
        return dict(counts)

    # ========================================================================
    # GRACEFUL DEGRADATION
    # ========================================================================

    async def _attempt_graceful_degradation(
        self,
        state: Dict[str, Any],
        error: Exception,
        metrics: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Provide fallback when validation fails.
        
        Returns minimal valid output with error information.
        """
        self.logger.warning(f"Using graceful degradation for quality validation: {error}")
        
        try:
            raw_llm_output = state.get("raw_llm_output", {})
            
            return {
                "final_review_output": {
                    "findings": [],
                    "summary": f"Review validation failed: {str(error)[:100]}. Original summary: {raw_llm_output.get('summary', 'N/A')[:200]}",
                    "total_findings": 0,
                    "high_confidence_findings": 0,
                    "blocker_count": 0,
                    "high_count": 0,
                    "medium_count": 0,
                    "low_count": 0,
                    "nit_count": 0,
                    "review_timestamp": datetime.utcnow().isoformat() + "Z",
                    "review_version": "v1",
                    "model_used": "degraded",
                    "validation_error": str(error),
                }
            }
        except Exception as fallback_error:
            self.logger.error(f"Graceful degradation also failed: {fallback_error}")
            return None
