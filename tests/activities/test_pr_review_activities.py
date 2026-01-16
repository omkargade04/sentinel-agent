"""
Tests for PR Review Activities

Tests Temporal activity implementations for Phase 2.
"""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.activities.pr_review_activities import (
    fetch_pr_context_activity,
    clone_pr_head_activity,
    cleanup_pr_clone_activity
)
from src.models.schemas.pr_review import PRReviewRequest
from src.exceptions.pr_review_exceptions import (
    PRTooLargeException,
    BinaryFileException,
    InvalidDiffFormatException
)


@pytest.fixture
def sample_pr_request():
    """Sample PR review request."""
    return PRReviewRequest(
        installation_id=12345,
        repo_id=uuid.uuid4(),
        github_repo_id=987654321,
        github_repo_name="owner/test-repo",
        pr_number=42,
        head_sha="1234567890abcdef1234567890abcdef12345678",
        base_sha="abcdef1234567890abcdef1234567890abcdef12"
    )


@pytest.fixture
def sample_pr_details():
    """Sample PR details from GitHub API."""
    return {
        "id": 123456789,
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
            "additions": 5,
            "deletions": 2,
            "changes": 7,
            "patch": "@@ -1,3 +1,6 @@\n def test():\n-    return False\n+    # Updated logic\n+    result = calculate()\n+    return result"
        },
        {
            "filename": "README.md",
            "status": "modified",
            "additions": 1,
            "deletions": 0,
            "changes": 1,
            "patch": "@@ -10,2 +10,3 @@\n ## Usage\n Run the script\n+See docs for details"
        }
    ]


class TestFetchPRContextActivity:
    """Test suite for fetch_pr_context_activity."""

    @pytest.mark.asyncio
    async def test_fetch_pr_context_success(self, sample_pr_request, sample_pr_details, sample_pr_files):
        """Test successful PR context fetching."""
        with patch('src.activities.pr_review_activities.PRApiClient') as mock_api_client:
            with patch('src.activities.pr_review_activities.UnifiedDiffParser') as mock_parser:
                # Setup mocks
                mock_client_instance = AsyncMock()
                mock_api_client.return_value = mock_client_instance
                mock_client_instance.get_pr_details.return_value = sample_pr_details
                mock_client_instance.get_pr_files.return_value = sample_pr_files

                mock_parser_instance = MagicMock()
                mock_parser.return_value = mock_parser_instance

                # Mock patch objects
                mock_patch1 = MagicMock()
                mock_patch1.model_dump.return_value = {"file_path": "src/test.py", "changes": 7}
                mock_patch1.changes = 7

                mock_patch2 = MagicMock()
                mock_patch2.model_dump.return_value = {"file_path": "README.md", "changes": 1}
                mock_patch2.changes = 1

                mock_parser_instance._parse_single_file.side_effect = [mock_patch1, mock_patch2]

                # Execute activity
                result = await fetch_pr_context_activity(sample_pr_request)

                # Verify results
                assert result["total_files_changed"] == 2
                assert result["large_pr"] is False
                assert len(result["patches"]) == 2
                assert result["pr_metadata"]["title"] == "Add new feature"
                assert result["pr_metadata"]["author"] == "testuser"
                assert result["parsing_stats"]["files_fetched"] == 2
                assert result["parsing_stats"]["files_parsed"] == 2

                # Verify API calls
                mock_client_instance.get_pr_details.assert_called_once_with(
                    "owner/test-repo", 42, 12345
                )
                mock_client_instance.get_pr_files.assert_called_once_with(
                    "owner/test-repo", 42, 12345
                )

    @pytest.mark.asyncio
    async def test_fetch_pr_context_too_large(self, sample_pr_request):
        """Test PR too large exception handling."""
        # Create many files to exceed limit
        many_files = [
            {"filename": f"file_{i}.py", "status": "modified", "additions": 1, "deletions": 0, "changes": 1}
            for i in range(100)  # Exceeds default limit of 50
        ]

        with patch('src.activities.pr_review_activities.PRApiClient') as mock_api_client:
            mock_client_instance = AsyncMock()
            mock_api_client.return_value = mock_client_instance
            mock_client_instance.get_pr_details.return_value = {"id": 123}
            mock_client_instance.get_pr_files.return_value = many_files

            with pytest.raises(PRTooLargeException) as exc_info:
                await fetch_pr_context_activity(sample_pr_request)

            assert "100" in str(exc_info.value)
            assert "50" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_pr_context_with_binary_files(self, sample_pr_request, sample_pr_details):
        """Test PR context fetching with binary files that get skipped."""
        mixed_files = [
            {
                "filename": "src/code.py",
                "status": "modified",
                "additions": 2,
                "deletions": 1,
                "changes": 3,
                "patch": "@@ -1,1 +1,2 @@\n+# New line\n code"
            },
            {
                "filename": "image.png",
                "status": "added",
                "binary": True,
                "additions": 0,
                "deletions": 0,
                "changes": 0
            }
        ]

        with patch('src.activities.pr_review_activities.PRApiClient') as mock_api_client:
            with patch('src.activities.pr_review_activities.UnifiedDiffParser') as mock_parser:
                # Setup mocks
                mock_client_instance = AsyncMock()
                mock_api_client.return_value = mock_client_instance
                mock_client_instance.get_pr_details.return_value = sample_pr_details
                mock_client_instance.get_pr_files.return_value = mixed_files

                mock_parser_instance = MagicMock()
                mock_parser.return_value = mock_parser_instance

                # Mock parser to return patch for code file, raise exception for binary
                mock_patch = MagicMock()
                mock_patch.model_dump.return_value = {"file_path": "src/code.py"}
                mock_patch.changes = 3

                def parse_side_effect(file_data):
                    if file_data["filename"] == "image.png":
                        raise BinaryFileException("image.png")
                    return mock_patch

                mock_parser_instance._parse_single_file.side_effect = parse_side_effect

                result = await fetch_pr_context_activity(sample_pr_request)

                # Should have parsed 1 file, skipped 1 binary
                assert result["total_files_changed"] == 1
                assert result["parsing_stats"]["files_fetched"] == 2
                assert result["parsing_stats"]["files_parsed"] == 1
                assert result["parsing_stats"]["binary_files_skipped"] == 1

    @pytest.mark.asyncio
    async def test_fetch_pr_context_no_parseable_files(self, sample_pr_request, sample_pr_details):
        """Test handling when no files can be parsed."""
        invalid_files = [
            {
                "filename": "invalid.txt",
                "status": "modified",
                "additions": 1,
                "deletions": 0,
                "changes": 1,
                "patch": "invalid diff format"
            }
        ]

        with patch('src.activities.pr_review_activities.PRApiClient') as mock_api_client:
            with patch('src.activities.pr_review_activities.UnifiedDiffParser') as mock_parser:
                mock_client_instance = AsyncMock()
                mock_api_client.return_value = mock_client_instance
                mock_client_instance.get_pr_details.return_value = sample_pr_details
                mock_client_instance.get_pr_files.return_value = invalid_files

                mock_parser_instance = MagicMock()
                mock_parser.return_value = mock_parser_instance
                mock_parser_instance._parse_single_file.side_effect = InvalidDiffFormatException("Invalid format")

                with pytest.raises(InvalidDiffFormatException) as exc_info:
                    await fetch_pr_context_activity(sample_pr_request)

                assert "No files could be parsed" in str(exc_info.value)


