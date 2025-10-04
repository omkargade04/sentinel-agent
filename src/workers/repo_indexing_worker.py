import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from src.workflows.repo_indexing_workflow import RepoIndexingWorkflow
from src.activities.repo_indexing_activity import RepoIndexingActivity
from src.core.config import settings


async def main():
    activity_instance = RepoIndexingActivity()
    workflow_instance = RepoIndexingWorkflow()
    
    client = await Client.connect(
        target_host=settings.TEMPORAL_SERVER_URL,
    )
    worker = Worker(
        client,
        task_queue="repo-indexing-queue",
        workflows=[workflow_instance],
        activities=[activity_instance],
    )
    await worker.run()
    
if __name__ == "__main__":
    asyncio.run(main())