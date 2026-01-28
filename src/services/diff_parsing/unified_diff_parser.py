"""
Unified Diff Parser

Parses GitHub unified diff format into structured PRFilePatch and PRHunk objects.
Handles various diff formats, binary files, and edge cases.
"""

import re
import hashlib
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass

from src.models.schemas.pr_review.pr_patch import (
    PRFilePatch,
    PRHunk,
    FileChangeType,
    FileStatus
)
from src.exceptions.pr_review_exceptions import (
    InvalidDiffFormatException,
    PRHunkParsingException,
    BinaryFileException
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class HunkInfo:
    """Parsed hunk header information."""
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    context_line: str


class UnifiedDiffParser:
    """
    Parse GitHub unified diffs into structured patch objects.

    Features:
    - Handles GitHub API file objects with patch data
    - Deterministic hunk ID generation for diff anchoring
    - Binary file detection and handling
    - Robust parsing with comprehensive error handling
    - Changed line extraction for symbol mapping
    """

    # Regex patterns for diff parsing
    HUNK_HEADER_PATTERN = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$')
    BINARY_DIFF_PATTERN = re.compile(r'Binary files? .* differ')
    FILE_MODE_PATTERN = re.compile(r'^(old|new) mode (\d+)$')
    INDEX_PATTERN = re.compile(r'^index ([0-9a-f]+)\.\.([0-9a-f]+)( \d+)?$')

    def __init__(self):
        self.logger = get_logger(__name__)

    def parse_pr_files(self, files_data: List[Dict[str, Any]]) -> List[PRFilePatch]:
        """
        Parse GitHub PR files API response into PRFilePatch objects.

        Args:
            files_data: List of file objects from GitHub API /pulls/{number}/files

        Returns:
            List of PRFilePatch objects with parsed hunks

        Raises:
            InvalidDiffFormatException: If diff format is invalid
            BinaryFileException: If file is binary and cannot be processed
        """
        patches = []

        for file_data in files_data:
            try:
                patch = self._parse_single_file(file_data)
                if patch:  # Skip None results (e.g., binary files)
                    patches.append(patch)
            except Exception as e:
                file_path = file_data.get('filename', 'unknown')
                self.logger.error(f"Failed to parse file {file_path}: {e}")

                # Re-raise specific exceptions, wrap others
                if isinstance(e, (InvalidDiffFormatException, BinaryFileException)):
                    raise
                else:
                    raise InvalidDiffFormatException(f"Failed to parse file {file_path}: {e}")

        self.logger.info(f"Successfully parsed {len(patches)} file patches")
        return patches

    def _parse_single_file(self, file_data: Dict[str, Any]) -> Optional[PRFilePatch]:
        """
        Parse a single file from GitHub API response.

        Args:
            file_data: Single file object from GitHub API

        Returns:
            PRFilePatch object or None for binary files

        Raises:
            BinaryFileException: If file is binary
            InvalidDiffFormatException: If patch format is invalid
        """
        filename = file_data.get('filename')
        if not filename:
            raise InvalidDiffFormatException("File missing filename")

        # Check for binary files
        if self._is_binary_file(file_data):
            raise BinaryFileException(filename)

        # Determine file status and change type
        status = self._determine_file_status(file_data)
        change_type = self._determine_change_type(file_data)

        # Get patch content
        patch_content = file_data.get('patch', '')
        if not patch_content and status != FileStatus.RENAMED:
            # No patch content - might be a rename-only or empty file
            self.logger.warning(f"No patch content for {filename} with status {status}")

        # Parse hunks from patch content
        hunks = []
        if patch_content:
            try:
                hunks = self.parse_patch_to_hunks(patch_content, filename)
            except Exception as e:
                raise InvalidDiffFormatException(f"Failed to parse hunks for {filename}: {e}")

        return PRFilePatch(
            file_path=filename,
            change_type=change_type,
            additions=file_data.get('additions', 0),
            deletions=file_data.get('deletions', 0),
            hunks=hunks,
            previous_filename=file_data.get('previous_filename'),
            patch=patch_content,
        )

    def parse_patch_to_hunks(self, patch_text: str, file_path: str) -> List[PRHunk]:
        """
        Parse patch text into structured hunk objects.

        Args:
            patch_text: Unified diff patch content
            file_path: File path for error reporting

        Returns:
            List of PRHunk objects

        Raises:
            PRHunkParsingException: If hunk parsing fails
        """
        if not patch_text.strip():
            return []

        hunks = []
        lines = patch_text.split('\n')
        i = 0

        # Skip diff header lines (until we find first hunk)
        while i < len(lines) and not lines[i].startswith('@@'):
            i += 1

        while i < len(lines):
            line = lines[i]

            # Look for hunk header
            if line.startswith('@@'):
                try:
                    hunk, consumed_lines = self._parse_single_hunk(lines[i:], file_path)
                    hunks.append(hunk)
                    i += consumed_lines
                except Exception as e:
                    raise PRHunkParsingException(file_path, line) from e
            else:
                i += 1

        self.logger.debug(f"Parsed {len(hunks)} hunks for {file_path}")
        return hunks

    def _parse_single_hunk(self, lines: List[str], file_path: str) -> Tuple[PRHunk, int]:
        """
        Parse a single hunk from diff lines.

        Args:
            lines: Diff lines starting with hunk header
            file_path: File path for hunk ID generation

        Returns:
            Tuple of (PRHunk object, number of lines consumed)

        Raises:
            PRHunkParsingException: If hunk format is invalid
        """
        if not lines or not lines[0].startswith('@@'):
            raise PRHunkParsingException(file_path, "Missing hunk header")

        # Parse hunk header
        header_line = lines[0]
        match = self.HUNK_HEADER_PATTERN.match(header_line)
        if not match:
            raise PRHunkParsingException(file_path, header_line)

        hunk_info = HunkInfo(
            old_start=int(match.group(1)),
            old_count=int(match.group(2) or '1'),
            new_start=int(match.group(3)),
            new_count=int(match.group(4) or '1'),
            context_line=match.group(5).strip()
        )

        # Generate deterministic hunk ID
        hunk_id = self.generate_hunk_id(file_path, header_line)

        # Collect hunk lines
        hunk_lines = [header_line]
        new_changed_lines = []
        i = 1
        new_line_number = hunk_info.new_start

        # Parse hunk body
        while i < len(lines):
            line = lines[i]

            # Stop at next hunk or end of diff
            if line.startswith('@@') or line.startswith('diff '):
                break

            hunk_lines.append(line)

            # Track line numbers for changed lines in new version
            if line.startswith('+'):
                new_changed_lines.append(new_line_number)
                new_line_number += 1
            elif line.startswith('-'):
                # Deleted line doesn't increment new line number
                pass
            else:
                # Context line (or malformed line treated as context)
                new_line_number += 1

            i += 1

        # Validate hunk completeness (optional - some diffs might be truncated)
        expected_lines = hunk_info.old_count + hunk_info.new_count
        actual_content_lines = len(hunk_lines) - 1  # Exclude header

        if actual_content_lines != expected_lines:
            self.logger.debug(
                f"Hunk line count mismatch in {file_path}: "
                f"expected {expected_lines}, got {actual_content_lines}"
            )

        return PRHunk(
            hunk_id=hunk_id,
            header=header_line,
            old_start=hunk_info.old_start,
            old_count=hunk_info.old_count,
            new_start=hunk_info.new_start,
            new_count=hunk_info.new_count,
            lines=hunk_lines,
            new_changed_lines=new_changed_lines
        ), i

    def generate_hunk_id(self, file_path: str, hunk_header: str) -> str:
        """
        Generate deterministic hunk ID for diff anchoring.

        Uses file path and hunk header to create a unique, stable identifier
        that will be consistent across different runs.

        Args:
            file_path: Path of the file
            hunk_header: Hunk header line (e.g., "@@ -1,4 +1,6 @@ function")

        Returns:
            Deterministic hunk ID string
        """
        # Combine file path and hunk header for uniqueness
        content = f"{file_path}::{hunk_header}"

        # Generate short hash for compactness
        hash_object = hashlib.sha256(content.encode('utf-8'))
        short_hash = hash_object.hexdigest()[:12]

        return f"hunk_{short_hash}"

    def extract_changed_lines(self, hunk_lines: List[str], new_start: int) -> List[int]:
        """
        Extract line numbers that were changed (added or modified) in the new version.

        Args:
            hunk_lines: Lines from the hunk (including header)
            new_start: Starting line number for new version

        Returns:
            List of line numbers that were changed in the new version
        """
        changed_lines = []
        new_line_number = new_start

        # Skip header line
        for line in hunk_lines[1:]:
            if line.startswith('+'):
                changed_lines.append(new_line_number)
                new_line_number += 1
            elif line.startswith('-'):
                # Deleted lines don't increment new line counter
                continue
            else:
                # Context line or other
                new_line_number += 1

        return changed_lines

    def _is_binary_file(self, file_data: Dict[str, Any]) -> bool:
        """
        Determine if file is binary based on GitHub API data.

        Args:
            file_data: GitHub API file object

        Returns:
            True if file is binary, False otherwise
        """
        # GitHub API marks binary files explicitly
        if file_data.get('binary'):
            return True

        # Check patch content for binary indicators
        patch = file_data.get('patch', '')
        if self.BINARY_DIFF_PATTERN.search(patch):
            return True

        # Check file extension for common binary types
        filename = file_data.get('filename', '')
        binary_extensions = {
            '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg',  # Images
            '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',  # Documents
            '.zip', '.tar', '.gz', '.rar', '.7z',  # Archives
            '.exe', '.dll', '.so', '.dylib',  # Executables
            '.mp3', '.mp4', '.avi', '.mov', '.wav',  # Media
            '.ttf', '.otf', '.woff', '.woff2',  # Fonts
        }

        return any(filename.lower().endswith(ext) for ext in binary_extensions)

    def _determine_file_status(self, file_data: Dict[str, Any]) -> FileStatus:
        """
        Determine file status from GitHub API data.

        Args:
            file_data: GitHub API file object

        Returns:
            FileStatus enum value
        """
        status = file_data.get('status', '')

        status_mapping = {
            'added': FileStatus.ADDED,
            'removed': FileStatus.REMOVED,
            'modified': FileStatus.MODIFIED,
            'renamed': FileStatus.RENAMED,
            'copied': FileStatus.COPIED
        }

        return status_mapping.get(status, FileStatus.MODIFIED)

    def _determine_change_type(self, file_data: Dict[str, Any]) -> FileChangeType:
        """
        Determine change type from file data.

        Args:
            file_data: GitHub API file object

        Returns:
            FileChangeType enum value
        """
        additions = file_data.get('additions', 0)
        deletions = file_data.get('deletions', 0)
        status = file_data.get('status', '')

        if status == 'added':
            return FileChangeType.ADDED
        elif status == 'removed':
            return FileChangeType.REMOVED
        elif status == 'renamed' and additions == 0 and deletions == 0:
            return FileChangeType.RENAMED
        elif additions > 0 and deletions == 0:
            return FileChangeType.ADDED
        elif additions == 0 and deletions > 0:
            return FileChangeType.REMOVED
        else:
            return FileChangeType.MODIFIED

    def validate_patch_integrity(self, patch: PRFilePatch) -> List[str]:
        """
        Validate patch integrity and return list of warnings.

        Args:
            patch: PRFilePatch to validate

        Returns:
            List of warning messages (empty if no issues)
        """
        warnings = []

        # Check if hunk line counts match additions/deletions
        total_additions = sum(
            len([line for line in hunk.lines if line.startswith('+')])
            for hunk in patch.hunks
        )
        total_deletions = sum(
            len([line for line in hunk.lines if line.startswith('-')])
            for hunk in patch.hunks
        )

        if total_additions != patch.additions:
            warnings.append(
                f"Addition count mismatch: patch says {patch.additions}, "
                f"hunks have {total_additions}"
            )

        if total_deletions != patch.deletions:
            warnings.append(
                f"Deletion count mismatch: patch says {patch.deletions}, "
                f"hunks have {total_deletions}"
            )

        # Check for overlapping hunks
        hunk_ranges = []
        for hunk in patch.hunks:
            new_end = hunk.new_start + hunk.new_count - 1
            hunk_ranges.append((hunk.new_start, new_end))

        hunk_ranges.sort()
        for i in range(len(hunk_ranges) - 1):
            current_end = hunk_ranges[i][1]
            next_start = hunk_ranges[i + 1][0]
            if current_end >= next_start:
                warnings.append(f"Overlapping hunks detected in {patch.file_path}")
                break

        return warnings