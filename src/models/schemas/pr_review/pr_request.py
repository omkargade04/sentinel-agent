"""
PR Review Workflow Input/Output Models

Contains Pydantic schemas for PR review workflow request and result data.
"""

from uuid import UUID
from pydantic import BaseModel, Field, validator
from typing import Optional, Literal
from datetime import datetime


class PRReviewRequest(BaseModel):
    """Input contract for PR review workflow."""

    # GitHub App context
    installation_id: int = Field(..., description="GitHub installation ID", gt=0)

    # Repository identification
    repo_id: UUID = Field(..., description="Internal repository UUID")
    github_repo_id: int = Field(..., description="GitHub repository ID", gt=0)
    github_repo_name: str = Field(
        ...,
        description="Repository name in owner/repo format",
        pattern=r'^[^/]+/[^/]+$'
    )

    # PR identification
    pr_number: int = Field(..., description="Pull request number", ge=1)
    head_sha: str = Field(
        ...,
        description="PR head commit SHA",
        min_length=40,
        max_length=40
    )
    base_sha: str = Field(
        ...,
        description="PR base commit SHA",
        min_length=40,
        max_length=40
    )

    @validator('head_sha', 'base_sha')
    def validate_sha_format(cls, v):
        """Validate SHA format is hexadecimal."""
        if not all(c in '0123456789abcdef' for c in v.lower()):
            raise ValueError('SHA must be a valid 40-character hexadecimal string')
        return v.lower()

    @validator('github_repo_name')
    def validate_repo_name_format(cls, v):
        """Validate repository name format."""
        parts = v.split('/')
        if len(parts) != 2:
            raise ValueError('Repository name must be in owner/repo format')
        if not all(part.strip() for part in parts):
            raise ValueError('Owner and repository name cannot be empty')
        return v

    class Config:
        schema_extra = {
            "example": {
                "installation_id": 12345,
                "repo_id": "123e4567-e89b-12d3-a456-426614174000",
                "github_repo_id": 987654321,
                "github_repo_name": "owner/repository",
                "pr_number": 123,
                "head_sha": "abc123def456789012345678901234567890abcd",
                "base_sha": "def456abc123789012345678901234567890bcda"
            }
        }


class PRReviewResult(BaseModel):
    """Output contract for PR review workflow."""

    status: Literal["completed", "failed", "cancelled"] = Field(
        ...,
        description="Final workflow status"
    )
    review_run_id: str = Field(..., description="Database review run ID (UUID string)")
    pr_number: int = Field(..., description="Pull request number", ge=1)
    head_sha: str = Field(
        ...,
        description="PR head commit SHA processed",
        min_length=40,
        max_length=40
    )

    # Publishing results
    published: bool = Field(default=False, description="Whether review was published to GitHub")
    github_review_id: Optional[int] = Field(
        None,
        description="GitHub review ID if published",
        gt=0
    )

    # Statistics
    total_findings: Optional[int] = Field(
        None,
        description="Total number of findings generated",
        ge=0
    )
    anchored_findings: Optional[int] = Field(
        None,
        description="Number of findings anchored to diff positions",
        ge=0
    )
    processing_duration_ms: Optional[int] = Field(
        None,
        description="Total processing time in milliseconds",
        ge=0
    )

    # Error information
    error_message: Optional[str] = Field(None, description="Error message if workflow failed")
    error_stage: Optional[str] = Field(None, description="Stage where error occurred")

    # Timestamps
    completed_at: datetime = Field(..., description="Workflow completion timestamp")

    @validator('anchored_findings')
    def validate_anchored_findings(cls, v, values):
        """Ensure anchored findings don't exceed total findings."""
        if v is not None and 'total_findings' in values:
            total = values['total_findings']
            if total is not None and v > total:
                raise ValueError('Anchored findings cannot exceed total findings')
        return v

    class Config:
        schema_extra = {
            "example": {
                "status": "completed",
                "review_run_id": "123e4567-e89b-12d3-a456-426614174000",
                "pr_number": 123,
                "head_sha": "abc123def456789012345678901234567890abcd",
                "published": True,
                "github_review_id": 98765,
                "total_findings": 5,
                "anchored_findings": 4,
                "processing_duration_ms": 45000,
                "completed_at": "2026-01-15T10:30:00Z"
            }
        }