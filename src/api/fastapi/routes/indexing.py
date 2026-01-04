from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException
from temporalio.client import Client
from src.api.fastapi.middlewares.auth import get_current_user
from src.core.temporal_client import temporal_client
from src.models.db.users import User
from src.utils.response import IndexRepoResponse, IndexRepoResponseItem
from src.utils.requests import IndexRepoRequest
from src.workflows.repo_indexing_workflow import RepoIndexingWorkflow

router = APIRouter()

@router.post("/index", response_model = IndexRepoResponse)
async def index_repo(
    repo_request: IndexRepoRequest,
    temporal_client: Client = Depends(temporal_client.get_client),
    current_user: User = Depends(get_current_user)
):
    """
    Trigger repository indexing workflows for multiple repositories.
    
    This endpoint:
    1. Validates user has access to the installation
    2. Starts a Temporal workflow for each repository in the list
    3. Returns workflow handles for tracking all started workflows
    """
    
    try:
        repo_list = repo_request.repositories
        responses = []
        
        for repo in repo_list:
            workflow_id = f"repo-index-{repo.github_repo_id}-{repo.default_branch}"
            input = {
                "installation_id": repo_request.installation_id,
                "repository": repo.model_dump(mode="json"),
            }
            handle = await temporal_client.start_workflow(
                RepoIndexingWorkflow.run,
                input,
                id=workflow_id,
                task_queue="repo-indexing-queue",
            )
            responses.append(
                IndexRepoResponseItem(
                    workflow_id=handle.id,
                    run_id=str(handle.first_execution_run_id or ""),
                    message=f"Indexing started for repository {repo.github_repo_name}",
                    repo_name=repo.github_repo_name
                )
            )
        
        return IndexRepoResponse(
            repositories=responses,
            total_count=len(responses)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to index repositories: {str(e)}")
    
