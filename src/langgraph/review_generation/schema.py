"""
Review Generation Internal Schemas

Internal data models for the review generation workflow.
These schemas are used for inter-node communication and are NOT part of the public API.

Public output uses: src/models/schemas/pr_review/review_output.py
"""

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum
from datetime import datetime


# ============================================================================
# ENUMS (aligned with public schema)
# ============================================================================

class RawSeverity(str, Enum):
    """Internal severity enum for LLM output parsing."""
    BLOCKER = "blocker"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NIT = "nit"


class RawCategory(str, Enum):
    """Internal category enum for LLM output parsing."""
    BUG = "bug"
    SECURITY = "security"
    PERFORMANCE = "performance"
    STYLE = "style"
    DESIGN = "design"
    DOCS = "docs"
    OBSERVABILITY = "observability"
    MAINTAINABILITY = "maintainability"


# ============================================================================
# EVIDENCE MODELS (internal only - not in public schema)
# ============================================================================

class EvidenceCitation(BaseModel):
    """Citation evidence for grounding findings to context."""
    
    context_item_id: Optional[str] = Field(
        None,
        description="ID of the context item this finding references"
    )
    snippet_line_range: List[int] = Field(
        default_factory=list,
        description="Line range within the snippet [start, end] (0-based relative)",
        max_items=2
    )
    quote: Optional[str] = Field(
        None,
        description="Direct quote from the code supporting this finding",
        max_length=500
    )
    
    @validator('snippet_line_range')
    def validate_line_range(cls, v):
        """Ensure line range is valid [start, end] pair."""
        if v and len(v) == 2:
            if v[0] > v[1]:
                raise ValueError(f"Invalid line range: start ({v[0]}) > end ({v[1]})")
        return v


# ============================================================================
# RAW LLM OUTPUT MODELS (internal - before anchoring)
# ============================================================================

class RawLLMFinding(BaseModel):
    """
    Internal finding model from LLM output.
    
    This includes evidence fields used for anchoring that are NOT part of 
    the public Finding schema. These fields are consumed during anchoring
    and stripped when mapping to the public schema.
    """
    
    # Core fields (map to public Finding)
    title: str = Field(..., description="Concise finding title", max_length=255)
    message: str = Field(..., description="Detailed explanation of the issue")
    severity: RawSeverity = Field(..., description="Severity level")
    category: RawCategory = Field(..., description="Finding category")
    file_path: str = Field(..., description="File path where finding applies")
    suggested_fix: str = Field(..., description="Actionable fix suggestion")
    confidence: float = Field(
        ...,
        description="Confidence score (0.0-1.0)",
        ge=0.0,
        le=1.0
    )
    
    # Evidence fields (internal only - used for anchoring)
    evidence: Optional[EvidenceCitation] = Field(
        None,
        description="Evidence citation for grounding (internal use)"
    )
    
    # Hint fields from LLM (treated as suggestions, not authoritative - validated during anchoring)
    hunk_id: Optional[str] = Field(
        None,
        description="LLM's suggested hunk_id (may be invalid, validated during anchoring)"
    )
    line_hint: Optional[int] = Field(
        None,
        description="LLM's suggested line number (may be invalid, validated during anchoring)"
    )
    
    # Additional context (carried to public schema)
    related_symbols: List[str] = Field(
        default_factory=list,
        description="Symbol names related to this finding",
        max_items=10
    )
    code_examples: List[str] = Field(
        default_factory=list,
        description="Code snippets referenced in the finding",
        max_items=3
    )
    
    @validator('title')
    def validate_title_not_empty(cls, v):
        title = v.strip()
        if not title:
            raise ValueError('Finding title cannot be empty')
        return title
    
    @validator('file_path')
    def normalize_file_path(cls, v):
        if not v.strip():
            raise ValueError('File path cannot be empty')
        return v.strip().replace('\\', '/').strip('/')
    
    class Config:
        use_enum_values = True


