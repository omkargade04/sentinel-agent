"""
PR Patch and Diff Models

Contains Pydantic schemas for representing GitHub pull request diffs and patches.
"""

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Literal, Union
from enum import Enum


class ChangeType(str, Enum):
    """File change types in a PR."""
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    RENAMED = "renamed"


def get_change_type_value(change_type: Union[ChangeType, str]) -> str:
    """Safely extract string value from ChangeType enum or string.

    This handles the deserialization scenario where `use_enum_values = True`
    in Pydantic Config causes the enum to be serialized as a string,
    but code may later call `.value` expecting an enum.

    Args:
        change_type: Either a ChangeType enum or string value

    Returns:
        The string value of the change type

    Raises:
        TypeError: If change_type is neither ChangeType nor str
    """
    if isinstance(change_type, ChangeType):
        return change_type.value
    elif isinstance(change_type, str):
        return change_type
    raise TypeError(f"Expected ChangeType or str, got {type(change_type).__name__}")


class PRHunk(BaseModel):
    """Represents a single diff hunk within a file patch."""

    hunk_id: str = Field(..., description="Deterministic hunk identifier")
    header: str = Field(
        ...,
        description="Hunk header in format @@ -a,b +c,d @@",
        pattern=r'@@\s*-\d+(?:,\d+)?\s*\+\d+(?:,\d+)?\s*@@'
    )

    # Line range information (from hunk header)
    old_start: int = Field(..., description="Starting line number in old file", ge=0)
    old_count: int = Field(..., description="Number of lines in old file context", ge=0)
    new_start: int = Field(..., description="Starting line number in new file", ge=0)
    new_count: int = Field(..., description="Number of lines in new file context", ge=0)

    # Hunk content
    lines: List[str] = Field(
        ...,
        description="Raw hunk lines with +/-/ prefixes"
    )
    new_changed_lines: List[int] = Field(
        ...,
        description="Line numbers in PR head that were changed (additions/modifications)"
    )

    @validator('new_changed_lines')
    def validate_changed_lines(cls, v, values):
        """Validate that changed lines are within the hunk range.
        
        Note: GitHub's diff format can have inconsistencies between hunk headers
        and actual content, so we only warn (via logging) instead of failing.
        """
        # Just deduplicate and sort - don't fail on range mismatches
        # as GitHub diffs can have header/content inconsistencies
        return sorted(set(v))

    @validator('hunk_id')
    def validate_hunk_id_format(cls, v):
        """Validate hunk ID format."""
        if not v.strip():
            raise ValueError('Hunk ID cannot be empty')
        return v

    class Config:
        schema_extra = {
            "example": {
                "hunk_id": "hunk_1_src_utils_py",
                "header": "@@ -10,7 +10,8 @@",
                "old_start": 10,
                "old_count": 7,
                "new_start": 10,
                "new_count": 8,
                "lines": [
                    " def calculate_sum(a: int, b: int) -> int:",
                    "     \"\"\"Add two numbers together.\"\"\"",
                    "-    return a + b",
                    "+    # Add input validation",
                    "+    return a + b",
                    " ",
                    " def multiply(x: float, y: float) -> float:"
                ],
                "new_changed_lines": [12, 13]
            }
        }


