"""
Review Generation Exception Hierarchy

Comprehensive exception handling for the review generation system with
detailed error categorization and recovery guidance.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime


class ReviewGenerationError(Exception):
    """Base exception for all review generation errors."""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = False
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}
        self.recoverable = recoverable
        self.timestamp = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/serialization."""
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
            "recoverable": self.recoverable,
            "timestamp": self.timestamp.isoformat()
        }

    def __str__(self) -> str:
        return f"{self.error_code}: {self.message}"


# ============================================================================
# LLM GENERATION ERRORS
# ============================================================================

class LLMGenerationError(ReviewGenerationError):
    """Raised when LLM review generation fails."""

    def __init__(
        self,
        message: str,
        provider: str = "unknown",
        model: Optional[str] = None,
        prompt_tokens: int = 0,
        cause: Optional[Exception] = None
    ):
        super().__init__(
            message=message,
            error_code="LLM_GENERATION_ERROR",
            details={
                "provider": provider,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "cause": str(cause) if cause else None
            },
            recoverable=True  # LLM failures can often be retried
        )
        self.__cause__ = cause


class LLMResponseParseError(LLMGenerationError):
    """Raised when LLM response cannot be parsed as valid JSON."""

    def __init__(
        self,
        message: str,
        raw_response: Optional[str] = None,
        parse_error: Optional[str] = None
    ):
        super().__init__(
            message=message,
            provider="unknown",
        )
        self.error_code = "LLM_RESPONSE_PARSE_ERROR"
        self.details.update({
            "raw_response_length": len(raw_response) if raw_response else 0,
            "parse_error": parse_error
        })
        self.recoverable = True  # Can retry with different prompt


class LLMTimeoutError(LLMGenerationError):
    """Raised when LLM API request times out."""

    def __init__(
        self,
        message: str,
        timeout_seconds: float = 0.0,
        provider: str = "unknown"
    ):
        super().__init__(
            message=message,
            provider=provider,
        )
        self.error_code = "LLM_TIMEOUT_ERROR"
        self.details.update({
            "timeout_seconds": timeout_seconds
        })
        self.recoverable = True


class LLMRateLimitError(LLMGenerationError):
    """Raised when LLM API rate limit is exceeded."""

    def __init__(
        self,
        message: str,
        provider: str = "unknown",
        retry_after_seconds: Optional[int] = None
    ):
        super().__init__(
            message=message,
            provider=provider,
        )
        self.error_code = "LLM_RATE_LIMIT_ERROR"
        self.details.update({
            "retry_after_seconds": retry_after_seconds
        })
        self.recoverable = True


# ============================================================================
# ANCHORING ERRORS
# ============================================================================

