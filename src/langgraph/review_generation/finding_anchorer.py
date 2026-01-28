"""
Finding Anchorer Node Implementation

Node 5 in the Review Generation workflow.
Maps LLM findings to specific diff locations using simple text matching.

SIMPLIFIED APPROACH:
- Single source of truth: LLM's message + suggested_fix
- Extract code patterns (backticks, identifiers)
- Search in hunk lines
- One fallback: first added line
"""

import logging
import re
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

from src.langgraph.review_generation.base_node import BaseReviewGenerationNode
from src.langgraph.review_generation.circuit_breaker import CircuitBreaker
from src.langgraph.review_generation.schema import (
    DiffMappings,
    HunkMapping,
)

logger = logging.getLogger(__name__)


class FindingAnchorerNode(BaseReviewGenerationNode):
    """
    Node 5: Map findings to specific diff locations.

    Simple approach:
    1. Extract code patterns from LLM message
    2. Search for patterns in hunk lines
    3. Fallback to first added line
    """

    def __init__(self, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(
            name="finding_anchorer",
            timeout_seconds=20.0,
            circuit_breaker=circuit_breaker,
            max_retries=2
        )

    async def _execute_node_logic(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Anchor findings to diff locations."""
        self.logger.info("Anchoring findings to diff locations")
        raw_llm_output = state.get("raw_llm_output", {})
        diff_mappings_data = state.get("diff_mappings", {})
        diff_mappings = self._parse_diff_mappings(diff_mappings_data)
        findings = raw_llm_output.get("findings", [])
        if not findings:
            self.logger.info("No findings to anchor")
            return self._create_empty_result()
        anchored_findings: List[Dict[str, Any]] = []
        unanchored_findings: List[Dict[str, Any]] = []
        anchoring_methods: Dict[str, int] = defaultdict(int)

        # Track used positions to distribute findings
        used_positions: Dict[Tuple[str, str, int], int] = defaultdict(int)

        for finding in findings:
            try:
                anchored_finding, method = self._anchor_finding(finding, diff_mappings)

                if anchored_finding:
                    # Distribute findings across different lines if possible
                    position_key = (
                        anchored_finding.get("file_path", ""),
                        anchored_finding.get("hunk_id", ""),
                        anchored_finding.get("line_in_hunk", 0)
                    )

                    if used_positions[position_key] > 0:
                        adjusted = self._find_alternative_line(
                            anchored_finding, diff_mappings, used_positions
                        )
                        if adjusted:
                            anchored_finding = adjusted
                            position_key = (
                                anchored_finding["file_path"],
                                anchored_finding["hunk_id"],
                                anchored_finding["line_in_hunk"]
                            )

                    used_positions[position_key] += 1
                    anchored_findings.append(anchored_finding)
                    anchoring_methods[method] += 1
                else:
                    unanchored_findings.append(finding)
                    anchoring_methods["none"] += 1

            except Exception as e:
                self.logger.warning(f"Error anchoring '{finding.get('title', 'unknown')}': {e}")
                unanchored_findings.append(finding)
                anchoring_methods["error"] += 1

        total = len(findings)
        anchored_count = len(anchored_findings)
        self.logger.info(
            f"Anchoring complete: {anchored_count}/{total} anchored, "
            f"methods: {dict(anchoring_methods)}"
        )

        return {
            "anchored_findings": anchored_findings,
            "unanchored_findings": unanchored_findings,
            "anchoring_stats": {
                "total_findings": total,
                "anchored_count": anchored_count,
                "unanchored_count": len(unanchored_findings),
                "anchoring_success_rate": anchored_count / max(total, 1),
                "anchoring_methods": dict(anchoring_methods),
            },
        }

    def _get_required_state_keys(self) -> List[str]:
        return ["raw_llm_output", "diff_mappings"]

    def _get_state_type_requirements(self) -> Dict[str, type]:
        return {"raw_llm_output": dict, "diff_mappings": dict}

    def _anchor_finding(
        self,
        finding: Dict[str, Any],
        diff_mappings: DiffMappings
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Anchor a finding using simple text matching.

        Strategy:
        1. Extract code patterns from message/suggested_fix
        2. Search for patterns in hunk lines
        3. Fallback: first added line
        """
        file_path = finding.get("file_path", "")
        hunk_id = finding.get("hunk_id")

        # Validate file and hunk exist
        if file_path not in diff_mappings.all_file_paths:
            return None, "none"

        hunk = None
        if hunk_id:
            hunk = diff_mappings.get_hunk(file_path, hunk_id)

        if not hunk:
            # Try to get first hunk for this file
            file_mapping = diff_mappings.get_file_mapping(file_path)
            if file_mapping and file_mapping.hunks:
                hunk = file_mapping.hunks[0]
                hunk_id = hunk.hunk_id

        if not hunk:
            return None, "none"

        # Search for code patterns from LLM message
        line_idx = self._find_line_by_content_match(finding, hunk)
        if line_idx is not None:
            return self._create_anchored_finding(
                finding, hunk_id, line_idx, "content_match"
            ), "content_match"

        # Fallback: First added line
        if hunk.added_line_indexes:
            line_idx = hunk.added_line_indexes[0]
        else:
            line_idx = 0

        return self._create_anchored_finding(
            finding, hunk_id, line_idx, "fallback"
        ), "fallback"

    def _find_line_by_content_match(
        self,
        finding: Dict[str, Any],
        hunk: HunkMapping
    ) -> Optional[int]:
        """
        Find the best matching line in hunk based on finding content.

        Extracts patterns from:
        1. Code in backticks from message/suggested_fix
        2. Key identifiers from the text

        Returns line index or None.
        """
        # Combine all text sources
        message = finding.get("message", "")
        suggested_fix = finding.get("suggested_fix", "")
        title = finding.get("title", "")

        # Step 1: Extract code from backticks (highest priority)
        backtick_patterns = self._extract_backtick_code(message + " " + suggested_fix)

        if backtick_patterns:
            # Search for backtick patterns in hunk lines
            for pattern in backtick_patterns:
                idx = self._search_pattern_in_hunk(pattern, hunk)
                if idx is not None:
                    self.logger.debug(f"Found backtick pattern '{pattern}' at line {idx}")
                    return idx

        # Step 2: Extract identifiers from text
        identifiers = self._extract_key_identifiers(message + " " + title + " " + suggested_fix)

        if identifiers:
            # Search for identifiers, prioritizing added lines
            for ident in identifiers[:10]:  # Top 10 identifiers
                idx = self._search_identifier_in_hunk(ident, hunk)
                if idx is not None:
                    self.logger.debug(f"Found identifier '{ident}' at line {idx}")
                    return idx

        return None

    def _extract_backtick_code(self, text: str) -> List[str]:
        """
        Extract code snippets from backticks in text.

        Handles both `inline` and ```block``` code.
        Returns list of code snippets, ordered by specificity (longer = better).
        """
        patterns = []

        # Match ```block``` code
        block_matches = re.findall(r'```(?:\w+)?\s*(.*?)```', text, re.DOTALL)
        for match in block_matches:
            # Get the first meaningful line from block
            lines = [l.strip() for l in match.split('\n') if l.strip()]
            patterns.extend(lines[:3])  # First 3 lines

        # Match `inline` code
        inline_matches = re.findall(r'`([^`]+)`', text)
        patterns.extend(inline_matches)

        # Filter and clean
        cleaned = []
        for p in patterns:
            p = p.strip()
            # Skip very short or very long patterns
            if 2 < len(p) < 100:
                cleaned.append(p)

        # Sort by length (longer = more specific = better)
        cleaned.sort(key=len, reverse=True)

        return cleaned

    def _extract_key_identifiers(self, text: str) -> List[str]:
        """
        Extract key identifiers from text.

        Prioritizes:
        1. CamelCase/snake_case identifiers
        2. Method/function names (with parentheses)
        3. Property names
        """
        # Common keywords to skip
        skip_words = {
            # Language keywords
            'const', 'let', 'var', 'function', 'class', 'return', 'if', 'else',
            'for', 'while', 'try', 'catch', 'finally', 'async', 'await', 'new',
            'this', 'true', 'false', 'null', 'undefined', 'import', 'export',
            'from', 'default', 'typeof', 'instanceof',
            # Common English words
            'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'must', 'shall', 'can',
            'and', 'or', 'but', 'not', 'with', 'without', 'for', 'to',
            'of', 'in', 'on', 'at', 'by', 'as', 'an', 'that', 'which',
            'this', 'these', 'those', 'it', 'its', 'they', 'them',
            'all', 'any', 'some', 'no', 'every', 'each', 'both',
            'more', 'most', 'other', 'such', 'only', 'same', 'so',
            'than', 'too', 'very', 'just', 'also', 'now', 'here',
            'there', 'when', 'where', 'why', 'how', 'what', 'who',
            # Review-specific words
            'error', 'issue', 'bug', 'fix', 'add', 'remove', 'change',
            'missing', 'incorrect', 'invalid', 'code', 'line', 'file',
            'use', 'using', 'used', 'check', 'ensure', 'make', 'set',
            'get', 'call', 'called', 'calling', 'method', 'property',
            'variable', 'parameter', 'argument', 'value', 'type', 'string',
            'number', 'object', 'array', 'boolean', 'function',
        }

        # Extract potential identifiers
        # Match: identifiers with at least one letter, optionally followed by () or .
        raw_identifiers = re.findall(r'\b([a-zA-Z_$][a-zA-Z0-9_$]*)\b', text)

        # Filter and dedupe
        seen = set()
        identifiers = []

        for ident in raw_identifiers:
            ident_lower = ident.lower()

            # Skip keywords and short identifiers
            if ident_lower in skip_words or len(ident) < 3:
                continue

            # Skip duplicates
            if ident_lower in seen:
                continue

            seen.add(ident_lower)
            identifiers.append(ident)

        # Prioritize: longer identifiers and those with special patterns
        def priority(ident):
            score = len(ident)
            # Bonus for camelCase
            if re.search(r'[a-z][A-Z]', ident):
                score += 5
            # Bonus for snake_case
            if '_' in ident:
                score += 3
            # Bonus for $ prefix (common in JS)
            if ident.startswith('$'):
                score += 3
            return score

        identifiers.sort(key=priority, reverse=True)

        return identifiers

    def _search_pattern_in_hunk(self, pattern: str, hunk: HunkMapping) -> Optional[int]:
        """
        Search for a pattern in hunk lines.

        Prioritizes added lines (+), then any line.
        Returns 0-based line index or None.
        """
        pattern_clean = pattern.strip()
        if not pattern_clean:
            return None

        # First pass: search added lines only
        for idx in hunk.added_line_indexes:
            line = hunk.lines[idx]
            line_clean = line.lstrip('+-').strip()

            if pattern_clean in line_clean:
                return idx

        # Second pass: search all lines
        for idx, line in enumerate(hunk.lines):
            line_clean = line.lstrip('+-').strip()

            if pattern_clean in line_clean:
                return idx

        return None

    def _search_identifier_in_hunk(self, identifier: str, hunk: HunkMapping) -> Optional[int]:
        """
        Search for an identifier in hunk lines.

        Uses word boundary matching to avoid partial matches.
        Prioritizes added lines.
        """
        if not identifier:
            return None

        # Create regex pattern with word boundaries
        # Handle special chars in identifier
        escaped = re.escape(identifier)
        pattern = re.compile(r'\b' + escaped + r'\b', re.IGNORECASE)

        # First pass: search added lines only
        for idx in hunk.added_line_indexes:
            line = hunk.lines[idx]
            if pattern.search(line):
                return idx

        # Second pass: search all lines
        for idx, line in enumerate(hunk.lines):
            if pattern.search(line):
                return idx

        return None

    def _find_alternative_line(
        self,
        finding: Dict[str, Any],
        diff_mappings: DiffMappings,
        used_positions: Dict[Tuple[str, str, int], int]
    ) -> Optional[Dict[str, Any]]:
        """Find an unused line in the same hunk to avoid stacking."""
        file_path = finding.get("file_path", "")
        hunk_id = finding.get("hunk_id", "")
        current_line = finding.get("line_in_hunk", 0)

        hunk = diff_mappings.get_hunk(file_path, hunk_id)
        if not hunk or not hunk.added_line_indexes:
            return None

        # Find first unused added line
        for alt_line in hunk.added_line_indexes:
            if alt_line == current_line:
                continue

            key = (file_path, hunk_id, alt_line)
            if used_positions[key] == 0:
                adjusted = finding.copy()
                adjusted["line_in_hunk"] = alt_line
                adjusted["anchoring_method"] = f"{finding.get('anchoring_method', 'unknown')}_adjusted"
                return adjusted

        return None

    def _create_anchored_finding(
        self,
        finding: Dict[str, Any],
        hunk_id: str,
        line_in_hunk: int,
        method: str
    ) -> Dict[str, Any]:
        """Create an anchored finding dict."""
        return {
            "title": finding.get("title", ""),
            "message": finding.get("message", ""),
            "severity": finding.get("severity", "medium"),
            "category": finding.get("category", "style"),
            "file_path": finding.get("file_path", ""),
            "suggested_fix": finding.get("suggested_fix", ""),
            "confidence": finding.get("confidence", 0.5),
            "related_symbols": finding.get("related_symbols", []),
            "code_examples": finding.get("code_examples", []),
            "hunk_id": hunk_id,
            "line_in_hunk": line_in_hunk,
            "is_anchored": True,
            "anchoring_method": method,
        }

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _parse_diff_mappings(self, data: Dict[str, Any]) -> DiffMappings:
        """Parse diff mappings dict into DiffMappings model."""
        try:
            return DiffMappings.model_validate(data)
        except Exception as e:
            self.logger.warning(f"Failed to parse DiffMappings: {e}")
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

    def _create_empty_result(self) -> Dict[str, Any]:
        """Create empty result."""
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

    async def _attempt_graceful_degradation(
        self,
        state: Dict[str, Any],
        error: Exception,
        metrics: Any
    ) -> Optional[Dict[str, Any]]:
        """Provide fallback when anchoring fails completely."""
        self.logger.warning(f"Using graceful degradation: {error}")

        try:
            findings = state.get("raw_llm_output", {}).get("findings", [])
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
        except Exception:
            return None
