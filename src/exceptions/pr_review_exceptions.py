"""
PR Review Pipeline Specific Exceptions

Custom exceptions for the PR review pipeline components.
"""

from src.utils.exception import AppException, BadRequestException, NotFoundException, RepoCloneError
from fastapi import status


# ============================================================================
# BASE PR REVIEW EXCEPTIONS
# ============================================================================

class PRReviewException(AppException):
    """Base exception for PR review pipeline errors."""
    def __init__(self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        super().__init__(status_code=status_code, message=message)


# ============================================================================
# GITHUB API EXCEPTIONS
# ============================================================================

class GitHubAPIException(PRReviewException):
    """Base exception for GitHub API related errors."""
    def __init__(self, message: str, status_code: int = status.HTTP_502_BAD_GATEWAY):
        super().__init__(message=message, status_code=status_code)


class GitHubPRNotFoundException(GitHubAPIException):
    """Raised when a Pull Request is not found on GitHub."""
    def __init__(self, repo_name: str, pr_number: int):
        message = f"Pull request #{pr_number} not found in repository {repo_name}"
        super().__init__(message=message, status_code=status.HTTP_404_NOT_FOUND)


class GitHubRateLimitException(GitHubAPIException):
    """Raised when GitHub API rate limit is exceeded."""
    def __init__(self, retry_after_seconds: int = None):
        message = "GitHub API rate limit exceeded"
        if retry_after_seconds:
            message += f". Retry after {retry_after_seconds} seconds"
        super().__init__(message=message, status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        self.retry_after_seconds = retry_after_seconds


class GitHubAuthenticationException(GitHubAPIException):
    """Raised when GitHub API authentication fails."""
    def __init__(self, installation_id: int = None):
        message = "GitHub API authentication failed"
        if installation_id:
            message += f" for installation {installation_id}"
        super().__init__(message=message, status_code=status.HTTP_401_UNAUTHORIZED)


class GitHubPermissionException(GitHubAPIException):
    """Raised when GitHub API operation is not permitted."""
    def __init__(self, message: str = "Insufficient permissions for GitHub operation"):
        super().__init__(message=message, status_code=status.HTTP_403_FORBIDDEN)


# ============================================================================
# PR PROCESSING EXCEPTIONS
# ============================================================================

class PRTooLargeException(PRReviewException):
    """Raised when a PR exceeds size limits."""
    def __init__(self, files_changed: int, max_files: int):
        message = f"PR has {files_changed} changed files, exceeding limit of {max_files}"
        super().__init__(message=message, status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)


class InvalidDiffFormatException(PRReviewException):
    """Raised when diff format is invalid or cannot be parsed."""
    def __init__(self, message: str = "Invalid or unparseable diff format"):
        super().__init__(message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


class PRHunkParsingException(InvalidDiffFormatException):
    """Raised when specific hunk cannot be parsed."""
    def __init__(self, file_path: str, hunk_header: str):
        message = f"Failed to parse hunk in {file_path}: {hunk_header}"
        super().__init__(message=message)


class BinaryFileException(PRReviewException):
    """Raised when encountering binary files that cannot be processed."""
    def __init__(self, file_path: str):
        message = f"Binary file cannot be processed: {file_path}"
        super().__init__(message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


# ============================================================================
# CLONE SPECIFIC EXCEPTIONS
# ============================================================================

class PRCloneException(RepoCloneError):
    """Base exception for PR-specific cloning errors."""
    pass


class CloneTimeoutException(PRCloneException):
    """Raised when repository cloning times out."""
    def __init__(self, repo_name: str, timeout_seconds: int):
        message = f"Repository clone timed out after {timeout_seconds}s: {repo_name}"
        super().__init__(message)


class ClonePermissionException(PRCloneException):
    """Raised when clone operation lacks required permissions."""
    def __init__(self, repo_name: str, installation_id: int):
        message = f"Insufficient permissions to clone {repo_name} with installation {installation_id}"
        super().__init__(message)


class SHAValidationException(PRCloneException):
    """Raised when cloned repository SHA doesn't match expected SHA."""
    def __init__(self, expected_sha: str, actual_sha: str):
        message = f"Clone SHA mismatch: expected {expected_sha}, got {actual_sha}"
        super().__init__(message)


class CloneResourceExhaustedException(PRCloneException):
    """Raised when clone operation exceeds resource limits."""
    def __init__(self, resource_type: str, limit: str):
        message = f"Clone operation exceeded {resource_type} limit: {limit}"
        super().__init__(message)


# ============================================================================
# AST EXTRACTION EXCEPTIONS (for Phase 3)
# ============================================================================

class ASTExtractionException(PRReviewException):
    """Base exception for AST analysis errors."""
    def __init__(self, message: str):
        super().__init__(message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


class UnsupportedLanguageException(ASTExtractionException):
    """Raised when file language is not supported for AST analysis."""
    def __init__(self, file_path: str, language: str = None):
        message = f"Unsupported language for AST analysis: {file_path}"
        if language:
            message += f" (detected: {language})"
        super().__init__(message=message)


class SymbolExtractionException(ASTExtractionException):
    """Raised when symbol extraction fails."""
    def __init__(self, file_path: str, error_detail: str):
        message = f"Failed to extract symbols from {file_path}: {error_detail}"
        super().__init__(message=message)


# ============================================================================
# LANGGRAPH EXECUTION EXCEPTIONS (for Phases 5-6)
# ============================================================================

class LangGraphExecutionException(PRReviewException):
    """Base exception for LangGraph workflow execution errors."""
    def __init__(self, workflow_type: str, message: str):
        full_message = f"LangGraph {workflow_type} execution failed: {message}"
        super().__init__(message=full_message)


class ContextAssemblyException(LangGraphExecutionException):
    """Raised when context assembly workflow fails."""
    def __init__(self, message: str):
        super().__init__(workflow_type="context assembly", message=message)


class ReviewGenerationException(LangGraphExecutionException):
    """Raised when review generation workflow fails."""
    def __init__(self, message: str):
        super().__init__(workflow_type="review generation", message=message)


# ============================================================================
# REVIEW VALIDATION EXCEPTIONS
# ============================================================================

class ReviewValidationException(PRReviewException):
    """Base exception for review validation errors."""
    def __init__(self, message: str):
        super().__init__(message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


class ReviewSchemaException(ReviewValidationException):
    """Raised when review output doesn't match expected schema."""
    def __init__(self, validation_errors: list):
        message = f"Review output validation failed: {', '.join(str(e) for e in validation_errors)}"
        super().__init__(message=message)


class ReviewConfidenceException(ReviewValidationException):
    """Raised when review confidence scores are invalid."""
    def __init__(self, finding_id: str, confidence: float):
        message = f"Invalid confidence score for finding {finding_id}: {confidence}"
        super().__init__(message=message)


# ============================================================================
# PUBLISHING EXCEPTIONS
# ============================================================================

class ReviewPublishingException(PRReviewException):
    """Base exception for review publishing errors."""
    def __init__(self, message: str):
        super().__init__(message=message)


class DiffPositionCalculationException(ReviewPublishingException):
    """Raised when diff position calculation fails."""
    def __init__(self, finding_id: str, file_path: str, hunk_id: str):
        message = f"Failed to calculate diff position for finding {finding_id} in {file_path} hunk {hunk_id}"
        super().__init__(message=message)


class ReviewAnchoringException(ReviewPublishingException):
    """Raised when review findings cannot be anchored to diff positions."""
    def __init__(self, anchored_count: int, total_count: int):
        message = f"Only {anchored_count}/{total_count} findings could be anchored to diff positions"
        super().__init__(message=message)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def is_retryable_github_error(exception: Exception) -> bool:
    """
    Determine if a GitHub API error should be retried.

    Returns True for transient errors (rate limits, server errors),
    False for permanent errors (not found, permission denied).
    """
    if isinstance(exception, GitHubRateLimitException):
        return True

    if isinstance(exception, GitHubAPIException):
        # Retry server errors (5xx), don't retry client errors (4xx)
        return exception.status_code >= 500

    if isinstance(exception, PRCloneException):
        # Retry timeouts and resource exhaustion, not permissions
        return isinstance(exception, (CloneTimeoutException, CloneResourceExhaustedException))

    return False


def get_retry_delay_seconds(exception: Exception) -> int:
    """
    Get appropriate retry delay for an exception.

    Returns delay in seconds, or 0 if no specific delay recommended.
    """
    if isinstance(exception, GitHubRateLimitException):
        return exception.retry_after_seconds or 60

    if isinstance(exception, GitHubAPIException):
        # Exponential backoff base for server errors
        return 5

    if isinstance(exception, CloneTimeoutException):
        return 30

    return 0