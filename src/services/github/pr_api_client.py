"""
GitHub API Client for Pull Request Operations

Specialized client for PR review operations with rate limiting,
retry logic, and proper error handling.
"""

import asyncio
import time
from typing import Dict, Any, List, Optional
import httpx
from dataclasses import dataclass

from src.services.repository.helpers import RepositoryHelpers
from src.exceptions.pr_review_exceptions import (
    GitHubAPIException,
    GitHubPRNotFoundException,
    GitHubRateLimitException,
    GitHubAuthenticationException,
    GitHubPermissionException,
    is_retryable_github_error,
    get_retry_delay_seconds
)
from src.core.pr_review_config import pr_review_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class GitHubAPIRateLimit:
    """Rate limit information from GitHub API headers."""
    limit: int
    remaining: int
    reset_time: int
    used: int

    @classmethod
    def from_headers(cls, headers: dict) -> Optional['GitHubAPIRateLimit']:
        """Create rate limit info from response headers."""
        try:
            return cls(
                limit=int(headers.get('x-ratelimit-limit', 0)),
                remaining=int(headers.get('x-ratelimit-remaining', 0)),
                reset_time=int(headers.get('x-ratelimit-reset', 0)),
                used=int(headers.get('x-ratelimit-used', 0))
            )
        except (ValueError, TypeError):
            return None

    @property
    def seconds_until_reset(self) -> int:
        """Seconds until rate limit resets."""
        return max(0, self.reset_time - int(time.time()))