class RawLLMReviewOutput(BaseModel):
    """
    Internal LLM output model before post-processing.
    
    Note: Does NOT include finding_id, total counts, or timestamps.
    Those are system-computed fields added during quality validation.
    """
    
    findings: List[RawLLMFinding] = Field(
        default_factory=list,
        description="Raw findings from LLM (before validation/filtering)"
    )
    summary: str = Field(
        ...,
        description="Overall review summary from LLM"
    )
    patterns: List[str] = Field(
        default_factory=list,
        description="Repository-wide patterns observed",
        max_items=5
    )
    recommendations: List[str] = Field(
        default_factory=list,
        description="General recommendations",
        max_items=3
    )
    
    @validator('summary')
    def validate_summary_not_empty(cls, v):
        summary = v.strip()
        if not summary:
            raise ValueError('Review summary cannot be empty')
        return summary


# ============================================================================
# CONTEXT ANALYSIS MODELS
# ============================================================================

class TechnicalInsight(BaseModel):
    """Technical insight extracted from context analysis."""
    
    insight_type: str = Field(..., description="Type of insight (framework, pattern, etc.)")
    name: str = Field(..., description="Name of the insight")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    files: List[str] = Field(default_factory=list, description="Files where this was detected")


class ReviewFocusArea(BaseModel):
    """Suggested focus area for review."""
    
    area: str = Field(..., description="Focus area name")
    priority: int = Field(default=1, ge=1, le=5, description="Priority 1-5 (1 highest)")
    reason: str = Field(..., description="Why this area should be focused on")
    file_paths: List[str] = Field(default_factory=list)


class AnalyzedContext(BaseModel):
    """
    Output from ContextAnalyzer node.
    
    Contains technical metadata and insights extracted from the ContextPack
    to guide prompt construction and review focus.
    """
    
    # Technical metadata
    frameworks_detected: List[TechnicalInsight] = Field(
        default_factory=list,
        description="Frameworks/libraries detected in the code"
    )
    patterns_detected: List[TechnicalInsight] = Field(
        default_factory=list,
        description="Code patterns detected (e.g., async/await, decorators)"
    )
    languages: Dict[str, int] = Field(
        default_factory=dict,
        description="Language -> file count mapping"
    )
    
    # Context classification
    seed_symbol_count: int = Field(default=0, description="Count of seed symbols in context")
    related_symbol_count: int = Field(default=0, description="Count of related/neighbor symbols")
    test_file_count: int = Field(default=0, description="Count of test files in context")
    
    # Review focus
    focus_areas: List[ReviewFocusArea] = Field(
        default_factory=list,
        description="Suggested areas to focus review on",
        max_items=5
    )
    
    # Complexity indicators
    total_context_chars: int = Field(default=0, description="Total characters in context")
    total_context_items: int = Field(default=0, description="Total context items")
    estimated_complexity: str = Field(
        default="medium",
        description="Estimated review complexity (low/medium/high)"
    )
    
    # Technical summary for prompt
    technical_summary: str = Field(
        default="",
        description="Human-readable technical summary for LLM prompt"
    )


# ============================================================================
# DIFF MAPPING MODELS
# ============================================================================

class HunkMapping(BaseModel):
    """Mapping information for a single diff hunk."""
    
    hunk_id: str = Field(..., description="Unique hunk identifier")
    file_path: str = Field(..., description="File path this hunk belongs to")
    
    # Line mappings
    old_start: int = Field(..., description="Start line in old file")
    old_count: int = Field(..., description="Number of lines in old file")
    new_start: int = Field(..., description="Start line in new file")
    new_count: int = Field(..., description="Number of lines in new file")
    
    # Hunk content
    lines: List[str] = Field(default_factory=list, description="Hunk lines with +/- prefix")
    line_count: int = Field(default=0, description="Total lines in hunk")
    
    # Changed line indexes (0-based into lines array)
    added_line_indexes: List[int] = Field(
        default_factory=list,
        description="Indexes of added lines (+ prefix) in lines array"
    )
    removed_line_indexes: List[int] = Field(
        default_factory=list,
        description="Indexes of removed lines (- prefix) in lines array"
    )
    
    @validator('line_count', always=True)
    def compute_line_count(cls, v, values):
        if 'lines' in values:
            return len(values['lines'])
        return v


class FileDiffMapping(BaseModel):
    """Diff mapping for a single file."""
    
    file_path: str = Field(..., description="File path")
    hunks: List[HunkMapping] = Field(default_factory=list, description="Hunks in this file")
    hunk_ids: List[str] = Field(default_factory=list, description="List of hunk IDs for quick lookup")
    
    # Convenience lookups
    total_additions: int = Field(default=0, description="Total added lines")
    total_deletions: int = Field(default=0, description="Total deleted lines")
    
    def get_hunk(self, hunk_id: str) -> Optional[HunkMapping]:
        """Get hunk by ID."""
        for hunk in self.hunks:
            if hunk.hunk_id == hunk_id:
                return hunk
        return None


