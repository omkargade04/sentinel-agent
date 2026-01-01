from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException
from temporalio.client import Client
from src.api.fastapi.middlewares.auth import get_current_user
from src.core.temporal_client import get_temporal_client
from src.models.db.users import User
from src.utils.response import IndexRepoResponse
from src.utils.requests import IndexRepoRequest
from src.workflows.repo_indexing_workflow import RepoIndexingWorkflow

router = APIRouter()

@router.post("/index", response_model = IndexRepoResponse)
async def index_repo(
    repo_request: IndexRepoRequest,
    temporal_client: Client = Depends(get_temporal_client),
    current_user: User = Depends(get_current_user)
):
    """
    Trigger repository indexing workflow.
    
    This endpoint:
    1. Validates user has access to the installation
    2. Starts a Temporal workflow for indexing
    3. Returns workflow handle for tracking
    """
    
    workflow_id = f"repo-index-{repo_request.repo_id}-{repo_request.default_branch}"
    try:
        handle = await temporal_client.start_workflow(
            RepoIndexingWorkflow.run,
            repo_request.model_dump(mode="json"),
            id=workflow_id,
            task_queue="repo-indexing-queue",
        )
        return IndexRepoResponse(
            workflow_id=handle.id,
            run_id=str(handle.first_execution_run_id or ""),
            message=f"Indexing started for repository {repo_request.github_repo_name}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to index repository: {str(e)}")
    