class TestClonePRHeadActivity:
    """Test suite for clone_pr_head_activity."""

    @pytest.mark.asyncio
    async def test_clone_pr_head_success(self, sample_pr_request):
        """Test successful PR head cloning."""
        expected_clone_path = "/tmp/pr-review-clone-test"
        clone_info = {
            "size_bytes": 1024 * 1024,  # 1MB
            "current_sha": sample_pr_request.head_sha,
            "commit_message": "Test commit",
            "author_name": "Test Author",
            "author_email": "test@example.com",
            "commit_date": "2024-01-15"
        }

        with patch('src.activities.pr_review_activities.PRCloneService') as mock_clone_service:
            with patch('src.activities.pr_review_activities.os.walk') as mock_walk:
                with patch('src.activities.pr_review_activities.time.time', side_effect=[1000, 1002]):  # 2 second duration
                    # Setup mocks
                    mock_service_instance = AsyncMock()
                    mock_clone_service.return_value = mock_service_instance
                    mock_service_instance.clone_pr_head.return_value = expected_clone_path
                    mock_service_instance.get_clone_info.return_value = clone_info

                    # Mock file counting
                    mock_walk.return_value = [
                        ("/tmp/clone", [], ["file1.py", "file2.py"]),
                        ("/tmp/clone/subdir", [], ["file3.py"])
                    ]

                    result = await clone_pr_head_activity(sample_pr_request)

                    # Verify results
                    assert result["clone_path"] == expected_clone_path
                    assert result["clone_size_mb"] == 1.0
                    assert result["clone_duration_ms"] == 2000
                    assert result["file_count"] == 3
                    assert result["clone_metadata"]["current_sha"] == sample_pr_request.head_sha
                    assert result["clone_metadata"]["commit_message"] == "Test commit"

                    # Verify service calls
                    mock_service_instance.clone_pr_head.assert_called_once_with(
                        repo_name=sample_pr_request.github_repo_name,
                        head_sha=sample_pr_request.head_sha,
                        installation_id=sample_pr_request.installation_id
                    )

    @pytest.mark.asyncio
    async def test_clone_pr_head_with_git_directory(self, sample_pr_request):
        """Test file counting skips .git directory."""
        expected_clone_path = "/tmp/pr-review-clone-test"

        with patch('src.activities.pr_review_activities.PRCloneService') as mock_clone_service:
            with patch('src.activities.pr_review_activities.os.walk') as mock_walk:
                with patch('src.activities.pr_review_activities.time.time', side_effect=[1000, 1001]):
                    mock_service_instance = AsyncMock()
                    mock_clone_service.return_value = mock_service_instance
                    mock_service_instance.clone_pr_head.return_value = expected_clone_path
                    mock_service_instance.get_clone_info.return_value = {"size_bytes": 1024}

                    # Mock file walk with .git directory
                    mock_walk.return_value = [
                        ("/tmp/clone", [".git", "src"], ["file1.py"]),
                        ("/tmp/clone/.git", [], ["config", "HEAD"]),  # Should be skipped
                        ("/tmp/clone/src", [], ["file2.py", "file3.py"])
                    ]

                    result = await clone_pr_head_activity(sample_pr_request)

                    # Should count only files outside .git directory
                    assert result["file_count"] == 3  # file1.py, file2.py, file3.py

    @pytest.mark.asyncio
    async def test_clone_pr_head_file_count_error(self, sample_pr_request):
        """Test handling of file counting errors."""
        expected_clone_path = "/tmp/pr-review-clone-test"

        with patch('src.activities.pr_review_activities.PRCloneService') as mock_clone_service:
            with patch('src.activities.pr_review_activities.os.walk', side_effect=OSError("Permission denied")):
                with patch('src.activities.pr_review_activities.time.time', side_effect=[1000, 1001]):
                    mock_service_instance = AsyncMock()
                    mock_clone_service.return_value = mock_service_instance
                    mock_service_instance.clone_pr_head.return_value = expected_clone_path
                    mock_service_instance.get_clone_info.return_value = {"size_bytes": 1024}

                    result = await clone_pr_head_activity(sample_pr_request)

                    # Should handle error gracefully and set file_count to 0
                    assert result["file_count"] == 0


