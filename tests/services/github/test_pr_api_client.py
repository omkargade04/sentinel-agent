"""
Tests for PRApiClient

Tests GitHub API integration for PR operations with mocking.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from src.services.github.pr_api_client import PRApiClient, GitHubAPIRateLimit
from src.exceptions.pr_review_exceptions import (
    GitHubAPIException,
    GitHubPRNotFoundException,
    GitHubRateLimitException,
    GitHubAuthenticationException,
    GitHubPermissionException
)


@pytest.fixture
def pr_api_client():
    """Create PRApiClient instance for testing."""
    return PRApiClient()


@pytest.fixture
def mock_installation_token():
    """Mock installation token."""
    return "ghs_test_token_1234567890"


@pytest.fixture
def sample_pr_details():
    """Sample PR details from GitHub API."""
    return {
        "id": 123456789,
        "number": 42,
        "title": "Add new feature",
        "state": "open",
        "draft": False,
        "mergeable": True,
        "user": {"login": "testuser"},
        "created_at": "2024-01-15T10:00:00Z",
        "updated_at": "2024-01-15T12:00:00Z",
        "base": {"ref": "main"},
        "head": {"ref": "feature-branch"}
    }


@pytest.fixture
def sample_pr_files():
    """Sample PR files from GitHub API."""
    return [
        {
            "filename": "src/test.py",
            "status": "modified",
            "additions": 10,
            "deletions": 5,
            "changes": 15,
            "patch": "@@ -1,4 +1,6 @@\n def test_function():\n+    # New comment\n     return True\n+    # Another line"
        },
        {
            "filename": "README.md",
            "status": "modified",
            "additions": 2,
            "deletions": 1,
            "changes": 3,
            "patch": "@@ -10,3 +10,4 @@\n ## Installation\n-Run pip install\n+Run pip install -r requirements.txt\n+See docs for more info"
        }
    ]


class TestPRApiClient:
    """Test suite for PRApiClient."""

    @pytest.mark.asyncio
    async def test_get_pr_details_success(self, pr_api_client, sample_pr_details, mock_installation_token):
        """Test successful PR details retrieval."""
        with patch.object(pr_api_client.helpers, 'generate_installation_token', return_value=mock_installation_token):
            with patch('httpx.AsyncClient') as mock_client:
                # Setup mock response
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.headers = {}
                mock_response.json.return_value = sample_pr_details
                mock_response.raise_for_status = MagicMock()

                mock_client.return_value.__aenter__.return_value.request.return_value = mock_response

                result = await pr_api_client.get_pr_details("owner/repo", 42, 12345)

                assert result == sample_pr_details
                assert result["number"] == 42
                assert result["title"] == "Add new feature"

    @pytest.mark.asyncio
    async def test_get_pr_details_not_found(self, pr_api_client, mock_installation_token):
        """Test PR not found error handling."""
        with patch.object(pr_api_client.helpers, 'generate_installation_token', return_value=mock_installation_token):
            with patch('httpx.AsyncClient') as mock_client:
                # Setup 404 response
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "404", request=MagicMock(), response=mock_response
                )

                mock_client.return_value.__aenter__.return_value.request.return_value = mock_response

                with pytest.raises(GitHubPRNotFoundException) as exc_info:
                    await pr_api_client.get_pr_details("owner/repo", 42, 12345)

                assert "Pull request #42 not found" in str(exc_info.value)
                assert "owner/repo" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_pr_files_success(self, pr_api_client, sample_pr_files, mock_installation_token):
        """Test successful PR files retrieval."""
        with patch.object(pr_api_client.helpers, 'generate_installation_token', return_value=mock_installation_token):
            with patch('httpx.AsyncClient') as mock_client:
                # Setup mock response
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.headers = {}
                mock_response.json.return_value = sample_pr_files
                mock_response.raise_for_status = MagicMock()

                mock_client.return_value.__aenter__.return_value.request.return_value = mock_response

                result = await pr_api_client.get_pr_files("owner/repo", 42, 12345)

                assert result == sample_pr_files
                assert len(result) == 2
                assert result[0]["filename"] == "src/test.py"

    @pytest.mark.asyncio
    async def test_get_pr_files_pagination(self, pr_api_client, mock_installation_token):
        """Test PR files pagination handling."""
        # Create test data for multiple pages
        page1_files = [{"filename": f"file_{i}.py", "status": "modified"} for i in range(100)]
        page2_files = [{"filename": f"file_{i}.py", "status": "modified"} for i in range(100, 150)]

        with patch.object(pr_api_client.helpers, 'generate_installation_token', return_value=mock_installation_token):
            with patch('httpx.AsyncClient') as mock_client:
                # Setup mock responses for pagination
                mock_response_page1 = MagicMock()
                mock_response_page1.status_code = 200
                mock_response_page1.headers = {}
                mock_response_page1.json.return_value = page1_files
                mock_response_page1.raise_for_status = MagicMock()

                mock_response_page2 = MagicMock()
                mock_response_page2.status_code = 200
                mock_response_page2.headers = {}
                mock_response_page2.json.return_value = page2_files
                mock_response_page2.raise_for_status = MagicMock()

                # Return different responses for different page requests
                mock_client.return_value.__aenter__.return_value.request.side_effect = [
                    mock_response_page1, mock_response_page2
                ]

                result = await pr_api_client.get_pr_files("owner/repo", 42, 12345)

                # Should have combined both pages
                assert len(result) == 150
                assert result[0]["filename"] == "file_0.py"
                assert result[149]["filename"] == "file_149.py"

    @pytest.mark.asyncio
    async def test_rate_limit_handling(self, pr_api_client, mock_installation_token):
        """Test rate limit exception handling."""
        with patch.object(pr_api_client.helpers, 'generate_installation_token', return_value=mock_installation_token):
            with patch('httpx.AsyncClient') as mock_client:
                # Setup 429 response
                mock_response = MagicMock()
                mock_response.status_code = 429
                mock_response.headers = {"retry-after": "60"}
                mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "429", request=MagicMock(), response=mock_response
                )

                mock_client.return_value.__aenter__.return_value.request.return_value = mock_response

                with pytest.raises(GitHubRateLimitException) as exc_info:
                    await pr_api_client.get_pr_details("owner/repo", 42, 12345)

                assert exc_info.value.retry_after_seconds == 60

    @pytest.mark.asyncio
    async def test_authentication_error(self, pr_api_client, mock_installation_token):
        """Test authentication error handling."""
        with patch.object(pr_api_client.helpers, 'generate_installation_token', return_value=mock_installation_token):
            with patch('httpx.AsyncClient') as mock_client:
                # Setup 401 response
                mock_response = MagicMock()
                mock_response.status_code = 401
                mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "401", request=MagicMock(), response=mock_response
                )

                mock_client.return_value.__aenter__.return_value.request.return_value = mock_response

                with pytest.raises(GitHubAuthenticationException):
                    await pr_api_client.get_pr_details("owner/repo", 42, 12345)

    @pytest.mark.asyncio
    async def test_create_review_success(self, pr_api_client, mock_installation_token):
        """Test successful review creation."""
        review_data = {
            "body": "LGTM!",
            "event": "APPROVE",
            "comments": []
        }

        expected_response = {
            "id": 123456,
            "html_url": "https://github.com/owner/repo/pull/42#pullrequestreview-123456"
        }

        with patch.object(pr_api_client.helpers, 'generate_installation_token', return_value=mock_installation_token):
            with patch('httpx.AsyncClient') as mock_client:
                # Setup mock response
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.headers = {}
                mock_response.json.return_value = expected_response
                mock_response.raise_for_status = MagicMock()

                mock_client.return_value.__aenter__.return_value.request.return_value = mock_response

                result = await pr_api_client.create_review("owner/repo", 42, review_data, 12345)

                assert result == expected_response
                assert result["id"] == 123456

    def test_rate_limit_from_headers(self):
        """Test rate limit info parsing from headers."""
        headers = {
            "x-ratelimit-limit": "5000",
            "x-ratelimit-remaining": "4999",
            "x-ratelimit-reset": "1640995200",
            "x-ratelimit-used": "1"
        }

        rate_limit = GitHubAPIRateLimit.from_headers(headers)

        assert rate_limit is not None
        assert rate_limit.limit == 5000
        assert rate_limit.remaining == 4999
        assert rate_limit.reset_time == 1640995200
        assert rate_limit.used == 1

    def test_rate_limit_from_invalid_headers(self):
        """Test rate limit parsing with invalid headers."""
        headers = {"content-type": "application/json"}

        rate_limit = GitHubAPIRateLimit.from_headers(headers)

        assert rate_limit is not None
        assert rate_limit.limit == 0
        assert rate_limit.remaining == 0

    @pytest.mark.asyncio
    async def test_api_health_check_success(self, pr_api_client, mock_installation_token):
        """Test successful API health check."""
        with patch.object(pr_api_client.helpers, 'generate_installation_token', return_value=mock_installation_token):
            with patch('httpx.AsyncClient') as mock_client:
                # Setup mock response
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.headers = {}
                mock_response.json.return_value = {"resources": {}}
                mock_response.raise_for_status = MagicMock()

                mock_client.return_value.__aenter__.return_value.request.return_value = mock_response

                result = await pr_api_client.check_api_health(12345)

                assert result is True

    @pytest.mark.asyncio
    async def test_api_health_check_failure(self, pr_api_client, mock_installation_token):
        """Test API health check failure."""
        with patch.object(pr_api_client.helpers, 'generate_installation_token', side_effect=Exception("Auth failed")):
            result = await pr_api_client.check_api_health(12345)
            assert result is False