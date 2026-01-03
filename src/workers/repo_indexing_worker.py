import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from src.workflows.repo_indexing_workflow import RepoIndexingWorkflow
from src.activities.indexing_activities import (
    clone_repo_activity,
    parse_repo_activity,
    persist_metadata_activity,
    persist_kg_activity,
    cleanup_repo_activity,
    cleanup_stale_kg_nodes_activity,
)
from src.core.config import settings


async def main():
    client = await Client.connect(
        target_host=settings.TEMPORAL_SERVER_URL,
    )
    worker = Worker(
        client,
        task_queue="repo-indexing-queue",
        workflows=[RepoIndexingWorkflow],
        activities=[
            clone_repo_activity,
            parse_repo_activity,
            persist_metadata_activity,
            persist_kg_activity,
            cleanup_stale_kg_nodes_activity,
            cleanup_repo_activity,
        ],
    )
    await worker.run()
    
if __name__ == "__main__":
    asyncio.run(main())