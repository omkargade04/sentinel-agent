"""
Review Output Models

Contains Pydantic schemas for structured LLM review output including findings and review summary.
These models enforce strict schema validation for AI-generated content.
"""

from pydantic import BaseModel, Field, validator, computed_field
from typing import List, Optional, Literal, Dict, Any
from enum import Enum


class FindingSeverity(str, Enum):
    """Severity levels for code review findings."""
    BLOCKER = "blocker"      # Critical issues that must be fixed
    HIGH = "high"            # Important issues that should be fixed
    MEDIUM = "medium"        # Moderate issues worth addressing
    LOW = "low"              # Minor issues or suggestions
    NIT = "nit"              # Nitpicks and style preferences


class FindingCategory(str, Enum):
    """Categories for code review findings."""
    BUG = "bug"                        # Logic errors, incorrect behavior
    SECURITY = "security"              # Security vulnerabilities
    PERFORMANCE = "performance"        # Performance issues
    STYLE = "style"                    # Code style and formatting
    DESIGN = "design"                  # Architecture and design issues
    DOCS = "docs"                      # Documentation issues
    OBSERVABILITY = "observability"   # Logging, monitoring, debugging
    MAINTAINABILITY = "maintainability" # Code maintainability concerns


class Finding(BaseModel):
    """Single code review finding with anchoring information."""

    finding_id: str = Field(
        ...,
        description="Unique finding identifier within the review",
        regex=r'^finding_\d+$'
    )
    severity: FindingSeverity = Field(..., description="Severity level of this finding")
    category: FindingCategory = Field(..., description="Category/type of finding")

    # Content
    title: str = Field(
        ...,
        description="Concise finding title (max 255 chars)",
        max_length=255
    )
    message: str = Field(..., description="Detailed explanation of the issue")
    suggested_fix: str = Field(..., description="Actionable fix suggestion")

    # Anchoring for diff positioning
    file_path: str = Field(..., description="File path where finding applies")
    hunk_id: Optional[str] = Field(
        None,
        description="Diff hunk ID for anchoring (enables inline comments)"
    )
    line_in_hunk: Optional[int] = Field(
        None,
        description="0-based line offset within the hunk",
        ge=0
    )

    # Quality and confidence metrics
    confidence: float = Field(
        ...,
        description="Confidence score for this finding (0.0-1.0)",
        ge=0.0,
        le=1.0
    )

    # Additional metadata
    related_symbols: List[str] = Field(
        default_factory=list,
        description="Symbol names related to this finding"
    )
    code_examples: List[str] = Field(
        default_factory=list,
        description="Code snippets referenced in the finding",
        max_items=3
    )

    @validator('title')
    def validate_title_not_empty(cls, v):
        """Ensure title is not empty and properly trimmed."""
        title = v.strip()
        if not title:
            raise ValueError('Finding title cannot be empty')
        return title

    @validator('message')
    def validate_message_not_empty(cls, v):
        """Ensure message is not empty and has minimum content."""
        message = v.strip()
        if not message:
            raise ValueError('Finding message cannot be empty')
        if len(message) < 10:
            raise ValueError('Finding message must be at least 10 characters')
        return message

    @validator('suggested_fix')
    def validate_suggested_fix_not_empty(cls, v):
        """Ensure suggested fix is actionable."""
        fix = v.strip()
        if not fix:
            raise ValueError('Suggested fix cannot be empty')
        if len(fix) < 10:
            raise ValueError('Suggested fix must be at least 10 characters')
        return fix

    @validator('file_path')
    def validate_file_path(cls, v):
        """Normalize file path."""
        if not v.strip():
            raise ValueError('File path cannot be empty')
        return v.strip().replace('\\', '/').strip('/')

    @validator('line_in_hunk')
    def validate_line_in_hunk_requires_hunk_id(cls, v, values):
        """Ensure line_in_hunk is only set when hunk_id is provided."""
        if v is not None and not values.get('hunk_id'):
            raise ValueError('line_in_hunk requires hunk_id to be set')
        return v

    @computed_field
    @property
    def is_anchorable(self) -> bool:
        """Whether this finding can be anchored to a diff position."""
        return self.hunk_id is not None and self.line_in_hunk is not None

    @computed_field
    @property
    def is_high_confidence(self) -> bool:
        """Whether this is a high confidence finding (>= 0.7)."""
        return self.confidence >= 0.7

    @computed_field
    @property
    def is_critical(self) -> bool:
        """Whether this finding is critical (blocker or high severity)."""
        return self.severity in [FindingSeverity.BLOCKER, FindingSeverity.HIGH]

    @computed_field
    @property
    def display_severity(self) -> str:
        """Display-friendly severity name."""
        return self.severity.upper()

    class Config:
        use_enum_values = True
        schema_extra = {
            "example": {
                "finding_id": "finding_1",
                "severity": "high",
                "category": "bug",
                "title": "Potential null pointer dereference in calculateSum",
                "message": "The function doesn't validate input parameters before use, which could lead to null pointer exceptions in certain scenarios.",
                "suggested_fix": "Add input validation at the beginning of the function: if (a == null || b == null) throw new IllegalArgumentException('Parameters cannot be null');",
                "file_path": "src/utils.py",
                "hunk_id": "hunk_1_src_utils_py",
                "line_in_hunk": 2,
                "confidence": 0.85,
                "related_symbols": ["calculate_sum"],
                "code_examples": ["def calculate_sum(a, b): return a + b"]
            }
        }


