"""
Finding Anchorer Node Implementation

Node 5 in the Review Generation workflow.
Maps LLM findings to specific diff locations deterministically.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

from src.services.pr_review.review_generation.base_node import BaseReviewGenerationNode
from src.services.pr_review.review_generation.circuit_breaker import CircuitBreaker
from src.services.pr_review.review_generation.schema import (
    AnchoredFinding,
    DiffMappings,
    HunkMapping,
)

logger = logging.getLogger(__name__)


class FindingAnchorerNode(BaseReviewGenerationNode):
    """
    Node 5: Map findings to specific diff locations deterministically.
    
    This node:
    - Takes raw LLM findings with hunk_id hints and line hints
    - Validates anchors against DiffMappings (source of truth)
    - Uses multiple anchoring strategies (evidence, hint, fallback)
    - Separates findings into anchored and unanchored lists
    - Calculates line_in_hunk as 0-based index into PRHunk.lines
    """

    def __init__(self, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(
            name="finding_anchorer",
            timeout_seconds=20.0,
            circuit_breaker=circuit_breaker,
            max_retries=2
        )

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the finding anchorer node."""
        return await self._execute_node_logic(state)

    async def _execute_node_logic(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Anchor findings to specific diff locations.
        
        Args:
            state: Workflow state containing raw_llm_output and diff_mappings
            
        Returns:
            Dict with anchored_findings, unanchored_findings, and anchoring_stats
        """
        self.logger.info("Anchoring findings to diff locations")
        
        raw_llm_output = state.get("raw_llm_output", {})
        diff_mappings_data = state.get("diff_mappings", {})
        context_pack = state.get("context_pack", {})
        
        # Parse diff mappings
        diff_mappings = self._parse_diff_mappings(diff_mappings_data)
        
        # Get findings from LLM output
        findings = raw_llm_output.get("findings", [])
        
        if not findings:
            self.logger.info("No findings to anchor")
            return self._create_empty_result()
        
        # Build context item lookup for evidence-based anchoring
        context_item_lookup = self._build_context_item_lookup(context_pack)
        
        # Process each finding
        anchored_findings: List[Dict[str, Any]] = []
        unanchored_findings: List[Dict[str, Any]] = []
        anchoring_methods: Dict[str, int] = defaultdict(int)
        
        for finding in findings:
            anchored_finding, method = self._anchor_finding(
                finding, diff_mappings, context_item_lookup
            )
            
            if anchored_finding and anchored_finding.get("is_anchored"):
                anchored_findings.append(anchored_finding)
                anchoring_methods[method] += 1
            else:
                # Keep original finding for unanchored list
                unanchored_findings.append(finding)
                anchoring_methods["none"] += 1
        
        # Build stats
        total = len(findings)
        anchored_count = len(anchored_findings)
        
        anchoring_stats = {
            "total_findings": total,
            "anchored_count": anchored_count,
            "unanchored_count": len(unanchored_findings),
            "anchoring_success_rate": anchored_count / max(total, 1),
            "anchoring_methods": dict(anchoring_methods),
        }
        
        self.logger.info(
            f"Anchoring complete: {anchored_count}/{total} findings anchored "
            f"({anchoring_stats['anchoring_success_rate']:.1%})"
        )
        
        return {
            "anchored_findings": anchored_findings,
            "unanchored_findings": unanchored_findings,
            "anchoring_stats": anchoring_stats,
        }

    def _get_required_state_keys(self) -> List[str]:
        return ["raw_llm_output", "diff_mappings"]

    def _get_state_type_requirements(self) -> Dict[str, type]:
        return {
            "raw_llm_output": dict,
            "diff_mappings": dict
        }

    # ========================================================================
    # ANCHORING LOGIC
    # ========================================================================

    def _anchor_finding(
        self,
        finding: Dict[str, Any],
        diff_mappings: DiffMappings,
        context_item_lookup: Dict[str, Dict[str, Any]]
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Attempt to anchor a single finding using multiple strategies.
        
        Strategies (in priority order):
        1. Evidence-based: Use context_item_id + snippet_line_range
        2. Hint-based: Validate LLM's hunk_id + line_hint
        3. File-based fallback: Anchor to first changed line in file
        
        Args:
            finding: Raw finding from LLM
            diff_mappings: Validated diff mappings
            context_item_lookup: Context items by ID for evidence lookup
            
        Returns:
            Tuple of (anchored_finding dict or None, anchoring method used)
        """
        file_path = finding.get("file_path", "")
        
        # Check if file is in the diff at all
        if file_path not in diff_mappings.all_file_paths:
            self.logger.debug(f"File not in diff: {file_path}")
            return None, "none"
        
        # Strategy 1: Evidence-based anchoring
        evidence = finding.get("evidence", {})
        if evidence:
            result = self._anchor_via_evidence(
                finding, evidence, diff_mappings, context_item_lookup
            )
            if result:
                return result, "evidence"
        
        # Strategy 2: Hint-based anchoring (validate LLM's suggestion)
        hunk_id_hint = finding.get("hunk_id")
        line_hint = finding.get("line_hint")
        
        if hunk_id_hint:
            result = self._anchor_via_hint(
                finding, file_path, hunk_id_hint, line_hint, diff_mappings
            )
            if result:
                return result, "hint"
        
        # Strategy 3: File-based fallback (first changed line)
        result = self._anchor_via_fallback(finding, file_path, diff_mappings)
        if result:
            return result, "fallback"
        
        return None, "none"

    def _anchor_via_evidence(
        self,
        finding: Dict[str, Any],
        evidence: Dict[str, Any],
        diff_mappings: DiffMappings,
        context_item_lookup: Dict[str, Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Anchor using evidence citation (context_item_id + snippet_line_range).
        
        This is the most accurate method as it references the actual code snippet
        the LLM used as evidence for the finding.
        """
        context_item_id = evidence.get("context_item_id")
        snippet_line_range = evidence.get("snippet_line_range", [])
        
        if not context_item_id:
            return None
        
        # Look up the context item
        context_item = context_item_lookup.get(context_item_id)
        if not context_item:
            self.logger.debug(f"Context item not found: {context_item_id}")
            return None
        
        # Get file path and line info from context item
        ctx_file_path = context_item.get("file_path", "")
        ctx_start_line = context_item.get("start_line", 0)
        
        # Calculate target line
        if snippet_line_range and len(snippet_line_range) >= 1:
            # snippet_line_range is relative to the snippet, convert to file line
            target_line = ctx_start_line + snippet_line_range[0]
        else:
            target_line = ctx_start_line
        
        # Use line_to_hunk_lookup to find the exact position
        file_path = finding.get("file_path", ctx_file_path)
        hunk_info = diff_mappings.get_hunk_for_line(file_path, target_line)
        
        if hunk_info:
            hunk_id, line_in_hunk = hunk_info
            return self._create_anchored_finding(
                finding, hunk_id, line_in_hunk,
                method="evidence", confidence=0.9
            )
        
        return None

    def _anchor_via_hint(
        self,
        finding: Dict[str, Any],
        file_path: str,
        hunk_id_hint: str,
        line_hint: Optional[int],
        diff_mappings: DiffMappings
    ) -> Optional[Dict[str, Any]]:
        """
        Anchor using LLM's hunk_id and line hints (validated against diff_mappings).
        """
        # Validate hunk_id exists for this file
        if not diff_mappings.is_valid_anchor(file_path, hunk_id_hint):
            self.logger.debug(f"Invalid hunk_id hint: {hunk_id_hint} for {file_path}")
            return None
        
        # Get the hunk to validate line_in_hunk
        hunk = diff_mappings.get_hunk(file_path, hunk_id_hint)
        if not hunk:
            return None
        
        # Determine line_in_hunk
        if line_hint is not None:
            # LLM provided a line hint - check if it's within hunk bounds
            if 0 <= line_hint < hunk.line_count:
                line_in_hunk = line_hint
            else:
                # Line hint out of bounds - try to map from file line number
                hunk_info = diff_mappings.get_hunk_for_line(file_path, line_hint)
                if hunk_info and hunk_info[0] == hunk_id_hint:
                    line_in_hunk = hunk_info[1]
                else:
                    # Default to first added line in hunk
                    line_in_hunk = self._get_first_changed_line(hunk)
        else:
            # No line hint - use first added line
            line_in_hunk = self._get_first_changed_line(hunk)
        
        return self._create_anchored_finding(
            finding, hunk_id_hint, line_in_hunk,
            method="hint", confidence=0.7
        )

    def _anchor_via_fallback(
        self,
        finding: Dict[str, Any],
        file_path: str,
        diff_mappings: DiffMappings
    ) -> Optional[Dict[str, Any]]:
        """
        Fallback anchoring - use first hunk with changes in the file.
        """
        file_mapping = diff_mappings.get_file_mapping(file_path)
        if not file_mapping or not file_mapping.hunks:
            return None
        
        # Find first hunk with added lines
        for hunk in file_mapping.hunks:
            if hunk.added_line_indexes:
                line_in_hunk = hunk.added_line_indexes[0]
                return self._create_anchored_finding(
                    finding, hunk.hunk_id, line_in_hunk,
                    method="fallback", confidence=0.5
                )
        
        # No added lines - use first hunk, first line
        first_hunk = file_mapping.hunks[0]
        return self._create_anchored_finding(
            finding, first_hunk.hunk_id, 0,
            method="fallback", confidence=0.4
        )

    def _get_first_changed_line(self, hunk: HunkMapping) -> int:
        """Get the first changed (added) line index in a hunk, or 0."""
        if hunk.added_line_indexes:
            return hunk.added_line_indexes[0]
        return 0

    def _create_anchored_finding(
        self,
        finding: Dict[str, Any],
        hunk_id: str,
        line_in_hunk: int,
        method: str,
        confidence: float
    ) -> Dict[str, Any]:
        """Create an anchored finding dict."""
        return {
            # Copy core fields
            "title": finding.get("title", ""),
            "message": finding.get("message", ""),
            "severity": finding.get("severity", "medium"),
            "category": finding.get("category", "style"),
            "file_path": finding.get("file_path", ""),
            "suggested_fix": finding.get("suggested_fix", ""),
            "confidence": finding.get("confidence", 0.5),
            "related_symbols": finding.get("related_symbols", []),
            "code_examples": finding.get("code_examples", []),
            # Anchoring fields (validated)
            "hunk_id": hunk_id,
            "line_in_hunk": line_in_hunk,
            "is_anchored": True,
            "anchoring_method": method,
            "anchoring_confidence": confidence,
        }

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _parse_diff_mappings(self, data: Dict[str, Any]) -> DiffMappings:
        """Parse diff mappings dict into DiffMappings model."""
        try:
            return DiffMappings.model_validate(data)
        except Exception as e:
            self.logger.warning(f"Failed to parse DiffMappings: {e}, using raw dict")
            # Create minimal DiffMappings from raw data
            return DiffMappings(
                file_mappings={},
                all_file_paths=data.get("all_file_paths", []),
                all_hunk_ids=data.get("all_hunk_ids", []),
                allowed_anchors=data.get("allowed_anchors", []),
                line_to_hunk_lookup=data.get("line_to_hunk_lookup", {}),
                total_files=data.get("total_files", 0),
                total_hunks=data.get("total_hunks", 0),
                total_changed_lines=data.get("total_changed_lines", 0),
            )

    def _build_context_item_lookup(
        self,
        context_pack: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """Build a lookup dict of context items by item_id."""
        lookup = {}
        context_items = context_pack.get("context_items", [])
        
        for item in context_items:
            item_id = item.get("item_id")
            if item_id:
                lookup[item_id] = item
        
        return lookup

    def _create_empty_result(self) -> Dict[str, Any]:
        """Create empty result when there are no findings."""
        return {
            "anchored_findings": [],
            "unanchored_findings": [],
            "anchoring_stats": {
                "total_findings": 0,
                "anchored_count": 0,
                "unanchored_count": 0,
                "anchoring_success_rate": 0.0,
                "anchoring_methods": {},
            },
        }

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
        Provide fallback when anchoring fails completely.
        
        Returns all findings as unanchored so they can still be included in summary.
        """
        self.logger.warning(f"Using graceful degradation for anchoring: {error}")
        
        try:
            raw_llm_output = state.get("raw_llm_output", {})
            findings = raw_llm_output.get("findings", [])
            
            return {
                "anchored_findings": [],
                "unanchored_findings": findings,
                "anchoring_stats": {
                    "total_findings": len(findings),
                    "anchored_count": 0,
                    "unanchored_count": len(findings),
                    "anchoring_success_rate": 0.0,
                    "anchoring_methods": {"degraded": len(findings)},
                    "degradation_reason": str(error),
                },
            }
        except Exception as fallback_error:
            self.logger.error(f"Graceful degradation also failed: {fallback_error}")
            return None