class DiffMappings(BaseModel):
    """
    Output from DiffProcessor node.
    
    Contains lookup structures for deterministic diff anchoring.
    """
    
    # File -> Hunk mappings
    file_mappings: Dict[str, FileDiffMapping] = Field(
        default_factory=dict,
        description="file_path -> FileDiffMapping"
    )
    
    # Quick lookups
    all_file_paths: List[str] = Field(
        default_factory=list,
        description="All file paths with changes"
    )
    all_hunk_ids: List[str] = Field(
        default_factory=list,
        description="All hunk IDs across all files"
    )
    
    # Allowed anchors for LLM constraints
    allowed_anchors: List[Tuple[str, str]] = Field(
        default_factory=list,
        description="Valid (file_path, hunk_id) pairs for anchoring"
    )
    
    # New line -> (hunk_id, line_in_hunk) reverse lookup
    # Format: file_path -> new_line_number -> (hunk_id, line_index)
    line_to_hunk_lookup: Dict[str, Dict[int, Tuple[str, int]]] = Field(
        default_factory=dict,
        description="Reverse lookup: file_path -> new_line -> (hunk_id, line_in_hunk)"
    )
    
    # Stats
    total_files: int = Field(default=0)
    total_hunks: int = Field(default=0)
    total_changed_lines: int = Field(default=0)
    
    def get_file_mapping(self, file_path: str) -> Optional[FileDiffMapping]:
        """Get file mapping by path."""
        return self.file_mappings.get(file_path)
    
    def get_hunk(self, file_path: str, hunk_id: str) -> Optional[HunkMapping]:
        """Get specific hunk by file path and hunk ID."""
        file_mapping = self.file_mappings.get(file_path)
        if file_mapping:
            return file_mapping.get_hunk(hunk_id)
        return None
    
    def is_valid_anchor(self, file_path: str, hunk_id: str) -> bool:
        """Check if a file_path + hunk_id combination is valid for anchoring."""
        return (file_path, hunk_id) in self.allowed_anchors
    
    def is_valid_line(self, file_path: str, hunk_id: str, line_in_hunk: int) -> bool:
        """Check if line_in_hunk is valid (within bounds)."""
        hunk = self.get_hunk(file_path, hunk_id)
        if not hunk:
            return False
        return 0 <= line_in_hunk < hunk.line_count
    
    def get_hunk_for_line(self, file_path: str, new_line: int) -> Optional[Tuple[str, int]]:
        """Get (hunk_id, line_in_hunk) for a given file line number."""
        file_lookup = self.line_to_hunk_lookup.get(file_path, {})
        return file_lookup.get(new_line)


# ============================================================================
# STRUCTURED PROMPT MODEL
# ============================================================================

class StructuredPrompt(BaseModel):
    """
    Output from PromptBuilder node.
    
    Contains the complete prompt structure for LLM review generation,
    with grounding constraints and anti-hallucination measures.
    """
    
    # Core prompt components
    system_prompt: str = Field(
        ...,
        description="System prompt defining the LLM's role and constraints"
    )
    user_prompt: str = Field(
        ...,
        description="User prompt with context, code, and review request"
    )
    
    # Grounding data (extracted for validation/debugging)
    allowed_anchors_count: int = Field(
        default=0,
        description="Number of valid (file_path, hunk_id) anchors"
    )
    context_items_count: int = Field(
        default=0,
        description="Number of context items included in prompt"
    )
    
    # Schema enforcement
    output_schema_json: str = Field(
        ...,
        description="JSON schema string the LLM must conform to"
    )
    
    # Token management
    estimated_prompt_tokens: int = Field(
        default=0,
        description="Estimated token count for the complete prompt"
    )
    estimated_max_completion_tokens: int = Field(
        default=4000,
        description="Recommended max tokens for completion"
    )
    
    # Metadata
    prompt_version: str = Field(
        default="v1.0",
        description="Prompt template version for tracking"
    )
    includes_few_shot: bool = Field(
        default=True,
        description="Whether few-shot examples are included"
    )
    truncation_applied: bool = Field(
        default=False,
        description="Whether context was truncated to fit limits"
    )
    
    # For debugging/logging
    technical_summary: str = Field(
        default="",
        description="Technical summary from AnalyzedContext (for logging)"
    )
    focus_areas: List[str] = Field(
        default_factory=list,
        description="Focus areas identified (for logging)"
    )
    
    def get_full_prompt(self) -> str:
        """Combine system and user prompts for single-prompt LLMs."""
        return f"{self.system_prompt}\n\n{self.user_prompt}"
    
    def get_messages(self) -> List[Dict[str, str]]:
        """Get prompt as message list for chat-based LLMs."""
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.user_prompt}
        ]


