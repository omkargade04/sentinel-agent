"""
Context Pack Models

Contains Pydantic schemas for the bounded context assembly used in LLM analysis.
The context pack includes all relevant information for generating code reviews.
"""

from uuid import UUID
from pydantic import BaseModel, Field, validator, computed_field, model_validator
from typing import List, Optional, Dict, Any, Literal
from enum import Enum
from .seed_set import SeedSetS0
from .pr_patch import PRFilePatch


class ContextSource(str, Enum):
    """Source of context data."""
    OVERLAY = "overlay"      # From PR head clone (authoritative)
    CANONICAL = "canonical"  # From Neo4j knowledge graph


class ContextItemType(str, Enum):
    """Types of context items."""
    CHANGED_SYMBOL = "changed_symbol"      # Symbol that was modified in PR
    NEIGHBOR_SYMBOL = "neighbor_symbol"    # Related symbol via relationships
    FILE_CONTEXT = "file_context"          # File-level context
    DOC_CONTEXT = "doc_context"            # Documentation context
    IMPORT_FILE = "import_file"            # Imported/dependency file context
    TEST_FILE = "test_file"                # Test file context


class ContextItem(BaseModel):
    """Single item in the context pack for LLM analysis."""

    item_id: str = Field(..., description="Unique identifier for this context item")
    source: ContextSource = Field(..., description="Data source (overlay or canonical)")
    item_type: ContextItemType = Field(..., description="Type of context item")

    # Location information
    file_path: str = Field(..., description="File path relative to repository root")
    start_line: Optional[int] = Field(None, description="Starting line number (1-based)", ge=1)
    end_line: Optional[int] = Field(None, description="Ending line number (1-based)", ge=1)

    # Content
    title: str = Field(..., description="Human-readable title for this context item")
    snippet: str = Field(..., description="Code or text content")

    # Relevance and priority
    relevance_score: float = Field(
        ...,
        description="Relevance score to the PR changes",
        ge=0.0,
        le=1.0
    )
    priority: int = Field(
        ...,
        description="Priority bucket (1=highest priority)",
        ge=1
    )

    # Processing metadata
    truncated: bool = Field(
        default=False,
        description="Whether content was truncated due to size limits"
    )
    original_size: Optional[int] = Field(
        None,
        description="Original size in characters before truncation",
        ge=0
    )

    # Provenance (for debugging and traceability)
    provenance: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata about how this context was obtained"
    )

    @validator('end_line')
    def validate_line_range(cls, v, values):
        """Ensure end_line >= start_line when both are provided."""
        start_line = values.get('start_line')
        if start_line is not None and v is not None and v < start_line:
            raise ValueError('end_line must be >= start_line')
        return v

    @validator('file_path')
    def validate_file_path(cls, v):
        """Normalize file path."""
        if not v.strip():
            raise ValueError('File path cannot be empty')
        return v.strip().replace('\\', '/').strip('/')

    @validator('snippet')
    def validate_snippet_not_empty(cls, v):
        """Ensure snippet is not empty."""
        if not v.strip():
            raise ValueError('Snippet cannot be empty')
        return v

    @validator('title')
    def validate_title_not_empty(cls, v):
        """Ensure title is not empty."""
        if not v.strip():
            raise ValueError('Title cannot be empty')
        return v.strip()

    @computed_field
    @property
    def line_span(self) -> Optional[int]:
        """Number of lines this context item spans."""
        if self.start_line is not None and self.end_line is not None:
            return self.end_line - self.start_line + 1
        return None

    @computed_field
    @property
    def character_count(self) -> int:
        """Number of characters in the snippet."""
        return len(self.snippet)

    @computed_field
    @property
    def is_high_priority(self) -> bool:
        """Whether this is a high priority context item."""
        return self.priority <= 2

    class Config:
        use_enum_values = True
        schema_extra = {
            "example": {
                "item_id": "ctx_changed_calculate_sum_func",
                "source": "overlay",
                "item_type": "changed_symbol",
                "file_path": "src/utils.py",
                "start_line": 15,
                "end_line": 25,
                "title": "Function: calculate_sum (modified)",
                "snippet": "def calculate_sum(a: int, b: int) -> int:\n    \"\"\"Add two numbers.\"\"\"\n    return a + b",
                "relevance_score": 1.0,
                "priority": 1,
                "truncated": False,
                "provenance": {
                    "extraction_method": "ast_overlay",
                    "seed_symbol_id": "seed_calculate_sum"
                }
            }
        }


class ContextPackLimits(BaseModel):
    """Hard limits applied during context assembly."""

    max_context_items: int = Field(35, description="Maximum number of context items", ge=1)
    max_total_characters: int = Field(120_000, description="Maximum total character count", ge=1000)
    max_lines_per_snippet: int = Field(120, description="Maximum lines per code snippet", ge=1)
    max_chars_per_item: int = Field(2000, description="Maximum characters per context item", ge=100)
    max_hops: int = Field(1, description="Maximum relationship traversal hops", ge=0)
    max_neighbors_per_seed: int = Field(8, description="Maximum neighbors per seed symbol", ge=1)

    class Config:
        schema_extra = {
            "example": {
                "max_context_items": 35,
                "max_total_characters": 120000,
                "max_lines_per_snippet": 120,
                "max_chars_per_item": 2000,
                "max_hops": 1,
                "max_neighbors_per_seed": 8
            }
        }


