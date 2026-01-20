"""
Review Publisher for GitHub PR Reviews

Orchestrates the publishing of AI-generated code review findings to GitHub
as inline comments anchored to diff positions, with fallback to summary-only
reviews when anchoring fails.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.models.schemas.pr_review.pr_patch import PRFilePatch
from src.services.github.diff_position import DiffPositionCalculator, PositionResult
from src.services.github.pr_api_client import PRApiClient
from src.exceptions.pr_review_exceptions import GitHubAPIException
from src.utils.logging import get_logger

logger = get_logger(__name__)


# Severity label mapping for inline comments
SEVERITY_LABELS = {
    "critical": "[CRITICAL]",
    "high": "[HIGH]",
    "medium": "[MEDIUM]",
    "low": "[LOW]",
    "nit": "[NIT]",
}


@dataclass
class PublishStats:
    """Statistics collected during review publishing."""
    
    github_api_calls: int = 0
    rate_limit_delays: int = 0
    retry_attempts: int = 0
    publish_duration_ms: int = 0
    position_calculations: int = 0
    position_failures: int = 0
    position_adjustments: int = 0


@dataclass
class PublishResult:
    """Result of review publishing operation."""
    
    published: bool
    """Whether the review was successfully published."""
    
    github_review_id: Optional[int] = None
    """GitHub's review ID if published successfully."""
    
    review_run_id: Optional[str] = None
    """Internal review run identifier."""
    
    anchored_comments: int = 0
    """Number of findings published as inline comments."""
    
    unanchored_findings: int = 0
    """Number of findings included in summary (not anchored)."""
    
    total_findings: int = 0
    """Total number of findings processed."""
    
    fallback_used: bool = False
    """Whether fallback to summary-only was used due to anchoring failure."""
    
    error_message: Optional[str] = None
    """Error message if publishing failed."""
    
    publish_stats: PublishStats = field(default_factory=PublishStats)
    """Detailed publishing statistics."""


@dataclass
class AnchoredComment:
    """A finding that has been successfully anchored to a diff position."""
    
    path: str
    position: int
    body: str
    finding: Dict[str, Any]