class PRApiClient:
    """
    GitHub API client specialized for PR review operations.

    Features:
    - GitHub App authentication using installation tokens
    - Automatic rate limiting with backoff
    - Retry logic for transient failures
    - Comprehensive error handling with typed exceptions
    - Request/response logging for debugging
    """

    def __init__(self):
        self.helpers = RepositoryHelpers()
        self.base_url = "https://api.github.com"
        self._rate_limit_info: Optional[GitHubAPIRateLimit] = None

    async def get_pr_details(
        self,
        repo_name: str,
        pr_number: int,
        installation_id: int
    ) -> Dict[str, Any]:
        """
        Get pull request details from GitHub API.

        Args:
            repo_name: Repository name in format "owner/repo"
            pr_number: Pull request number
            installation_id: GitHub installation ID for authentication

        Returns:
            Dictionary with PR metadata including title, author, created_at, etc.

        Raises:
            GitHubPRNotFoundException: If PR doesn't exist
            GitHubAPIException: For other API errors
        """
        endpoint = f"/repos/{repo_name}/pulls/{pr_number}"

        logger.info(f"Fetching PR details for {repo_name}#{pr_number}")

        try:
            response_data = await self._make_api_request(
                method="GET",
                endpoint=endpoint,
                installation_id=installation_id
            )

            logger.info(f"Successfully fetched PR details for {repo_name}#{pr_number}")
            return response_data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise GitHubPRNotFoundException(repo_name, pr_number)
            raise self._handle_http_error(e, f"get PR details for {repo_name}#{pr_number}")

    async def get_pr_files(
        self,
        repo_name: str,
        pr_number: int,
        installation_id: int,
        per_page: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get files changed in a pull request with their diffs.

        Args:
            repo_name: Repository name in format "owner/repo"
            pr_number: Pull request number
            installation_id: GitHub installation ID for authentication
            per_page: Number of files per page (max 300)

        Returns:
            List of file objects with patches, additions, deletions, etc.

        Raises:
            GitHubPRNotFoundException: If PR doesn't exist
            GitHubAPIException: For other API errors
        """
        endpoint = f"/repos/{repo_name}/pulls/{pr_number}/files"
        params = {"per_page": min(per_page, 300)}

        logger.info(f"Fetching PR files for {repo_name}#{pr_number}")

        try:
            # GitHub API paginates files, we need to collect all pages
            all_files = []
            page = 1

            while True:
                params["page"] = page
                response_data = await self._make_api_request(
                    method="GET",
                    endpoint=endpoint,
                    installation_id=installation_id,
                    params=params
                )

                if not response_data:
                    break

                all_files.extend(response_data)

                # Check if we got a full page (more pages might exist)
                if len(response_data) < per_page:
                    break

                page += 1

                # Safety limit to prevent infinite loops
                if page > 100:  # Max 30,000 files (100 * 300)
                    logger.warning(f"Reached pagination limit fetching files for {repo_name}#{pr_number}")
                    break

            logger.info(f"Successfully fetched {len(all_files)} files for {repo_name}#{pr_number}")
            return all_files

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise GitHubPRNotFoundException(repo_name, pr_number)
            raise self._handle_http_error(e, f"get PR files for {repo_name}#{pr_number}")

    async def get_pr_diff(
        self,
        repo_name: str,
        pr_number: int,
        installation_id: int
    ) -> str:
        """
        Get unified diff for entire pull request.

        Args:
            repo_name: Repository name in format "owner/repo"
            pr_number: Pull request number
            installation_id: GitHub installation ID for authentication

        Returns:
            Raw unified diff string

        Raises:
            GitHubPRNotFoundException: If PR doesn't exist
            GitHubAPIException: For other API errors
        """
        endpoint = f"/repos/{repo_name}/pulls/{pr_number}"
        headers = {"Accept": "application/vnd.github.diff"}

        logger.info(f"Fetching PR diff for {repo_name}#{pr_number}")

        try:
            response_text = await self._make_api_request(
                method="GET",
                endpoint=endpoint,
                installation_id=installation_id,
                additional_headers=headers,
                return_text=True
            )

            logger.info(f"Successfully fetched PR diff for {repo_name}#{pr_number}")
            return response_text

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise GitHubPRNotFoundException(repo_name, pr_number)
            raise self._handle_http_error(e, f"get PR diff for {repo_name}#{pr_number}")

    async def create_review(
        self,
        repo_name: str,
        pr_number: int,
        review_data: Dict[str, Any],
        installation_id: int
    ) -> Dict[str, Any]:
        """
        Create a pull request review with comments.

        Args:
            repo_name: Repository name in format "owner/repo"
            pr_number: Pull request number
            review_data: Review payload with body, event, and comments
            installation_id: GitHub installation ID for authentication

        Returns:
            Created review object with ID and URL

        Raises:
            GitHubPRNotFoundException: If PR doesn't exist
            GitHubPermissionException: If lacking permissions to create review
            GitHubAPIException: For other API errors
        """
        endpoint = f"/repos/{repo_name}/pulls/{pr_number}/reviews"

        logger.info(f"Creating review for {repo_name}#{pr_number}")

        try:
            response_data = await self._make_api_request(
                method="POST",
                endpoint=endpoint,
                installation_id=installation_id,
                json_data=review_data
            )

            logger.info(
                f"Successfully created review {response_data.get('id')} for {repo_name}#{pr_number}"
            )
            return response_data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise GitHubPRNotFoundException(repo_name, pr_number)
            elif e.response.status_code == 403:
                raise GitHubPermissionException(
                    f"Insufficient permissions to create review for {repo_name}#{pr_number}"
                )
            raise self._handle_http_error(e, f"create review for {repo_name}#{pr_number}")

    async def _make_api_request(
        self,
        method: str,
        endpoint: str,
        installation_id: int,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        additional_headers: Optional[Dict[str, str]] = None,
        return_text: bool = False
    ) -> Any:
        """
        Make authenticated API request with retry logic and rate limiting.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path (starting with /)
            installation_id: GitHub installation ID for token generation
            params: Query parameters
            json_data: JSON request body
            additional_headers: Additional headers to include
            return_text: If True, return response text instead of JSON

        Returns:
            Response data (JSON dict or text string)

        Raises:
            GitHubAPIException: For API errors
            GitHubRateLimitException: For rate limit exceeded
            GitHubAuthenticationException: For auth failures
        """
        url = f"{self.base_url}{endpoint}"
        max_retries = pr_review_settings.github_api.retry_attempts

        for attempt in range(max_retries + 1):
            try:
                # Check rate limit before making request
                await self._check_rate_limit()

                # Generate fresh installation token
                token = await self.helpers.generate_installation_token(installation_id)

                # Prepare headers
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "AI-Code-Reviewer/1.0"
                }

                if additional_headers:
                    headers.update(additional_headers)

                # Make request with timeout
                timeout = httpx.Timeout(pr_review_settings.github_api.request_timeout)

                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        params=params,
                        json=json_data
                    )

                    # Update rate limit info from headers
                    self._rate_limit_info = GitHubAPIRateLimit.from_headers(response.headers)

                    # Handle rate limiting
                    if response.status_code == 429:
                        retry_after = int(response.headers.get('retry-after', 60))
                        raise GitHubRateLimitException(retry_after_seconds=retry_after)

                    # Raise for HTTP errors
                    response.raise_for_status()

                    # Return appropriate response format
                    if return_text:
                        return response.text
                    else:
                        return response.json()

            except GitHubRateLimitException as e:
                if attempt < max_retries:
                    delay = e.retry_after_seconds or 60
                    logger.warning(f"Rate limit hit, waiting {delay}s before retry {attempt + 1}")
                    await asyncio.sleep(delay)
                    continue
                raise

            except httpx.HTTPStatusError as e:
                if attempt < max_retries and e.response.status_code >= 500:
                    delay = pr_review_settings.github_api.retry_backoff ** attempt
                    logger.warning(f"Server error {e.response.status_code}, retrying in {delay}s")
                    await asyncio.sleep(delay)
                    continue
                # Re-raise to be handled by caller
                raise

            except (httpx.RequestError, httpx.TimeoutException) as e:
                if attempt < max_retries:
                    delay = pr_review_settings.github_api.retry_backoff ** attempt
                    logger.warning(f"Request error: {e}, retrying in {delay}s")
                    await asyncio.sleep(delay)
                    continue
                raise GitHubAPIException(f"Request failed after {max_retries} attempts: {e}")

            except Exception as e:
                # Don't retry unexpected errors
                raise GitHubAPIException(f"Unexpected error during API request: {e}")

        # Should not reach here due to the loop structure, but for safety
        raise GitHubAPIException(f"Failed to complete request after {max_retries} attempts")

    async def _check_rate_limit(self) -> None:
        """
        Check current rate limit status and wait if necessary.

        Raises:
            GitHubRateLimitException: If rate limit will be exceeded
        """
        if not self._rate_limit_info:
            return

        # If we're close to the limit, wait for reset
        if self._rate_limit_info.remaining < 10:  # Conservative buffer
            wait_time = self._rate_limit_info.seconds_until_reset
            if wait_time > 0:
                logger.warning(
                    f"Rate limit nearly exceeded ({self._rate_limit_info.remaining} remaining), "
                    f"waiting {wait_time}s for reset"
                )
                await asyncio.sleep(wait_time)

    def _handle_http_error(self, error: httpx.HTTPStatusError, operation: str) -> GitHubAPIException:
        """
        Convert HTTP status error to appropriate GitHub exception.

        Args:
            error: HTTP status error from httpx
            operation: Description of the operation that failed

        Returns:
            Appropriate GitHubAPIException subclass
        """
        status_code = error.response.status_code
        response_text = error.response.text

        if status_code == 401:
            return GitHubAuthenticationException()
        elif status_code == 403:
            return GitHubPermissionException(f"Permission denied to {operation}")
        elif status_code == 429:
            retry_after = int(error.response.headers.get('retry-after', 60))
            return GitHubRateLimitException(retry_after_seconds=retry_after)
        else:
            message = f"GitHub API error during {operation}: {status_code}"
            if response_text:
                message += f" - {response_text}"
            return GitHubAPIException(message=message, status_code=status_code)

    def get_current_rate_limit(self) -> Optional[GitHubAPIRateLimit]:
        """Get current rate limit information."""
        return self._rate_limit_info

    async def check_api_health(self, installation_id: int) -> bool:
        """
        Check if GitHub API is accessible with given installation.

        Args:
            installation_id: GitHub installation ID to test

        Returns:
            True if API is accessible, False otherwise
        """
        try:
            await self._make_api_request(
                method="GET",
                endpoint="/rate_limit",
                installation_id=installation_id
            )
            return True
        except Exception as e:
            logger.error(f"GitHub API health check failed: {e}")
            return False