class TestCleanupPRCloneActivity:
    """Test suite for cleanup_pr_clone_activity."""

    @pytest.mark.asyncio
    async def test_cleanup_pr_clone_success(self):
        """Test successful clone cleanup."""
        input_data = {"clone_path": "/tmp/test-clone-path"}

        with patch('src.activities.pr_review_activities.PRCloneService') as mock_clone_service:
            with patch('src.activities.pr_review_activities.time.time', side_effect=[1000, 1001]):  # 1 second
                mock_service_instance = AsyncMock()
                mock_clone_service.return_value = mock_service_instance
                mock_service_instance.cleanup_clone.return_value = None

                result = await cleanup_pr_clone_activity(input_data)

                assert result["cleaned_up"] is True
                assert result["path"] == "/tmp/test-clone-path"
                assert result["cleanup_duration_ms"] == 1000

                mock_service_instance.cleanup_clone.assert_called_once_with("/tmp/test-clone-path")

    @pytest.mark.asyncio
    async def test_cleanup_pr_clone_error(self):
        """Test cleanup with error handling."""
        input_data = {"clone_path": "/tmp/test-clone-path"}

        with patch('src.activities.pr_review_activities.PRCloneService') as mock_clone_service:
            mock_service_instance = AsyncMock()
            mock_clone_service.return_value = mock_service_instance
            mock_service_instance.cleanup_clone.side_effect = OSError("Permission denied")

            result = await cleanup_pr_clone_activity(input_data)

            # Should handle error gracefully
            assert result["cleaned_up"] is False
            assert result["path"] == "/tmp/test-clone-path"
            assert "error" in result
            assert "Permission denied" in result["error"]


class TestActivityExceptionHandling:
    """Test exception handling across activities."""

    @pytest.mark.asyncio
    async def test_fetch_pr_context_generic_exception(self, sample_pr_request):
        """Test generic exception handling in fetch PR context."""
        with patch('src.activities.pr_review_activities.PRApiClient') as mock_api_client:
            mock_client_instance = AsyncMock()
            mock_api_client.return_value = mock_client_instance
            mock_client_instance.get_pr_details.side_effect = Exception("Network error")

            with pytest.raises(Exception) as exc_info:
                await fetch_pr_context_activity(sample_pr_request)

            assert "Network error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_clone_pr_head_generic_exception(self, sample_pr_request):
        """Test generic exception handling in clone PR head."""
        with patch('src.activities.pr_review_activities.PRCloneService') as mock_clone_service:
            mock_service_instance = AsyncMock()
            mock_clone_service.return_value = mock_service_instance
            mock_service_instance.clone_pr_head.side_effect = Exception("Clone failed")

            with pytest.raises(Exception) as exc_info:
                await clone_pr_head_activity(sample_pr_request)

            assert "Clone failed" in str(exc_info.value)