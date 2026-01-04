from pydantic import BaseModel

class Repository(BaseModel):
    github_repo_name: str  # e.g., "owner/repo"
    github_repo_id: int
    repo_id: str
    repo_url: str
    commit_sha: str | None = None  # Optional - if not provided, will use branch name
    default_branch: str = "main"

class IndexRepoRequest(BaseModel):
    """Request model for repository indexing."""
    installation_id: int
    repositories: list[Repository]