"""
Repository parsing service using Tree-sitter.
"""

from pathlib import Path
from src.graph.repo_graph_builder import RepoGraphBuilder
from src.models.graph.repo_graph_result import RepoGraphResult


class RepoParsingService:
    """Parse repository and build in-memory knowledge graph."""
    
    async def parse_repository(
        self,
        *,
        local_path: str,
        repo_id: str,
        commit_sha: str,
    ) -> RepoGraphResult:
        """
        Parse repository using Tree-sitter and build knowledge graph.
        
        Args:
            local_path: Path to cloned repository
            repo_id: Internal repo identifier
            commit_sha: Exact commit SHA
        
        Returns:
            RepoGraphResult with nodes, edges, stats
        """
        repo_path = Path(local_path)
        
        if not repo_path.exists():
            raise FileNotFoundError(f"Repository not found at {local_path}")
        
        # Use RepoGraphBuilder
        builder = RepoGraphBuilder(repo_id=repo_id, commit_sha=commit_sha, repo_root=repo_path)
        # Note: build() is synchronous, not async
        graph_result = builder.build()
        
        return graph_result