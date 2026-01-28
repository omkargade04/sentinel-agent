"""
PR Head Clone Service

Specialized service for securely cloning PR head commits for code review analysis.
Provides enhanced security, validation, and resource management.
"""

import os
import asyncio
import tempfile
import shutil
import time
from pathlib import Path
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager

from src.services.repository.helpers import RepositoryHelpers
from src.exceptions.pr_review_exceptions import (
    PRCloneException,
    CloneTimeoutException,
    ClonePermissionException,
    SHAValidationException,
    CloneResourceExhaustedException
)
from src.core.pr_review_config import pr_review_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class PRCloneService:
    """
    Secure cloning service for PR head commits.

    Features:
    - Isolated temporary directories with secure permissions
    - SHA validation post-clone for integrity verification
    - Resource usage monitoring and limits enforcement
    - Guaranteed cleanup via context managers
    - Atomic operations to prevent race conditions
    - Timeout handling for long-running clones
    """

    def __init__(self):
        self.helpers = RepositoryHelpers()
        self.logger = get_logger(__name__)

    async def clone_pr_head(
        self,
        repo_name: str,
        head_sha: str,
        installation_id: int,
        timeout_seconds: Optional[int] = None
    ) -> str:
        """
        Clone repository at PR head SHA to isolated temporary directory.

        Args:
            repo_name: Repository name in format "owner/repo"
            head_sha: Specific commit SHA to clone (40 characters)
            installation_id: GitHub installation ID for authentication
            timeout_seconds: Optional timeout override

        Returns:
            Path to cloned directory

        Raises:
            CloneTimeoutException: If clone operation times out
            ClonePermissionException: If authentication/permission fails
            SHAValidationException: If cloned SHA doesn't match expected
            CloneResourceExhaustedException: If resource limits exceeded
            PRCloneException: For other clone failures
        """
        if not self._validate_sha_format(head_sha):
            raise PRCloneException(f"Invalid SHA format: {head_sha}")

        timeout = timeout_seconds or pr_review_settings.timeouts.clone_pr_head_timeout
        start_time = time.time()

        self.logger.info(f"Starting PR head clone: {repo_name}@{head_sha[:8]}")

        try:
            # Generate installation token
            token = await self.helpers.generate_installation_token(installation_id)

            # Create secure temporary directory
            clone_path = await self._create_secure_temp_dir(repo_name, head_sha)

            # Execute clone operation with timeout
            await asyncio.wait_for(
                self._perform_clone(repo_name, head_sha, clone_path, token),
                timeout=timeout
            )

            # Validate clone integrity
            await self._validate_clone_integrity(clone_path, head_sha)

            # Check resource usage
            clone_size = self._get_directory_size(clone_path)
            self._validate_resource_usage(clone_size)

            duration_ms = int((time.time() - start_time) * 1000)
            self.logger.info(
                f"Successfully cloned PR head {repo_name}@{head_sha[:8]} "
                f"to {clone_path} ({clone_size / 1024 / 1024:.1f}MB, {duration_ms}ms)"
            )

            return clone_path

        except asyncio.TimeoutError:
            raise CloneTimeoutException(repo_name, timeout)
        except Exception as e:
            # Cleanup on failure
            if 'clone_path' in locals() and Path(clone_path).exists():
                await self.cleanup_clone(clone_path)

            if isinstance(e, PRCloneException):
                raise
            else:
                raise PRCloneException(f"Failed to clone {repo_name}@{head_sha}: {e}")

    async def _create_secure_temp_dir(self, repo_name: str, head_sha: str) -> str:
        """
        Create secure temporary directory for clone.

        Args:
            repo_name: Repository name for path generation
            head_sha: Commit SHA for path generation

        Returns:
            Path to created directory
        """
        # Create deterministic but unique path
        safe_repo_name = repo_name.replace('/', '_')
        dir_name = f"pr-review-{safe_repo_name}-{head_sha[:12]}"

        # Use system temp directory with proper permissions
        base_temp = tempfile.gettempdir()
        clone_path = os.path.join(base_temp, dir_name)

        # Handle existing directory (cleanup from previous run)
        if Path(clone_path).exists():
            self.logger.warning(f"Clone directory already exists, cleaning up: {clone_path}")
            await self.cleanup_clone(clone_path)

        # Create directory with restricted permissions
        os.makedirs(clone_path, mode=0o700)

        self.logger.debug(f"Created secure temp directory: {clone_path}")
        return clone_path

    async def _perform_clone(
        self,
        repo_name: str,
        head_sha: str,
        clone_path: str,
        token: str
    ) -> None:
        """
        Execute the actual git clone operation.

        Args:
            repo_name: Repository name
            head_sha: Commit SHA to clone
            clone_path: Target directory
            token: GitHub access token
        """
        repo_url = f"https://github.com/{repo_name}.git"

        # Create temporary askpass script for authentication
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write('#!/bin/sh\n')
            f.write(f'echo "x-access-token:{token}"\n')
            askpass_path = f.name

        os.chmod(askpass_path, 0o700)

        try:
            env = os.environ.copy()
            env.update({
                "GIT_ASKPASS": askpass_path,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",  # Ignore system git config
                "HOME": clone_path,  # Isolate git config
            })

            # Initialize repository
            await self._run_git_command(
                ["git", "init"],
                env=env,
                cwd=clone_path
            )

            # Add remote
            await self._run_git_command(
                ["git", "remote", "add", "origin", repo_url],
                env=env,
                cwd=clone_path
            )

            # Fetch specific commit (shallow for efficiency)
            await self._run_git_command(
                ["git", "fetch", "--depth", "1", "origin", head_sha],
                env=env,
                cwd=clone_path
            )

            # Checkout to detached HEAD at the specific SHA
            await self._run_git_command(
                ["git", "checkout", "--detach", head_sha],
                env=env,
                cwd=clone_path
            )

            self.logger.debug(f"Successfully cloned {repo_name}@{head_sha} to {clone_path}")

        except Exception as e:
            # Convert specific git errors to appropriate exceptions
            error_msg = str(e).lower()

            if "authentication failed" in error_msg or "access denied" in error_msg:
                raise ClonePermissionException(repo_name, 0)  # installation_id not available here
            elif "not found" in error_msg:
                raise PRCloneException(f"Repository or commit not found: {repo_name}@{head_sha}")
            else:
                raise PRCloneException(f"Git operation failed: {e}")

        finally:
            # Cleanup askpass script
            try:
                os.unlink(askpass_path)
            except OSError:
                pass

    async def _run_git_command(
        self,
        cmd: list,
        env: dict,
        cwd: Optional[str] = None
    ) -> str:
        """
        Run git command with error handling.

        Args:
            cmd: Git command and arguments
            env: Environment variables
            cwd: Working directory

        Returns:
            Command output

        Raises:
            PRCloneException: If command fails
        """
        self.logger.debug(f"Running git command: {' '.join(cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_output = stderr.decode('utf-8', errors='replace')
            raise PRCloneException(
                f"Git command failed: {' '.join(cmd)}\n{error_output}"
            )

        return stdout.decode('utf-8', errors='replace').strip()

    async def _validate_clone_integrity(
        self,
        clone_path: str,
        expected_sha: str
    ) -> bool:
        """
        Validate that cloned repository is at the expected SHA.

        Args:
            clone_path: Path to cloned repository
            expected_sha: Expected commit SHA

        Returns:
            True if validation passes

        Raises:
            SHAValidationException: If SHA doesn't match
            PRCloneException: If validation fails
        """
        try:
            # Get current commit SHA
            process = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "HEAD",
                cwd=clone_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise PRCloneException(f"Failed to get current SHA: {stderr.decode()}")

            actual_sha = stdout.decode().strip()

            if actual_sha != expected_sha:
                raise SHAValidationException(expected_sha, actual_sha)

            self.logger.debug(f"SHA validation passed: {actual_sha}")
            return True

        except SHAValidationException:
            raise
        except Exception as e:
            raise PRCloneException(f"Clone integrity validation failed: {e}")

    def _validate_resource_usage(self, size_bytes: int) -> None:
        """
        Validate clone size against resource limits.

        Args:
            size_bytes: Clone directory size in bytes

        Raises:
            CloneResourceExhaustedException: If limits exceeded
        """
        # Get size limits from config (convert MB to bytes)
        max_size_mb = getattr(pr_review_settings.limits, 'max_clone_size_mb', 1000)
        max_size_bytes = max_size_mb * 1024 * 1024

        if size_bytes > max_size_bytes:
            actual_mb = size_bytes / 1024 / 1024
            raise CloneResourceExhaustedException(
                "disk space",
                f"{actual_mb:.1f}MB exceeds limit of {max_size_mb}MB"
            )

    def _get_directory_size(self, directory_path: str) -> int:
        """
        Calculate total size of directory in bytes.

        Args:
            directory_path: Path to directory

        Returns:
            Total size in bytes
        """
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(directory_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    if os.path.exists(filepath):
                        total_size += os.path.getsize(filepath)
        except OSError as e:
            self.logger.warning(f"Error calculating directory size: {e}")
        return total_size

    def _validate_sha_format(self, sha: str) -> bool:
        """
        Validate SHA format (40 character hexadecimal).

        Args:
            sha: SHA string to validate

        Returns:
            True if valid format
        """
        if not sha or len(sha) != 40:
            return False

        try:
            int(sha, 16)
            return True
        except ValueError:
            return False

    async def cleanup_clone(self, clone_path: str) -> None:
        """
        Safely cleanup cloned repository directory.

        Args:
            clone_path: Path to clone directory to cleanup
        """
        if not clone_path or not Path(clone_path).exists():
            return

        try:
            # Remove read-only permissions that git might set
            await self._make_writable_recursive(clone_path)

            # Remove directory tree
            shutil.rmtree(clone_path, ignore_errors=True)

            self.logger.debug(f"Cleaned up clone directory: {clone_path}")

        except Exception as e:
            self.logger.warning(f"Error during clone cleanup: {e}")

    async def _make_writable_recursive(self, path: str) -> None:
        """
        Recursively make directory tree writable for cleanup.

        Args:
            path: Root path to make writable
        """
        try:
            for root, dirs, files in os.walk(path):
                # Make directories writable
                for dir_name in dirs:
                    dir_path = os.path.join(root, dir_name)
                    try:
                        os.chmod(dir_path, 0o755)
                    except OSError:
                        pass

                # Make files writable
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    try:
                        os.chmod(file_path, 0o644)
                    except OSError:
                        pass

        except Exception as e:
            self.logger.debug(f"Error making files writable: {e}")

    @asynccontextmanager
    async def temporary_clone(
        self,
        repo_name: str,
        head_sha: str,
        installation_id: int,
        timeout_seconds: Optional[int] = None
    ):
        """
        Context manager for temporary PR head clone with guaranteed cleanup.

        Args:
            repo_name: Repository name in format "owner/repo"
            head_sha: Specific commit SHA to clone
            installation_id: GitHub installation ID for authentication
            timeout_seconds: Optional timeout override

        Yields:
            Path to cloned directory

        Example:
            async with clone_service.temporary_clone("owner/repo", sha, install_id) as clone_path:
                # Use cloned repository
                pass
            # Directory automatically cleaned up
        """
        clone_path = None
        try:
            clone_path = await self.clone_pr_head(
                repo_name, head_sha, installation_id, timeout_seconds
            )
            yield clone_path
        finally:
            if clone_path:
                await self.cleanup_clone(clone_path)

    async def get_clone_info(self, clone_path: str) -> Dict[str, Any]:
        """
        Get information about a cloned repository.

        Args:
            clone_path: Path to clone directory

        Returns:
            Dictionary with clone information
        """
        if not Path(clone_path).exists():
            return {"exists": False}

        try:
            # Get current commit info
            process = await asyncio.create_subprocess_exec(
                "git", "log", "--format=%H|%s|%an|%ae|%ad", "-1",
                cwd=clone_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                commit_info = stdout.decode().strip().split('|')
                if len(commit_info) >= 5:
                    return {
                        "exists": True,
                        "current_sha": commit_info[0],
                        "commit_message": commit_info[1],
                        "author_name": commit_info[2],
                        "author_email": commit_info[3],
                        "commit_date": commit_info[4],
                        "size_bytes": self._get_directory_size(clone_path)
                    }

            return {
                "exists": True,
                "size_bytes": self._get_directory_size(clone_path)
            }

        except Exception as e:
            self.logger.warning(f"Error getting clone info: {e}")
            return {
                "exists": True,
                "error": str(e),
                "size_bytes": self._get_directory_size(clone_path)
            }