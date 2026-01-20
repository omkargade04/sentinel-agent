"""
Diff Position Calculator for GitHub PR Reviews

Converts finding anchoring data (file_path, hunk_id, line_in_hunk) into
GitHub's diff position format for inline comment placement.

GitHub's position is a 1-indexed count of lines from the start of the diff
for a given file, including hunk headers (@@ ... @@).
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from src.models.schemas.pr_review.pr_patch import PRFilePatch, PRHunk
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PositionResult:
    """Result of diff position calculation."""
    
    position: Optional[int]
    """GitHub diff position (1-indexed), or None if calculation failed."""
    
    adjusted_line_in_hunk: Optional[int]
    """Adjusted line index if removed-line adjustment was applied."""
    
    adjustment_applied: bool
    """Whether the target line was adjusted (e.g., shifted from a removed line)."""
    
    failure_reason: Optional[str]
    """Reason for failure if position is None."""


class DiffPositionCalculator:
    """
    Calculator for converting finding anchoring data to GitHub diff positions.
    
    GitHub's diff position system works as follows:
    - Position is 1-indexed from the start of the file's diff
    - Each hunk header (@@ -a,b +c,d @@) counts as 1 line
    - Each line within a hunk (context, addition, deletion) counts as 1 line
    - Comments can only be placed on addition (+) or context ( ) lines, not deletions (-)
    
    Example diff with positions:
        Position 1: @@ -10,7 +10,8 @@
        Position 2:  def calculate_sum(a, b):    (context line)
        Position 3:      '''Add two numbers.'''  (context line)
        Position 4: -    return a + b             (deletion - cannot comment)
        Position 5: +    # Add validation         (addition - can comment)
        Position 6: +    return a + b             (addition - can comment)
    
    Usage:
        calculator = DiffPositionCalculator()
        result = calculator.calculate_position(
            file_path="src/utils.py",
            hunk_id="hunk_1_src_utils_py",
            line_in_hunk=3,  # 0-based index into hunk.lines
            patches=patches
        )
        if result.position:
            # Use result.position for GitHub API
    """
    
    def calculate_position(
        self,
        file_path: str,
        hunk_id: str,
        line_in_hunk: int,
        patches: List[PRFilePatch]
    ) -> PositionResult:
        """
        Calculate GitHub diff position from anchoring data.
        
        Args:
            file_path: Path to the file containing the finding.
            hunk_id: Unique identifier of the target hunk.
            line_in_hunk: 0-based index into PRHunk.lines array.
            patches: List of all file patches from the PR.
        
        Returns:
            PositionResult with calculated position or failure reason.
        """
        # Find the patch for this file
        patch = self._find_patch_by_path(file_path, patches)
        if patch is None:
            logger.debug(f"Patch not found for file: {file_path}")
            return PositionResult(
                position=None,
                adjusted_line_in_hunk=None,
                adjustment_applied=False,
                failure_reason=f"No patch found for file: {file_path}"
            )
        
        # Find the specific hunk
        hunk = self._find_hunk_by_id(hunk_id, patch.hunks)
        if hunk is None:
            logger.debug(f"Hunk not found: {hunk_id} in file {file_path}")
            return PositionResult(
                position=None,
                adjusted_line_in_hunk=None,
                adjustment_applied=False,
                failure_reason=f"Hunk not found: {hunk_id}"
            )
        
        # Validate line_in_hunk bounds
        validation_error = self._validate_line_in_hunk(line_in_hunk, hunk)
        if validation_error:
            logger.debug(f"Invalid line_in_hunk: {validation_error}")
            return PositionResult(
                position=None,
                adjusted_line_in_hunk=None,
                adjustment_applied=False,
                failure_reason=validation_error
            )
        
        # Check if target line is a removed line and adjust if needed
        adjusted_line, adjustment_applied = self._adjust_for_removed_lines(
            line_in_hunk, hunk
        )
        
        if adjusted_line is None:
            logger.debug(
                f"Cannot comment on line {line_in_hunk} in hunk {hunk_id}: "
                "all nearby lines are deletions"
            )
            return PositionResult(
                position=None,
                adjusted_line_in_hunk=None,
                adjustment_applied=True,
                failure_reason="Target line is a deletion and no valid adjacent line found"
            )
        
        # Calculate the absolute position
        position = self._calculate_absolute_position(patch, hunk, adjusted_line)
        
        logger.debug(
            f"Calculated position {position} for {file_path}:{hunk_id}:"
            f"{line_in_hunk} (adjusted={adjustment_applied})"
        )
        
        return PositionResult(
            position=position,
            adjusted_line_in_hunk=adjusted_line if adjustment_applied else None,
            adjustment_applied=adjustment_applied,
            failure_reason=None
        )
    
    def _find_patch_by_path(
        self,
        file_path: str,
        patches: List[PRFilePatch]
    ) -> Optional[PRFilePatch]:
        """
        Find the patch for a given file path.
        
        Args:
            file_path: Normalized file path to search for.
            patches: List of all patches in the PR.
        
        Returns:
            Matching PRFilePatch or None if not found.
        """
        # Normalize the search path
        normalized_path = file_path.strip().replace("\\", "/").strip("/")
        
        for patch in patches:
            patch_path = patch.file_path.strip().replace("\\", "/").strip("/")
            if patch_path == normalized_path:
                return patch
        
        return None
    
    def _find_hunk_by_id(
        self,
        hunk_id: str,
        hunks: List[PRHunk]
    ) -> Optional[PRHunk]:
        """
        Find a hunk by its unique identifier.
        
        Args:
            hunk_id: The hunk_id to search for.
            hunks: List of hunks in the patch.
        
        Returns:
            Matching PRHunk or None if not found.
        """
        for hunk in hunks:
            if hunk.hunk_id == hunk_id:
                return hunk
        return None
    
    def _validate_line_in_hunk(
        self,
        line_in_hunk: int,
        hunk: PRHunk
    ) -> Optional[str]:
        """
        Validate that line_in_hunk is within bounds.
        
        Args:
            line_in_hunk: 0-based line index.
            hunk: The target hunk.
        
        Returns:
            Error message if invalid, None if valid.
        """
        if line_in_hunk < 0:
            return f"line_in_hunk cannot be negative: {line_in_hunk}"
        
        if line_in_hunk >= len(hunk.lines):
            return (
                f"line_in_hunk {line_in_hunk} is out of range "
                f"(hunk has {len(hunk.lines)} lines)"
            )
        
        return None
    
    def _adjust_for_removed_lines(
        self,
        line_in_hunk: int,
        hunk: PRHunk
    ) -> Tuple[Optional[int], bool]:
        """
        Adjust target line if it's a deletion (starts with '-').
        
        GitHub doesn't allow comments on removed lines. If the target line
        is a deletion, search for the nearest commentable line (addition or context):
        1. First search forward from the target line
        2. If not found, search backward
        
        Args:
            line_in_hunk: Original 0-based line index.
            hunk: The target hunk.
        
        Returns:
            Tuple of (adjusted_line_index, was_adjusted).
            If no valid line found, returns (None, True).
        """
        lines = hunk.lines
        
        # Check if target line is commentable (not a deletion)
        if not self._is_deletion_line(lines[line_in_hunk]):
            return (line_in_hunk, False)
        
        # Target is a deletion - need to find nearest commentable line
        
        # Search forward first
        for i in range(line_in_hunk + 1, len(lines)):
            if not self._is_deletion_line(lines[i]):
                return (i, True)
        
        # Search backward
        for i in range(line_in_hunk - 1, -1, -1):
            if not self._is_deletion_line(lines[i]):
                return (i, True)
        
        # All lines in hunk are deletions - cannot comment
        return (None, True)
    
    def _is_deletion_line(self, line: str) -> bool:
        """
        Check if a diff line is a deletion.
        
        Args:
            line: A single line from PRHunk.lines.
        
        Returns:
            True if line starts with '-' (deletion), False otherwise.
        """
        return line.startswith("-")
    
    def _calculate_absolute_position(
        self,
        patch: PRFilePatch,
        target_hunk: PRHunk,
        line_in_hunk: int
    ) -> int:
        """
        Calculate the absolute diff position for GitHub API.
        
        The position is calculated as:
        - Sum of (1 + len(hunk.lines)) for all hunks before target hunk
          (the +1 accounts for the @@ header line)
        - Plus 1 for the target hunk's header
        - Plus (line_in_hunk + 1) for the line within the target hunk
        
        Args:
            patch: The file patch containing all hunks.
            target_hunk: The hunk containing the target line.
            line_in_hunk: 0-based index into target_hunk.lines.
        
        Returns:
            1-indexed position for GitHub API.
        """
        position = 0
        
        for hunk in patch.hunks:
            if hunk.hunk_id == target_hunk.hunk_id:
                # We're at the target hunk
                # Add 1 for the header line, then the line offset (1-indexed)
                position += 1 + (line_in_hunk + 1)
                break
            else:
                # Add this hunk's total contribution:
                # 1 for header + number of content lines
                position += 1 + len(hunk.lines)
        
        return position
    
    def calculate_position_for_finding(
        self,
        finding: dict,
        patches: List[PRFilePatch]
    ) -> PositionResult:
        """
        Convenience method to calculate position from a finding dict.
        
        Args:
            finding: Finding dict with file_path, hunk_id, line_in_hunk.
            patches: List of all file patches.
        
        Returns:
            PositionResult with calculated position or failure reason.
        """
        file_path = finding.get("file_path")
        hunk_id = finding.get("hunk_id")
        line_in_hunk = finding.get("line_in_hunk")
        
        # Validate required fields
        if not file_path:
            return PositionResult(
                position=None,
                adjusted_line_in_hunk=None,
                adjustment_applied=False,
                failure_reason="Finding missing file_path"
            )
        
        if hunk_id is None:
            return PositionResult(
                position=None,
                adjusted_line_in_hunk=None,
                adjustment_applied=False,
                failure_reason="Finding missing hunk_id"
            )
        
        if line_in_hunk is None:
            return PositionResult(
                position=None,
                adjusted_line_in_hunk=None,
                adjustment_applied=False,
                failure_reason="Finding missing line_in_hunk"
            )
        
        return self.calculate_position(file_path, hunk_id, line_in_hunk, patches)