class ReviewGenerationStats(BaseModel):
    """Statistics about the review generation process."""

    total_findings_generated: int = Field(..., description="Total findings generated", ge=0)
    high_confidence_findings: int = Field(..., description="High confidence findings (>= 0.7)", ge=0)
    anchored_findings: int = Field(..., description="Findings that can be anchored to diff", ge=0)
    unanchored_findings: int = Field(..., description="Findings without diff anchoring", ge=0)

    # Breakdown by severity
    findings_by_severity: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of findings by severity level"
    )

    # Breakdown by category
    findings_by_category: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of findings by category"
    )

    # Generation metadata
    generation_duration_ms: Optional[int] = Field(
        None,
        description="Time taken to generate review in milliseconds",
        ge=0
    )
    model_used: Optional[str] = Field(None, description="LLM model used for generation")
    token_usage: Optional[Dict[str, int]] = Field(
        None,
        description="Token usage statistics (prompt_tokens, completion_tokens, total_tokens)"
    )

    @computed_field
    @property
    def anchoring_rate(self) -> float:
        """Percentage of findings that are anchorable."""
        if self.total_findings_generated == 0:
            return 0.0
        return (self.anchored_findings / self.total_findings_generated) * 100.0

    @computed_field
    @property
    def confidence_rate(self) -> float:
        """Percentage of high confidence findings."""
        if self.total_findings_generated == 0:
            return 0.0
        return (self.high_confidence_findings / self.total_findings_generated) * 100.0

    class Config:
        schema_extra = {
            "example": {
                "total_findings_generated": 5,
                "high_confidence_findings": 4,
                "anchored_findings": 4,
                "unanchored_findings": 1,
                "findings_by_severity": {
                    "high": 2,
                    "medium": 2,
                    "low": 1
                },
                "findings_by_category": {
                    "bug": 2,
                    "style": 2,
                    "performance": 1
                },
                "generation_duration_ms": 8000,
                "model_used": "gpt-4",
                "token_usage": {
                    "prompt_tokens": 12000,
                    "completion_tokens": 800,
                    "total_tokens": 12800
                }
            }
        }