class PromptConfig(BaseModel):
    """Configuration for prompt building."""
    
    max_prompt_tokens: int = Field(
        default=100000,
        description="Maximum tokens for entire prompt"
    )
    max_context_chars: int = Field(
        default=80000,
        description="Maximum characters for context section"
    )
    max_items_in_prompt: int = Field(
        default=30,
        description="Maximum context items to include"
    )
    include_few_shot: bool = Field(
        default=True,
        description="Whether to include few-shot examples"
    )
    few_shot_count: int = Field(
        default=2,
        description="Number of few-shot examples to include"
    )
    chars_per_token_estimate: float = Field(
        default=4.0,
        description="Estimated characters per token for token counting"
    )
    
    
# ============================================================================
# ANCHORED FINDING MODEL
# ============================================================================

class AnchoredFinding(BaseModel):
    """
    Finding after deterministic anchoring has been applied.
    
    Contains validated hunk_id and line_in_hunk ready for mapping
    to the public Finding schema.
    """
    
    # Core finding data (from RawLLMFinding)
    title: str
    message: str
    severity: str
    category: str
    file_path: str
    suggested_fix: str
    confidence: float
    related_symbols: List[str] = Field(default_factory=list)
    code_examples: List[str] = Field(default_factory=list)
    
    # Anchoring results (system-computed, validated)
    hunk_id: Optional[str] = Field(None, description="Validated hunk ID")
    line_in_hunk: Optional[int] = Field(None, description="Validated 0-based line index")
    
    # Anchoring metadata
    is_anchored: bool = Field(default=False, description="Whether anchoring succeeded")
    anchoring_method: str = Field(
        default="none",
        description="How anchoring was determined: evidence|hint|fallback|none"
    )
    anchoring_confidence: float = Field(
        default=0.0,
        description="Confidence in the anchoring accuracy"
    )
    
    class Config:
        use_enum_values = True


# ============================================================================
# WORKFLOW STATE MODEL
# ============================================================================

class ReviewGenerationState(BaseModel):
    """
    Complete state passed between workflow nodes.
    
    This is the TypedDict equivalent for LangGraph state management.
    """
    
    # Input data (from Phase 5)
    context_pack: Optional[Dict[str, Any]] = Field(
        None,
        description="Serialized ContextPack from Phase 5"
    )
    pr_patches: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Serialized PRFilePatch list"
    )
    
    # Node outputs (populated as workflow progresses)
    analyzed_context: Optional[AnalyzedContext] = None
    diff_mappings: Optional[DiffMappings] = None
    structured_prompt: Optional[str] = None
    raw_llm_output: Optional[RawLLMReviewOutput] = None
    anchored_findings: List[AnchoredFinding] = Field(default_factory=list)
    unanchored_findings: List[RawLLMFinding] = Field(default_factory=list)
    
    # Final output
    final_output: Optional[Dict[str, Any]] = Field(
        None,
        description="Serialized LLMReviewOutput (public schema)"
    )
    
    # Workflow metadata
    current_node: str = Field(default="start", description="Current/last executed node")
    completed_nodes: List[str] = Field(default_factory=list)
    workflow_start_time: Optional[datetime] = None
    workflow_errors: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Errors encountered during workflow"
    )
    
    # Metrics
    node_durations_ms: Dict[str, int] = Field(
        default_factory=dict,
        description="node_name -> duration in milliseconds"
    )
    llm_token_usage: Dict[str, int] = Field(
        default_factory=dict,
        description="Token usage: prompt_tokens, completion_tokens, total_tokens"
    )
    
    class Config:
        arbitrary_types_allowed = True