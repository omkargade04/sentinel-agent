from fastapi import APIRouter, Depends
from temporalio.client import Client
from src.core.temporal_client import get_temporal_client
from src.workflows.repo_indexing_workflow import RepoIndexingWorkflow

router = APIRouter()

@router.post("/index-repo")
async def index_repo(
    repo_request: dict,
    temporal_client: Client = Depends(get_temporal_client)
):
    id = f"repo-index-{repo_request.github_repo_name.replace('/', '-')}"
    handle = await temporal_client.start_workflow(
        RepoIndexingWorkflow.run,
        repo_request,
        id=id,
        task_queue="repo-indexing-queue",
    )
    return {"workflow_id": handle.id, "run_id": handle.run_id}