class ReviewPublisher:
    """
    Publishes AI-generated code review findings to GitHub.
    
    This class handles:
    - Calculating diff positions for findings
    - Formatting findings as GitHub inline comments
    - Building review body with summary and unanchored findings
    - Calling GitHub API with retry and fallback logic
    
    Usage:
        publisher = ReviewPublisher(pr_api_client, diff_calculator)
        result = await publisher.publish_review(
            repo_name="owner/repo",
            pr_number=123,
            head_sha="abc123...",
            review_output=llm_review_output,
            patches=pr_patches,
            installation_id=12345
        )
    """
    
    def __init__(
        self,
        pr_api_client: PRApiClient,
        diff_calculator: Optional[DiffPositionCalculator] = None
    ):
        """
        Initialize the ReviewPublisher.
        
        Args:
            pr_api_client: Client for GitHub API operations.
            diff_calculator: Calculator for diff positions. If None, creates default.
        """
        self.pr_api_client = pr_api_client
        self.diff_calculator = diff_calculator or DiffPositionCalculator()
    
    async def publish_review(
        self,
        repo_name: str,
        pr_number: int,
        head_sha: str,
        review_output: Dict[str, Any],
        patches: List[PRFilePatch],
        installation_id: int,
        review_run_id: Optional[str] = None
    ) -> PublishResult:
        """
        Publish a code review to GitHub with inline comments.
        
        Args:
            repo_name: Repository name in "owner/repo" format.
            pr_number: Pull request number.
            head_sha: Commit SHA to attach review to.
            review_output: LLM review output dict with findings and summary.
            patches: List of PR file patches for position calculation.
            installation_id: GitHub App installation ID.
            review_run_id: Optional internal review run identifier.
        
        Returns:
            PublishResult with publishing outcome and statistics.
        """
        start_time = time.time()
        stats = PublishStats()
        
        findings = review_output.get("findings", [])
        summary = review_output.get("summary", "")
        
        logger.info(
            f"Publishing review for {repo_name}#{pr_number} with "
            f"{len(findings)} findings"
        )
        
        # Split findings into anchorable and unanchorable
        anchored_comments, unanchored_findings, split_stats = self._split_findings(
            findings, patches
        )
        stats.position_calculations = split_stats["calculations"]
        stats.position_failures = split_stats["failures"]
        stats.position_adjustments = split_stats["adjustments"]
        
        logger.info(
            f"Position calculation: {len(anchored_comments)} anchorable, "
            f"{len(unanchored_findings)} unanchorable, "
            f"{stats.position_adjustments} adjustments applied"
        )
        
        # Build review body (summary + unanchored findings)
        review_body = self._build_review_body(summary, unanchored_findings)
        
        # Build inline comments payload
        comments_payload = self._build_comments_payload(anchored_comments)
        
        # Build the review data for GitHub API
        review_data = {
            "commit_id": head_sha,
            "body": review_body,
            "event": "COMMENT",
            "comments": comments_payload
        }
        
        # Try to publish with inline comments
        try:
            stats.github_api_calls += 1
            response = await self.pr_api_client.create_review(
                repo_name=repo_name,
                pr_number=pr_number,
                review_data=review_data,
                installation_id=installation_id
            )
            
            duration_ms = int((time.time() - start_time) * 1000)
            stats.publish_duration_ms = duration_ms
            
            logger.info(
                f"Successfully published review {response.get('id')} for "
                f"{repo_name}#{pr_number} with {len(comments_payload)} inline comments"
            )
            
            return PublishResult(
                published=True,
                github_review_id=response.get("id"),
                review_run_id=review_run_id,
                anchored_comments=len(anchored_comments),
                unanchored_findings=len(unanchored_findings),
                total_findings=len(findings),
                fallback_used=False,
                publish_stats=stats
            )
        
        except GitHubAPIException as e:
            # Check if this is a 422 validation error (likely bad positions)
            if getattr(e, 'status_code', None) == 422:
                logger.warning(
                    f"GitHub returned 422 for review with inline comments, "
                    f"falling back to summary-only: {e}"
                )
                stats.retry_attempts += 1
                
                # Fallback: publish summary-only review
                return await self._publish_fallback_review(
                    repo_name=repo_name,
                    pr_number=pr_number,
                    head_sha=head_sha,
                    summary=summary,
                    findings=findings,
                    installation_id=installation_id,
                    review_run_id=review_run_id,
                    stats=stats,
                    start_time=start_time
                )
            
            # For other errors, don't retry
            duration_ms = int((time.time() - start_time) * 1000)
            stats.publish_duration_ms = duration_ms
            
            logger.error(f"Failed to publish review for {repo_name}#{pr_number}: {e}")
            
            return PublishResult(
                published=False,
                review_run_id=review_run_id,
                anchored_comments=0,
                unanchored_findings=len(findings),
                total_findings=len(findings),
                fallback_used=False,
                error_message=str(e),
                publish_stats=stats
            )
        
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            stats.publish_duration_ms = duration_ms
            
            logger.error(
                f"Unexpected error publishing review for {repo_name}#{pr_number}: {e}",
                exc_info=True
            )
            
            return PublishResult(
                published=False,
                review_run_id=review_run_id,
                anchored_comments=0,
                unanchored_findings=len(findings),
                total_findings=len(findings),
                fallback_used=False,
                error_message=f"Unexpected error: {e}",
                publish_stats=stats
            )
    
    async def _publish_fallback_review(
        self,
        repo_name: str,
        pr_number: int,
        head_sha: str,
        summary: str,
        findings: List[Dict[str, Any]],
        installation_id: int,
        review_run_id: Optional[str],
        stats: PublishStats,
        start_time: float
    ) -> PublishResult:
        """
        Publish a summary-only review when inline comments fail.
        
        Args:
            repo_name: Repository name.
            pr_number: Pull request number.
            head_sha: Commit SHA.
            summary: Review summary text.
            findings: All findings to include in summary.
            installation_id: GitHub installation ID.
            review_run_id: Internal review run ID.
            stats: Stats object to update.
            start_time: Original start time for duration calculation.
        
        Returns:
            PublishResult with fallback outcome.
        """
        # Build fallback body with all findings in summary
        fallback_body = self._build_fallback_summary(summary, findings)
        
        fallback_review_data = {
            "commit_id": head_sha,
            "body": fallback_body,
            "event": "COMMENT",
            "comments": []  # No inline comments
        }
        
        try:
            stats.github_api_calls += 1
            response = await self.pr_api_client.create_review(
                repo_name=repo_name,
                pr_number=pr_number,
                review_data=fallback_review_data,
                installation_id=installation_id
            )
            
            duration_ms = int((time.time() - start_time) * 1000)
            stats.publish_duration_ms = duration_ms
            
            logger.info(
                f"Published fallback summary-only review {response.get('id')} "
                f"for {repo_name}#{pr_number}"
            )
            
            return PublishResult(
                published=True,
                github_review_id=response.get("id"),
                review_run_id=review_run_id,
                anchored_comments=0,
                unanchored_findings=len(findings),
                total_findings=len(findings),
                fallback_used=True,
                publish_stats=stats
            )
        
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            stats.publish_duration_ms = duration_ms
            
            logger.error(
                f"Fallback review also failed for {repo_name}#{pr_number}: {e}"
            )
            
            return PublishResult(
                published=False,
                review_run_id=review_run_id,
                anchored_comments=0,
                unanchored_findings=len(findings),
                total_findings=len(findings),
                fallback_used=True,
                error_message=f"Fallback also failed: {e}",
                publish_stats=stats
            )
    
    def _split_findings(
        self,
        findings: List[Dict[str, Any]],
        patches: List[PRFilePatch]
    ) -> Tuple[List[AnchoredComment], List[Dict[str, Any]], Dict[str, int]]:
        """
        Split findings into anchorable and unanchorable.
        
        Args:
            findings: List of finding dicts from LLM output.
            patches: List of PR file patches.
        
        Returns:
            Tuple of:
            - List of AnchoredComment objects for findings with valid positions
            - List of finding dicts that cannot be anchored
            - Stats dict with calculation/failure/adjustment counts
        """
        anchored = []
        unanchored = []
        stats = {"calculations": 0, "failures": 0, "adjustments": 0}
        
        for finding in findings:
            # Check if finding has anchoring data
            hunk_id = finding.get("hunk_id")
            line_in_hunk = finding.get("line_in_hunk")
            file_path = finding.get("file_path", "")
            
            if hunk_id is None or line_in_hunk is None:
                # No anchoring data - goes to summary
                unanchored.append(finding)
                continue
            
            # Calculate position
            stats["calculations"] += 1
            result = self.diff_calculator.calculate_position(
                file_path=file_path,
                hunk_id=hunk_id,
                line_in_hunk=line_in_hunk,
                patches=patches
            )
            
            if result.position is None:
                # Position calculation failed
                stats["failures"] += 1
                unanchored.append(finding)
                logger.debug(
                    f"Position calculation failed for finding {finding.get('finding_id')}: "
                    f"{result.failure_reason}"
                )
                continue
            
            if result.adjustment_applied:
                stats["adjustments"] += 1
            
            # Create anchored comment
            comment_body = self._format_inline_comment(finding)
            anchored.append(AnchoredComment(
                path=file_path,
                position=result.position,
                body=comment_body,
                finding=finding
            ))
        
        return anchored, unanchored, stats
    
    def _build_comments_payload(
        self,
        anchored_comments: List[AnchoredComment]
    ) -> List[Dict[str, Any]]:
        """
        Build the comments payload for GitHub API.
        
        Args:
            anchored_comments: List of anchored comments.
        
        Returns:
            List of comment dicts for GitHub API.
        """
        return [
            {
                "path": comment.path,
                "position": comment.position,
                "body": comment.body
            }
            for comment in anchored_comments
        ]
    
    def _format_finding(
        self,
        finding: Dict[str, Any],
        include_file_path: bool = False,
        as_section: bool = False
    ) -> str:
        """
        Format a finding as markdown.
        
        Args:
            finding: Finding dict with severity, title, message, etc.
            include_file_path: Whether to include file path (for summary findings).
            as_section: Whether to format as a section with #### header (for summary).
        
        Returns:
            Markdown-formatted finding.
        """
        severity = finding.get("severity", "medium").lower()
        label = SEVERITY_LABELS.get(severity, "[INFO]")
        title = finding.get("title", "Code Review Finding")
        message = finding.get("message", "")
        suggested_fix = finding.get("suggested_fix", "")
        confidence = finding.get("confidence", 0.0)
        category = finding.get("category", "")
        file_path = finding.get("file_path", "")
        
        # Build header based on context
        if as_section:
            lines = [f"#### {label} {title}"]
        else:
            lines = [f"{label} **{title}**", ""]
        
        # File path (only for summary findings)
        if include_file_path and file_path:
            lines.append(f"**File:** `{file_path}`")
        
        # Meta information
        meta_parts = []
        if include_file_path and severity:
            meta_parts.append(f"Severity: {severity}")
        if category:
            meta_parts.append(f"Category: {category}")
        if meta_parts:
            lines.append(f"*{' | '.join(meta_parts)}*")
        elif not as_section and category:
            # For inline comments, just show category
            lines.append(f"*Category: {category}*")
        
        lines.append("")
        
        if message:
            lines.append(message)
            lines.append("")
        
        if suggested_fix:
            lines.append("**Suggested Fix:**")
            # Check if suggested_fix contains code-like content
            if any(char in suggested_fix for char in ['{', '}', '(', ')', '=', ';', 'def ', 'class ']):
                lines.append("```")
                lines.append(suggested_fix)
                lines.append("```")
            else:
                lines.append(suggested_fix)
            lines.append("")
        
        # Confidence indicator
        lines.append(f"*Confidence: {confidence * 100:.0f}%*")
        
        return "\n".join(lines)
    
    def _format_inline_comment(self, finding: Dict[str, Any]) -> str:
        """Format a finding as a GitHub inline comment."""
        return self._format_finding(finding, include_file_path=False, as_section=False)
    
    def _build_review_body(
        self,
        summary: str,
        unanchored_findings: List[Dict[str, Any]]
    ) -> str:
        """
        Build the main review body with summary and unanchored findings.
        
        Args:
            summary: Review summary text.
            unanchored_findings: Findings that couldn't be anchored to diff.
        
        Returns:
            Markdown-formatted review body.
        """
        parts = []
        
        # Summary section
        if summary:
            parts.append("## Summary")
            parts.append("")
            parts.append(summary)
            parts.append("")
        
        # Unanchored findings section
        if unanchored_findings:
            parts.append("## Additional Findings")
            parts.append("")
            parts.append(
                "*The following findings could not be anchored to specific "
                "diff locations:*"
            )
            parts.append("")
            
            for finding in unanchored_findings:
                parts.append(self._format_summary_finding(finding))
                parts.append("")
        
        # Footer
        parts.append("---")
        parts.append("*Generated by Sentinel AI*")
        
        return "\n".join(parts)
    
    def _build_fallback_summary(
        self,
        summary: str,
        findings: List[Dict[str, Any]]
    ) -> str:
        """
        Build a summary-only review body when inline comments fail.
        
        All findings are included in the body since they cannot be
        placed as inline comments.
        
        Args:
            summary: Review summary text.
            findings: All findings to include.
        
        Returns:
            Markdown-formatted review body.
        """
        parts = []
        
        # Note about fallback
        parts.append(
            "> **Note:** Inline comments could not be placed. "
            "All findings are listed below."
        )
        parts.append("")
        
        # Summary section
        if summary:
            parts.append("## Summary")
            parts.append("")
            parts.append(summary)
            parts.append("")
        
        # All findings
        if findings:
            parts.append("## Findings")
            parts.append("")
            
            # Group by severity
            severity_order = ["critical", "blocker", "high", "medium", "low", "nit"]
            findings_by_severity: Dict[str, List[Dict[str, Any]]] = {}
            
            for finding in findings:
                sev = finding.get("severity", "medium").lower()
                # Normalize "blocker" to "critical"
                if sev == "blocker":
                    sev = "critical"
                if sev not in findings_by_severity:
                    findings_by_severity[sev] = []
                findings_by_severity[sev].append(finding)
            
            for severity in severity_order:
                if severity in findings_by_severity:
                    sev_findings = findings_by_severity[severity]
                    label = SEVERITY_LABELS.get(severity, "[INFO]")
                    parts.append(f"### {label} {severity.title()} ({len(sev_findings)})")
                    parts.append("")
                    
                    for finding in sev_findings:
                        parts.append(self._format_summary_finding(finding))
                        parts.append("")
        
        # Footer
        parts.append("---")
        parts.append("*Generated by Sentinel AI*")
        
        return "\n".join(parts)
    
    def _format_summary_finding(self, finding: Dict[str, Any]) -> str:
        """Format a finding for inclusion in the review summary."""
        return self._format_finding(finding, include_file_path=True, as_section=True)