class AnchoringError(ReviewGenerationError):
    """Base class for diff anchoring errors."""

    def __init__(
        self,
        message: str,
        file_path: Optional[str] = None,
        hunk_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        base_details = {
            "file_path": file_path,
            "hunk_id": hunk_id
        }
        if details:
            base_details.update(details)
        super().__init__(
            message=message,
            error_code="ANCHORING_ERROR",
            details=base_details,
            recoverable=True  # Can fallback to unanchored finding
        )


class InvalidAnchorError(AnchoringError):
    """Raised when an anchor position is invalid."""

    def __init__(
        self,
        message: str,
        file_path: str,
        hunk_id: Optional[str] = None,
        line_in_hunk: Optional[int] = None,
        reason: str = "unknown"
    ):
        super().__init__(
            message=message,
            file_path=file_path,
            hunk_id=hunk_id,
            details={
                "line_in_hunk": line_in_hunk,
                "reason": reason
            }
        )
        self.error_code = "INVALID_ANCHOR_ERROR"


class HunkNotFoundError(AnchoringError):
    """Raised when a referenced hunk cannot be found."""

    def __init__(
        self,
        message: str,
        file_path: str,
        hunk_id: str,
        available_hunks: Optional[List[str]] = None
    ):
        super().__init__(
            message=message,
            file_path=file_path,
            hunk_id=hunk_id,
            details={
                "available_hunks": available_hunks or []
            }
        )
        self.error_code = "HUNK_NOT_FOUND_ERROR"


class LineOutOfBoundsError(AnchoringError):
    """Raised when line_in_hunk is outside valid range."""

    def __init__(
        self,
        message: str,
        file_path: str,
        hunk_id: str,
        line_in_hunk: int,
        hunk_line_count: int
    ):
        super().__init__(
            message=message,
            file_path=file_path,
            hunk_id=hunk_id,
            details={
                "line_in_hunk": line_in_hunk,
                "hunk_line_count": hunk_line_count,
                "valid_range": f"0-{hunk_line_count - 1}"
            }
        )
        self.error_code = "LINE_OUT_OF_BOUNDS_ERROR"


# ============================================================================
# PROMPT BUILDING ERRORS
# ============================================================================

class PromptBuildError(ReviewGenerationError):
    """Raised when prompt construction fails."""

    def __init__(
        self,
        message: str,
        stage: str = "unknown",
        context_items_count: int = 0,
        cause: Optional[Exception] = None
    ):
        super().__init__(
            message=message,
            error_code="PROMPT_BUILD_ERROR",
            details={
                "stage": stage,
                "context_items_count": context_items_count,
                "cause": str(cause) if cause else None
            },
            recoverable=False  # Usually indicates a configuration issue
        )
        self.__cause__ = cause


class TokenLimitExceededError(PromptBuildError):
    """Raised when prompt exceeds token limits."""

    def __init__(
        self,
        message: str,
        token_count: int,
        token_limit: int,
        truncation_applied: bool = False
    ):
        super().__init__(
            message=message,
            stage="token_validation"
        )
        self.error_code = "TOKEN_LIMIT_EXCEEDED"
        self.details.update({
            "token_count": token_count,
            "token_limit": token_limit,
            "truncation_applied": truncation_applied,
            "overflow": token_count - token_limit
        })
        self.recoverable = True  # Can truncate and retry


# ============================================================================
# DIFF PROCESSING ERRORS
# ============================================================================

class DiffProcessingError(ReviewGenerationError):
    """Raised when diff processing fails."""

    def __init__(
        self,
        message: str,
        file_path: Optional[str] = None,
        operation: str = "parse",
        cause: Optional[Exception] = None
    ):
        super().__init__(
            message=message,
            error_code="DIFF_PROCESSING_ERROR",
            details={
                "file_path": file_path,
                "operation": operation,
                "cause": str(cause) if cause else None
            },
            recoverable=True
        )
        self.__cause__ = cause


class InvalidDiffFormatError(DiffProcessingError):
    """Raised when diff data has invalid format."""

    def __init__(
        self,
        message: str,
        file_path: Optional[str] = None,
        expected_format: str = "unified diff"
    ):
        super().__init__(
            message=message,
            file_path=file_path,
            operation="format_validation"
        )
        self.error_code = "INVALID_DIFF_FORMAT"
        self.details.update({
            "expected_format": expected_format
        })


# ============================================================================
# QUALITY VALIDATION ERRORS
# ============================================================================

class QualityValidationError(ReviewGenerationError):
    """Raised when quality validation fails."""

    def __init__(
        self,
        message: str,
        validation_type: str = "unknown",
        findings_affected: int = 0,
        validation_errors: Optional[List[str]] = None
    ):
        super().__init__(
            message=message,
            error_code="QUALITY_VALIDATION_ERROR",
            details={
                "validation_type": validation_type,
                "findings_affected": findings_affected,
                "validation_errors": validation_errors or []
            },
            recoverable=True  # Can filter out invalid findings
        )


class FindingValidationError(QualityValidationError):
    """Raised when a specific finding fails validation."""

    def __init__(
        self,
        message: str,
        finding_index: int,
        field_name: Optional[str] = None,
        field_value: Optional[Any] = None,
        validation_rule: Optional[str] = None
    ):
        super().__init__(
            message=message,
            validation_type="finding_validation",
            findings_affected=1
        )
        self.error_code = "FINDING_VALIDATION_ERROR"
        self.details.update({
            "finding_index": finding_index,
            "field_name": field_name,
            "field_value": str(field_value) if field_value is not None else None,
            "validation_rule": validation_rule
        })


class DuplicateFindingError(QualityValidationError):
    """Raised when duplicate findings are detected."""

    def __init__(
        self,
        message: str,
        duplicate_count: int,
        duplicate_criteria: str = "title_and_file"
    ):
        super().__init__(
            message=message,
            validation_type="deduplication",
            findings_affected=duplicate_count
        )
        self.error_code = "DUPLICATE_FINDING_ERROR"
        self.details.update({
            "duplicate_count": duplicate_count,
            "duplicate_criteria": duplicate_criteria
        })


# ============================================================================
# WORKFLOW ERRORS
# ============================================================================

class WorkflowExecutionError(ReviewGenerationError):
    """Raised when LangGraph workflow execution fails."""

    def __init__(
        self,
        message: str,
        workflow_name: str = "review_generation",
        workflow_id: Optional[str] = None,
        failed_node: Optional[str] = None,
        execution_step: int = 0,
        cause: Optional[Exception] = None
    ):
        super().__init__(
            message=message,
            error_code="WORKFLOW_EXECUTION_ERROR",
            details={
                "workflow_name": workflow_name,
                "workflow_id": workflow_id,
                "failed_node": failed_node,
                "execution_step": execution_step,
                "cause": str(cause) if cause else None
            },
            recoverable=True  # Workflows can be retried
        )
        self.__cause__ = cause


class WorkflowNodeError(ReviewGenerationError):
    """Raised when a workflow node fails."""

    def __init__(
        self,
        message: str,
        node_name: str,
        input_state_keys: Optional[List[str]] = None,
        cause: Optional[Exception] = None
    ):
        super().__init__(
            message=message,
            error_code="WORKFLOW_NODE_ERROR",
            details={
                "node_name": node_name,
                "input_state_keys": input_state_keys or [],
                "cause": str(cause) if cause else None
            },
            recoverable=True
        )
        self.__cause__ = cause


class WorkflowStateError(ReviewGenerationError):
    """Raised when workflow state is invalid or corrupted."""

    def __init__(
        self,
        message: str,
        missing_fields: Optional[List[str]] = None,
        invalid_fields: Optional[List[str]] = None
    ):
        super().__init__(
            message=message,
            error_code="WORKFLOW_STATE_ERROR",
            details={
                "missing_fields": missing_fields or [],
                "invalid_fields": invalid_fields or []
            },
            recoverable=False  # State corruption is typically not recoverable
        )