class ContextPackStats(BaseModel):
    """Statistics about context pack assembly."""

    total_items: int = Field(..., description="Total context items included", ge=0)
    total_characters: int = Field(..., description="Total character count", ge=0)
    items_by_type: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of items by type"
    )
    items_by_source: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of items by source"
    )
    items_truncated: int = Field(
        default=0,
        description="Number of items that were truncated",
        ge=0
    )
    kg_symbols_found: int = Field(
        default=0,
        description="Number of seed symbols found in knowledge graph",
        ge=0
    )
    kg_symbols_missing: int = Field(
        default=0,
        description="Number of seed symbols not found in knowledge graph",
        ge=0
    )

    @computed_field
    @property
    def truncation_rate(self) -> float:
        """Percentage of items that were truncated."""
        if self.total_items == 0:
            return 0.0
        return (self.items_truncated / self.total_items) * 100.0

    @computed_field
    @property
    def kg_coverage_rate(self) -> float:
        """Percentage of seed symbols found in knowledge graph."""
        total_symbols = self.kg_symbols_found + self.kg_symbols_missing
        if total_symbols == 0:
            return 0.0
        return (self.kg_symbols_found / total_symbols) * 100.0

    class Config:
        schema_extra = {
            "example": {
                "total_items": 28,
                "total_characters": 95000,
                "items_by_type": {
                    "changed_symbol": 12,
                    "neighbor_symbol": 15,
                    "doc_context": 1
                },
                "items_by_source": {
                    "overlay": 12,
                    "canonical": 16
                },
                "items_truncated": 2,
                "kg_symbols_found": 10,
                "kg_symbols_missing": 2
            }
        }


class ContextPack(BaseModel):
    """Bounded context pack for LLM analysis."""

    # Metadata
    repo_id: UUID = Field(..., description="Repository UUID")
    github_repo_name: str = Field(..., description="Repository name in owner/repo format")
    pr_number: int = Field(..., description="Pull request number", ge=1)
    head_sha: str = Field(
        ...,
        description="PR head commit SHA (authoritative)",
        min_length=40,
        max_length=40
    )
    base_sha: str = Field(
        ...,
        description="PR base commit SHA",
        min_length=40,
        max_length=40
    )
    kg_commit_sha: Optional[str] = Field(
        None,
        description="Commit SHA that knowledge graph was built from"
    )

    # Core data
    patches: List[PRFilePatch] = Field(..., description="PR file patches")
    seed_set: SeedSetS0 = Field(..., description="Seed symbols and files from PR analysis")
    context_items: List[ContextItem] = Field(
        ...,
        description="Assembled context items for LLM analysis"
    )

    # Resource usage and limits
    limits: ContextPackLimits = Field(..., description="Hard limits that were applied")
    stats: ContextPackStats = Field(..., description="Assembly statistics")

    # Assembly metadata
    assembly_timestamp: str = Field(..., description="When context was assembled")
    assembly_duration_ms: Optional[int] = Field(
        None,
        description="Time taken to assemble context in milliseconds",
        ge=0
    )

    @validator('context_items')
    def validate_unique_item_ids(cls, v):
        """Ensure all context item IDs are unique."""
        item_ids = [item.item_id for item in v]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError('Context item IDs must be unique')
        return v

    @model_validator(mode='after')
    def validate_context_items_limits(self):
        """Validate that context items respect hard limits (runs after all fields set)."""
        context_items = self.context_items
        limits = self.limits

        if limits and context_items:
            if len(context_items) > limits.max_context_items:
                raise ValueError(f'Too many context items: {len(context_items)} > {limits.max_context_items}')

            total_chars = sum(item.character_count for item in context_items)
            if total_chars > limits.max_total_characters:
                raise ValueError(f'Context too large: {total_chars} chars > {limits.max_total_characters}')

        return self

    @computed_field
    @property
    def total_context_characters(self) -> int:
        """Total character count of all context items."""
        return sum(item.character_count for item in self.context_items)

    @computed_field
    @property
    def context_types(self) -> Dict[str, int]:
        """Count of context items by type."""
        type_counts = {}
        for item in self.context_items:
            type_counts[item.item_type] = type_counts.get(item.item_type, 0) + 1
        return type_counts

    @computed_field
    @property
    def has_kg_commit_drift(self) -> bool:
        """Whether knowledge graph commit differs from PR head."""
        return self.kg_commit_sha is not None and self.kg_commit_sha != self.head_sha

    def get_items_by_type(self, item_type: ContextItemType) -> List[ContextItem]:
        """Get all context items of a specific type."""
        return [item for item in self.context_items if item.item_type == item_type]

    def get_items_by_source(self, source: ContextSource) -> List[ContextItem]:
        """Get all context items from a specific source."""
        return [item for item in self.context_items if item.source == source]

    def get_high_priority_items(self) -> List[ContextItem]:
        """Get high priority context items (priority <= 2)."""
        return [item for item in self.context_items if item.is_high_priority]

    class Config:
        use_enum_values = True
        schema_extra = {
            "example": {
                "repo_id": "123e4567-e89b-12d3-a456-426614174000",
                "github_repo_name": "owner/repository",
                "pr_number": 123,
                "head_sha": "abc123def456789012345678901234567890abcd",
                "base_sha": "def456abc123789012345678901234567890bcda",
                "kg_commit_sha": "abc123def456789012345678901234567890abcd",
                "patches": [],
                "seed_set": {
                    "seed_symbols": [],
                    "seed_files": []
                },
                "context_items": [],
                "limits": {
                    "max_context_items": 35,
                    "max_total_characters": 120000
                },
                "stats": {
                    "total_items": 28,
                    "total_characters": 95000,
                    "items_by_type": {},
                    "items_by_source": {}
                },
                "assembly_timestamp": "2026-01-15T10:35:00Z",
                "assembly_duration_ms": 5000
            }
        }