"""
Repository cloning service using git CLI with GitHub App authentication.
"""

import os
import asyncio
from pathlib import Path
import shutil
import tempfile
from typing import Dict

from src.services.repository.helpers import RepositoryHelpers
from src.utils.exception import RepoCloneError


class RepoCloneService:
    """
    Service for cloning GitHub repositories.
    
    Uses git CLI with GIT_ASKPASS for secure token handling.
    Clones to deterministic paths: /tmp/{repo_id}-{commit_sha}
    Handles concurrent clones with atomic directory creation.
    """
    def __init__(self):
        self.helpers = RepositoryHelpers()
    
    async def clone_repo(
        self,
        *,
        repo_full_name: str,
        github_repo_id: int,
        repo_id: str,
        installation_id: int,
        default_branch: str,
        repo_url: str,
        commit_sha: str | None = None,
    ) -> Dict[str, str]:
        """
        Clone repository and return local path.
        
        Args:
            repo_full_name: e.g., "owner/repo"
            github_repo_id: GitHub repository ID
            repo_id: Internal repo identifier
            installation_id: GitHub App installation ID
            default_branch: Branch name to clone
            repo_url: Repository URL (optional, used for validation)
            commit_sha: Optional commit SHA. If not provided, will resolve from branch.
                        If resolution fails, will use branch name in path.
        
        Returns:
            {
                "local_path": "/tmp/{repo_id}-{identifier}",
                "commit_sha": "abc123..." or None
            }
        
        Raises:
            RepoCloneError: If cloning fails
        """
        # Mint installation token
        token = await self.helpers.generate_installation_token(installation_id)
        
        # Resolve commit SHA if not provided
        resolved_commit_sha = commit_sha
        if not resolved_commit_sha:
            try:
                resolved_commit_sha = await self._resolve_commit_sha(
                    repo_full_name, default_branch, token, repo_url
                )
            except Exception as e:
                # If resolution fails, log warning and continue with branch name
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Failed to resolve commit SHA for {repo_full_name}@{default_branch}: {e}. "
                    f"Continuing with branch name as identifier."
                )
                resolved_commit_sha = None
        
        # Use commit SHA if available, otherwise use branch name
        identifier = resolved_commit_sha or default_branch
        local_path = f"/tmp/{repo_id}-{identifier}"
        
        # Check if already exists (concurrent execution or cached)
        if Path(local_path).exists():
            return {"local_path": local_path, "commit_sha": resolved_commit_sha}
        
        # Clone with atomic staging
        temp_path = f"{local_path}.tmp-{os.getpid()}"
        try:
            await self._clone_repository(
                repo_full_name=repo_full_name,
                commit_sha=resolved_commit_sha,
                branch=default_branch,
                temp_path=temp_path,
                token=token,
                repo_url=repo_url,
            )
            
            # Atomic rename
            os.rename(temp_path, local_path)
            
            return {"local_path": local_path, "commit_sha": resolved_commit_sha}
        except Exception as e:
            # Cleanup temp dir on failure
            if Path(temp_path).exists():
                shutil.rmtree(temp_path, ignore_errors=True)
            raise RepoCloneError(f"Failed to clone {repo_full_name}: {e}") from e
    
    async def _resolve_commit_sha(
        self,
        repo_full_name: str,
        default_branch: str,
        token: str,
        repo_url: str,
    ) -> str:
        """Resolve branch name to commit SHA using git ls-remote."""
        if not repo_url:
            repo_url = f"https://github.com/{repo_full_name}.git"
            
        # Create temp askpass script
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write('#!/bin/sh\n')
            f.write(f'echo "x-access-token:${token}"\n')
            askpass_path = f.name
            
        os.chmod(askpass_path, 0o700)
        
        try:
            env = os.environ.copy()
            env["GIT_ASKPASS"] = askpass_path
            env["GIT_TERMINAL_PROMPT"] = "0"
            
            cmd = ["git", "ls-remote", repo_url, f"refs/heads/{default_branch}"]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd, 
                env=env, 
                stdout=asyncio.subprocess.PIPE, 
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RepoCloneError(
                    f"git ls-remote failed: {stderr.decode()}"
                )
            # Parse output: "abc123... refs/heads/main"
            line = stdout.decode().strip()
            if not line:
                raise RepoCloneError(f"Branch {default_branch} not found")
            
            commit_sha = line.split()[0]
            return commit_sha
                
        finally:
            os.unlink(askpass_path)
            
    async def _clone_repository(
        self,
        repo_full_name: str,
        commit_sha: str | None,
        branch: str,
        temp_path: str,
        token: str,
        repo_url: str,
    ) -> None:
        """Execute git clone using shallow fetch.
        
        Args:
            repo_full_name: Repository full name (owner/repo)
            commit_sha: Optional commit SHA. If provided, fetches specific commit.
            branch: Branch name to use if commit_sha is None
            temp_path: Temporary directory path for clone
            token: GitHub access token
            repo_url: Repository URL
        """
        if not repo_url:
            repo_url = f"https://github.com/{repo_full_name}.git"
            
        # Create temporary askpass script
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write('#!/bin/sh\n')
            f.write(f'echo "x-access-token:{token}"\n')
            askpass_path = f.name
        
        os.chmod(askpass_path, 0o700)
        
        try:
            env = os.environ.copy()
            env["GIT_ASKPASS"] = askpass_path
            env["GIT_TERMINAL_PROMPT"] = "0"
            
            # Git init
            await self._run_git_cmd(["git", "init", temp_path], env)
            
            # Add remote
            await self._run_git_cmd(["git", "remote", "add", "origin", repo_url], env, cwd=temp_path)

            if commit_sha:
                # Shallow fetch specific commit
                await self._run_git_cmd(
                    ["git", "fetch", "--depth", "1", "origin", commit_sha],
                    env,
                    cwd=temp_path,
                )
                
                    # Checkout detached at commit
                await self._run_git_cmd(
                    ["git", "checkout", "--detach", commit_sha],
                    env,
                    cwd=temp_path,
                )
            else:
                # Fetch branch instead - try the requested branch first
                try:
                    await self._run_git_cmd(
                        ["git", "fetch", "--depth", "1", "origin", f"refs/heads/{branch}"],
                        env,
                        cwd=temp_path,
                    )
                    # Create local branch tracking remote branch
                    await self._run_git_cmd(
                        ["git", "checkout", "-b", branch, f"origin/{branch}"],
                        env,
                        cwd=temp_path,
                    )
                except RepoCloneError as e:
                    # Branch might not exist, try to detect default branch
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(
                        f"Branch '{branch}' not found for {repo_full_name}. "
                        f"Attempting to detect default branch..."
                    )
                    
                    # Try to get default branch from remote HEAD
                    try:
                        await self._run_git_cmd(
                            ["git", "fetch", "--depth", "1", "origin", "HEAD"],
                            env,
                            cwd=temp_path,
                        )
                        # Checkout whatever HEAD points to
                        await self._run_git_cmd(
                            ["git", "checkout", "FETCH_HEAD"],
                            env,
                            cwd=temp_path,
                        )
                        logger.info(f"Successfully checked out default branch for {repo_full_name}")
                    except RepoCloneError as e2:
                        # If that also fails, raise original error
                        raise RepoCloneError(
                            f"Failed to clone branch '{branch}' for {repo_full_name}. "
                            f"Branch not found and could not detect default branch: {e2}"
                        ) from e
        finally:
            os.unlink(askpass_path)
            
    async def _run_git_cmd(self, cmd: list, env: dict, cwd: str = None) -> None:
         """Run git command with error handling."""
         
         proc = await asyncio.create_subprocess_exec(
             *cmd,
             env=env,
             stdout=asyncio.subprocess.PIPE,
             stderr=asyncio.subprocess.PIPE,
             cwd=cwd,
         )
         
         stdout, stderr = await proc.communicate()
         if proc.returncode != 0:
             raise RepoCloneError(
                f"Git command failed: {' '.join(cmd)}\n{stderr.decode()}"
            )
         return stdout.decode().strip()
     
    async def cleanup_repo(self, *, local_path: str) -> None:
        """Delete cloned repository directory."""
        if Path(local_path).exists():
            shutil.rmtree(local_path, ignore_errors=True)
        