class LLMReviewOutput(BaseModel):
    """Complete LLM review output with strict schema validation."""

    findings: List[Finding] = Field(
        ...,
        description="List of code review findings",
        min_items=0,
        max_items=20  # Hard limit as per TRD
    )
    summary: str = Field(..., description="Overall review summary")

    # Optional repository-wide insights
    patterns: Optional[List[str]] = Field(
        None,
        description="Repository-wide patterns or trends observed",
        max_items=5
    )
    recommendations: Optional[List[str]] = Field(
        None,
        description="General recommendations for the codebase",
        max_items=3
    )

    # Generation metadata (computed from findings)
    total_findings: int = Field(..., description="Total number of findings", ge=0)
    high_confidence_findings: int = Field(..., description="Number of high confidence findings", ge=0)

    # Generation statistics
    stats: Optional[ReviewGenerationStats] = Field(None, description="Review generation statistics")

    # Review metadata
    review_timestamp: str = Field(..., description="When the review was generated")
    review_version: str = Field(default="v1", description="Review schema version")

    @validator('findings')
    def validate_findings_unique_ids(cls, v):
        """Ensure all finding IDs are unique."""
        finding_ids = [f.finding_id for f in v]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError('Finding IDs must be unique')
        return v

    @validator('findings')
    def validate_findings_sequential_ids(cls, v):
        """Ensure finding IDs are sequential (finding_1, finding_2, etc.)."""
        expected_ids = [f"finding_{i+1}" for i in range(len(v))]
        actual_ids = sorted([f.finding_id for f in v])
        if actual_ids != expected_ids:
            raise ValueError(f'Finding IDs must be sequential: expected {expected_ids}, got {actual_ids}')
        return v

    @validator('summary')
    def validate_summary_not_empty(cls, v):
        """Ensure summary is meaningful."""
        summary = v.strip()
        if not summary:
            raise ValueError('Review summary cannot be empty')
        if len(summary) < 20:
            raise ValueError('Review summary must be at least 20 characters')
        return summary

    @validator('total_findings', always=True)
    def validate_total_findings_matches(cls, v, values):
        """Ensure total_findings matches actual findings count."""
        if 'findings' in values:
            actual_count = len(values['findings'])
            if v != actual_count:
                raise ValueError(f'total_findings ({v}) must match findings count ({actual_count})')
        return v

    @validator('high_confidence_findings', always=True)
    def validate_high_confidence_count(cls, v, values):
        """Ensure high_confidence_findings count is accurate."""
        if 'findings' in values:
            actual_count = sum(1 for f in values['findings'] if f.is_high_confidence)
            if v != actual_count:
                raise ValueError(f'high_confidence_findings ({v}) must match actual count ({actual_count})')
        return v

    @computed_field
    @property
    def anchored_findings(self) -> List[Finding]:
        """Findings that can be anchored to diff positions."""
        return [f for f in self.findings if f.is_anchorable]

    @computed_field
    @property
    def unanchored_findings(self) -> List[Finding]:
        """Findings that cannot be anchored to diff positions."""
        return [f for f in self.findings if not f.is_anchorable]

    @computed_field
    @property
    def critical_findings(self) -> List[Finding]:
        """Critical findings (blocker or high severity)."""
        return [f for f in self.findings if f.is_critical]

    def get_findings_by_severity(self, severity: FindingSeverity) -> List[Finding]:
        """Get all findings of a specific severity."""
        return [f for f in self.findings if f.severity == severity]

    def get_findings_by_category(self, category: FindingCategory) -> List[Finding]:
        """Get all findings of a specific category."""
        return [f for f in self.findings if f.category == category]

    def get_findings_by_file(self, file_path: str) -> List[Finding]:
        """Get all findings for a specific file."""
        return [f for f in self.findings if f.file_path == file_path]

    class Config:
        use_enum_values = True
        schema_extra = {
            "example": {
                "findings": [
                    {
                        "finding_id": "finding_1",
                        "severity": "high",
                        "category": "bug",
                        "title": "Potential null pointer dereference",
                        "message": "Input validation missing",
                        "suggested_fix": "Add null checks",
                        "file_path": "src/utils.py",
                        "confidence": 0.85
                    }
                ],
                "summary": "The PR introduces improvements to the utility functions with good test coverage. However, there are some input validation concerns that should be addressed.",
                "patterns": ["Missing input validation pattern"],
                "total_findings": 1,
                "high_confidence_findings": 1,
                "review_timestamp": "2026-01-15T10:40:00Z"
            }
        }