import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from src.utils.logging.otel_logger import logger
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
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions


async def main():
    target_host=settings.TEMPORAL_SERVER_URL
    client = await Client.connect(
        target_host=target_host,
        namespace='default'
    )
    # Create custom sandbox restrictions with passthrough modules
    # These modules do I/O at import time (read .env files, create thread locals, etc.)
    # but are not actually used inside workflow code - only in activities
    restrictions = SandboxRestrictions.default.with_passthrough_modules(
        "pydantic_settings",
        "dotenv",
        "httpx",
        "sniffio",
        "src",  # Pass through entire src package - activities do I/O, workflows don't
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
        workflow_runner=SandboxedWorkflowRunner(restrictions=restrictions),
    )
    logger.info("Temporal worker started")
    logger.info(f"Connected to temporal host ${target_host}. Polling for task queue ${worker.task_queue}")
    try:
        await worker.run()
    except Exception as e:
        logger.error(f"Error starting temporal worker: {e}")
        raise
    
if __name__ == "__main__":
    asyncio.run(main())