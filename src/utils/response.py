from pydantic import BaseModel
from typing import List


class IndexRepoResponseItem(BaseModel):
    """Response item for a single repository indexing."""
    workflow_id: str
    run_id: str
    message: str
    repo_name: str


class IndexRepoResponse(BaseModel):
    """Response model for repository indexing."""
    repositories: List[IndexRepoResponseItem]
    total_count: int