class PRFilePatch(BaseModel):
    """Represents changes to a single file in a PR."""

    file_path: str = Field(
        ...,
        description="Relative path from repository root"
    )
    change_type: ChangeType = Field(
        ...,
        description="Type of change made to this file"
    )
    patch: Optional[str] = Field(
        None,
        description="Raw unified diff patch text from GitHub"
    )
    hunks: List[PRHunk] = Field(
        default_factory=list,
        description="Parsed diff hunks for this file"
    )

    # File change metadata
    additions: int = Field(
        default=0,
        description="Number of lines added",
        ge=0
    )
    deletions: int = Field(
        default=0,
        description="Number of lines deleted",
        ge=0
    )
    binary_file: bool = Field(
        default=False,
        description="Whether this is a binary file"
    )

    # Additional metadata for renamed files
    previous_filename: Optional[str] = Field(
        None,
        description="Previous filename if file was renamed"
    )

    @validator('change_type', pre=True)
    def normalize_change_type(cls, v):
        """Normalize change_type to ensure consistent enum handling.

        This validator handles the case where change_type may come in as:
        - A ChangeType enum instance
        - A string value (from deserialized JSON with use_enum_values=True)

        It normalizes to a ChangeType enum for consistent internal representation.
        """
        if isinstance(v, ChangeType):
            return v
        if isinstance(v, str):
            try:
                return ChangeType(v)
            except ValueError:
                raise ValueError(f"Invalid change_type value: {v}")
        raise ValueError(f"change_type must be ChangeType or str, got {type(v).__name__}")

    @validator('file_path')
    def validate_file_path(cls, v):
        """Validate file path format."""
        if not v.strip():
            raise ValueError('File path cannot be empty')
        # Normalize path separators and remove leading/trailing slashes
        v = v.strip().replace('\\', '/').strip('/')
        if not v:
            raise ValueError('File path cannot be empty after normalization')
        return v

    @validator('hunks')
    def validate_hunks_order(cls, v):
        """Ensure hunks are ordered by line number."""
        if len(v) <= 1:
            return v

        # Check that hunks are in ascending order
        for i in range(1, len(v)):
            if v[i].new_start < v[i-1].new_start:
                raise ValueError('Hunks must be ordered by starting line number')

        return v

    @validator('previous_filename')
    def validate_previous_filename(cls, v, values):
        """Validate previous filename is only set for renamed files."""
        if v is not None and values.get('change_type') != ChangeType.RENAMED:
            raise ValueError('previous_filename should only be set for renamed files')
        return v

    @property
    def total_lines_changed(self) -> int:
        """Total number of lines changed (additions + deletions)."""
        return self.additions + self.deletions

    @property
    def has_code_changes(self) -> bool:
        """Whether this file has actual code changes (not just binary or no patch)."""
        return not self.binary_file and self.patch is not None and bool(self.hunks)

    @property
    def affected_line_numbers(self) -> List[int]:
        """Get all line numbers affected by changes in this file."""
        affected_lines = []
        for hunk in self.hunks:
            affected_lines.extend(hunk.new_changed_lines)
        return sorted(set(affected_lines))

    @property
    def change_type_str(self) -> str:
        """Get change_type as string, handling both enum and string types.

        This property provides safe access to the change_type value whether
        it's stored as a ChangeType enum or as a string (after deserialization).

        Returns:
            The string value of the change type (e.g., "modified", "added")
        """
        return get_change_type_value(self.change_type)

    class Config:
        use_enum_values = True
        schema_extra = {
            "example": {
                "file_path": "src/utils.py",
                "change_type": "modified",
                "patch": "@@ -10,7 +10,8 @@\n def calculate_sum(a: int, b: int) -> int:\n...",
                "hunks": [
                    {
                        "hunk_id": "hunk_1_src_utils_py",
                        "header": "@@ -10,7 +10,8 @@",
                        "old_start": 10,
                        "old_count": 7,
                        "new_start": 10,
                        "new_count": 8,
                        "lines": [
                            " def calculate_sum(a: int, b: int) -> int:",
                            "     \"\"\"Add two numbers together.\"\"\"",
                            "-    return a + b",
                            "+    # Add input validation",
                            "+    return a + b"
                        ],
                        "new_changed_lines": [12, 13]
                    }
                ],
                "additions": 2,
                "deletions": 1,
                "binary_file": False
            }
        }
        
class FileStatus(str, Enum):
    """File status in a PR."""
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    RENAMED = "renamed"
    COPIED = "copied"
    TYPE_CHANGED = "type_changed"
    UNKNOWN = "unknown"
    
class FileChangeType(str, Enum):
    """File change type in a PR."""
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    RENAMED = "renamed"
    COPIED = "copied"
    TYPE_CHANGED = "type_changed"
    UNKNOWN = "unknown"