from pydantic import BaseModel


class IndexRepoResponse(BaseModel):
    """Response model for repository indexing."""
    workflow_id: str
    run_id: str
    message: str