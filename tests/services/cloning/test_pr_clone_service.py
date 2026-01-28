"""
Tests for PRCloneService

Tests secure cloning functionality with mocking of git operations.
"""

import pytest
import asyncio
import tempfile
import os
import shutil
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from src.services.cloning.pr_clone_service import PRCloneService
from src.exceptions.pr_review_exceptions import (
    PRCloneException,
    CloneTimeoutException,
    ClonePermissionException,
    SHAValidationException,
    CloneResourceExhaustedException
)


@pytest.fixture
def clone_service():
    """Create PRCloneService instance for testing."""
    return PRCloneService()


@pytest.fixture
def mock_installation_token():
    """Mock installation token."""
    return "ghs_test_token_1234567890"


@pytest.fixture
def valid_sha():
    """Valid 40-character SHA."""
    return "1234567890abcdef1234567890abcdef12345678"


@pytest.fixture
def temp_clone_dir():
    """Create and cleanup temporary directory for testing."""
    temp_dir = tempfile.mkdtemp(prefix="test_clone_")
    yield temp_dir
    if Path(temp_dir).exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


class TestPRCloneService:
    """Test suite for PRCloneService."""

    @pytest.mark.asyncio
    async def test_clone_pr_head_success(self, clone_service, valid_sha, mock_installation_token):
        """Test successful PR head cloning."""
        repo_name = "owner/test-repo"
        installation_id = 12345

        with patch.object(clone_service.helpers, 'generate_installation_token', return_value=mock_installation_token):
            with patch.object(clone_service, '_create_secure_temp_dir') as mock_create_dir:
                with patch.object(clone_service, '_perform_clone') as mock_perform_clone:
                    with patch.object(clone_service, '_validate_clone_integrity', return_value=True):
                        with patch.object(clone_service, '_get_directory_size', return_value=1024 * 1024):  # 1MB
                            with patch.object(clone_service, '_validate_resource_usage'):
                                mock_clone_path = "/tmp/test-clone-path"
                                mock_create_dir.return_value = mock_clone_path

                                result = await clone_service.clone_pr_head(
                                    repo_name, valid_sha, installation_id
                                )

                                assert result == mock_clone_path
                                mock_create_dir.assert_called_once()
                                mock_perform_clone.assert_called_once_with(
                                    repo_name, valid_sha, mock_clone_path, mock_installation_token
                                )

    @pytest.mark.asyncio
    async def test_clone_pr_head_invalid_sha(self, clone_service):
        """Test clone with invalid SHA format."""
        invalid_sha = "invalid_sha_format"

        with pytest.raises(PRCloneException) as exc_info:
            await clone_service.clone_pr_head("owner/repo", invalid_sha, 12345)

        assert "Invalid SHA format" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_clone_pr_head_timeout(self, clone_service, valid_sha, mock_installation_token):
        """Test clone timeout handling."""
        repo_name = "owner/test-repo"
        installation_id = 12345

        with patch.object(clone_service.helpers, 'generate_installation_token', return_value=mock_installation_token):
            with patch.object(clone_service, '_create_secure_temp_dir', return_value="/tmp/test"):
                with patch.object(clone_service, '_perform_clone', side_effect=asyncio.sleep(10)):
                    with pytest.raises(CloneTimeoutException) as exc_info:
                        await clone_service.clone_pr_head(
                            repo_name, valid_sha, installation_id, timeout_seconds=1
                        )

                    assert repo_name in str(exc_info.value)
                    assert "1" in str(exc_info.value)  # timeout value

    @pytest.mark.asyncio
    async def test_validate_clone_integrity_success(self, clone_service, valid_sha, temp_clone_dir):
        """Test successful clone integrity validation."""
        # Mock git command that returns the expected SHA
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (valid_sha.encode(), b"")
            mock_subprocess.return_value = mock_process

            result = await clone_service._validate_clone_integrity(temp_clone_dir, valid_sha)

            assert result is True

    @pytest.mark.asyncio
    async def test_validate_clone_integrity_sha_mismatch(self, clone_service, valid_sha, temp_clone_dir):
        """Test clone integrity validation with SHA mismatch."""
        different_sha = "abcdef1234567890abcdef1234567890abcdef12"

        # Mock git command that returns a different SHA
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (different_sha.encode(), b"")
            mock_subprocess.return_value = mock_process

            with pytest.raises(SHAValidationException) as exc_info:
                await clone_service._validate_clone_integrity(temp_clone_dir, valid_sha)

            assert valid_sha in str(exc_info.value)
            assert different_sha in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validate_clone_integrity_git_error(self, clone_service, valid_sha, temp_clone_dir):
        """Test clone integrity validation with git command error."""
        # Mock git command that fails
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.returncode = 1
            mock_process.communicate.return_value = (b"", b"fatal: not a git repository")
            mock_subprocess.return_value = mock_process

            with pytest.raises(PRCloneException) as exc_info:
                await clone_service._validate_clone_integrity(temp_clone_dir, valid_sha)

            assert "Failed to get current SHA" in str(exc_info.value)

    def test_validate_sha_format_valid(self, clone_service):
        """Test SHA format validation with valid SHAs."""
        valid_shas = [
            "1234567890abcdef1234567890abcdef12345678",
            "abcdef1234567890abcdef1234567890abcdef12",
            "0000000000000000000000000000000000000000",
            "ffffffffffffffffffffffffffffffffffffffff"
        ]

        for sha in valid_shas:
            assert clone_service._validate_sha_format(sha) is True

    def test_validate_sha_format_invalid(self, clone_service):
        """Test SHA format validation with invalid SHAs."""
        invalid_shas = [
            "",
            "short",
            "1234567890abcdef1234567890abcdef1234567g",  # Invalid character
            "1234567890abcdef1234567890abcdef123456789",  # 41 chars
            "1234567890abcdef1234567890abcdef1234567",   # 39 chars
            None,
            123456789,
            "not-a-hex-string-but-is-forty-characters!"
        ]

        for sha in invalid_shas:
            assert clone_service._validate_sha_format(sha) is False

    @pytest.mark.asyncio
    async def test_create_secure_temp_dir(self, clone_service):
        """Test secure temporary directory creation."""
        repo_name = "owner/test-repo"
        sha = "1234567890abcdef1234567890abcdef12345678"

        clone_path = await clone_service._create_secure_temp_dir(repo_name, sha)

        try:
            # Verify directory exists and has correct permissions
            assert Path(clone_path).exists()
            assert Path(clone_path).is_dir()

            # Check permissions (should be 0o700)
            stat_info = os.stat(clone_path)
            permissions = oct(stat_info.st_mode)[-3:]
            assert permissions == "700"

            # Verify path structure
            assert "owner_test-repo" in clone_path
            assert sha[:12] in clone_path

        finally:
            # Cleanup
            if Path(clone_path).exists():
                shutil.rmtree(clone_path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_create_secure_temp_dir_existing_cleanup(self, clone_service):
        """Test cleanup of existing directory."""
        repo_name = "owner/test-repo"
        sha = "1234567890abcdef1234567890abcdef12345678"

        # First call creates directory
        clone_path1 = await clone_service._create_secure_temp_dir(repo_name, sha)

        # Create a file to verify cleanup
        test_file = Path(clone_path1) / "test_file.txt"
        test_file.write_text("test content")
        assert test_file.exists()

        # Second call should cleanup and recreate
        with patch.object(clone_service, 'cleanup_clone') as mock_cleanup:
            clone_path2 = await clone_service._create_secure_temp_dir(repo_name, sha)
            mock_cleanup.assert_called_once_with(clone_path1)

        # Cleanup
        for path in [clone_path1, clone_path2]:
            if Path(path).exists():
                shutil.rmtree(path, ignore_errors=True)

    def test_validate_resource_usage_within_limits(self, clone_service):
        """Test resource validation within limits."""
        # 100MB should be within default 1000MB limit
        size_bytes = 100 * 1024 * 1024

        # Should not raise exception
        clone_service._validate_resource_usage(size_bytes)

    def test_validate_resource_usage_exceeds_limits(self, clone_service):
        """Test resource validation exceeding limits."""
        # 2000MB exceeds default 1000MB limit
        size_bytes = 2000 * 1024 * 1024

        with pytest.raises(CloneResourceExhaustedException) as exc_info:
            clone_service._validate_resource_usage(size_bytes)

        assert "disk space" in str(exc_info.value)
        assert "2000.0MB" in str(exc_info.value)

    def test_get_directory_size(self, clone_service, temp_clone_dir):
        """Test directory size calculation."""
        # Create test files with known sizes
        test_files = [
            ("file1.txt", "a" * 1000),  # 1KB
            ("file2.txt", "b" * 2000),  # 2KB
            ("subdir/file3.txt", "c" * 500)  # 0.5KB
        ]

        for file_path, content in test_files:
            full_path = Path(temp_clone_dir) / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)

        total_size = clone_service._get_directory_size(temp_clone_dir)

        # Should be approximately 3.5KB
        assert 3400 <= total_size <= 3600  # Allow some filesystem overhead

    @pytest.mark.asyncio
    async def test_cleanup_clone_success(self, clone_service, temp_clone_dir):
        """Test successful clone cleanup."""
        # Create test files and subdirectories
        test_file = Path(temp_clone_dir) / "test_file.txt"
        test_subdir = Path(temp_clone_dir) / "subdir"
        test_subfile = test_subdir / "subfile.txt"

        test_subdir.mkdir()
        test_file.write_text("test content")
        test_subfile.write_text("sub content")

        # Make some files read-only to test permission handling
        os.chmod(test_file, 0o444)
        os.chmod(test_subfile, 0o444)

        assert Path(temp_clone_dir).exists()

        await clone_service.cleanup_clone(temp_clone_dir)

        assert not Path(temp_clone_dir).exists()

    @pytest.mark.asyncio
    async def test_cleanup_clone_nonexistent(self, clone_service):
        """Test cleanup of non-existent directory."""
        nonexistent_path = "/tmp/nonexistent_clone_dir"

        # Should not raise exception
        await clone_service.cleanup_clone(nonexistent_path)

    @pytest.mark.asyncio
    async def test_temporary_clone_context_manager(self, clone_service, valid_sha, mock_installation_token):
        """Test temporary clone context manager."""
        repo_name = "owner/test-repo"
        installation_id = 12345

        with patch.object(clone_service, 'clone_pr_head', return_value="/tmp/test-clone") as mock_clone:
            with patch.object(clone_service, 'cleanup_clone') as mock_cleanup:

                async with clone_service.temporary_clone(repo_name, valid_sha, installation_id) as clone_path:
                    assert clone_path == "/tmp/test-clone"
                    # Verify clone was called
                    mock_clone.assert_called_once_with(repo_name, valid_sha, installation_id, None)

                # Verify cleanup was called after context exit
                mock_cleanup.assert_called_once_with("/tmp/test-clone")

    @pytest.mark.asyncio
    async def test_temporary_clone_context_manager_exception(self, clone_service, valid_sha):
        """Test temporary clone context manager with exception."""
        repo_name = "owner/test-repo"
        installation_id = 12345

        with patch.object(clone_service, 'clone_pr_head', return_value="/tmp/test-clone"):
            with patch.object(clone_service, 'cleanup_clone') as mock_cleanup:

                with pytest.raises(ValueError):
                    async with clone_service.temporary_clone(repo_name, valid_sha, installation_id) as clone_path:
                        raise ValueError("Test exception")

                # Verify cleanup was still called despite exception
                mock_cleanup.assert_called_once_with("/tmp/test-clone")

    @pytest.mark.asyncio
    async def test_get_clone_info_success(self, clone_service, temp_clone_dir):
        """Test getting clone information."""
        # Mock git log command
        commit_info = "abc123|Test commit|John Doe|john@example.com|Mon Jan 15 10:00:00 2024"

        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (commit_info.encode(), b"")
            mock_subprocess.return_value = mock_process

            with patch.object(clone_service, '_get_directory_size', return_value=1024):
                info = await clone_service.get_clone_info(temp_clone_dir)

                assert info["exists"] is True
                assert info["current_sha"] == "abc123"
                assert info["commit_message"] == "Test commit"
                assert info["author_name"] == "John Doe"
                assert info["author_email"] == "john@example.com"
                assert info["size_bytes"] == 1024

    @pytest.mark.asyncio
    async def test_get_clone_info_nonexistent(self, clone_service):
        """Test getting info for non-existent clone."""
        info = await clone_service.get_clone_info("/tmp/nonexistent")

        assert info["exists"] is False

    @pytest.mark.asyncio
    async def test_run_git_command_success(self, clone_service):
        """Test successful git command execution."""
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (b"success output", b"")
            mock_subprocess.return_value = mock_process

            result = await clone_service._run_git_command(
                ["git", "status"], {}, "/tmp/test"
            )

            assert result == "success output"

    @pytest.mark.asyncio
    async def test_run_git_command_failure(self, clone_service):
        """Test git command failure handling."""
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.returncode = 1
            mock_process.communicate.return_value = (b"", b"fatal: not a git repository")
            mock_subprocess.return_value = mock_process

            with pytest.raises(PRCloneException) as exc_info:
                await clone_service._run_git_command(
                    ["git", "status"], {}, "/tmp/test"
                )

            assert "Git command failed" in str(exc_info.value)
            assert "fatal: not a git repository" in str(exc_info.value)