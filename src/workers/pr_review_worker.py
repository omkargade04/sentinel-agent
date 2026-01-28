import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from src.utils.logging.otel_logger import logger
from src.workflows.pr_review_workflow import PRReviewWorkflow
from src.activities.pr_review_activities import (
    fetch_pr_context_activity,
    clone_pr_head_activity,
    build_seed_set_activity,
    retrieve_kg_candidates_activity,
    retrieve_and_assemble_context_activity,
    generate_review_activity,
    persist_pr_review_metadata_activity,
    anchor_and_publish_activity,
    cleanup_pr_clone_activity,
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
        task_queue="pr-review-pipeline",
        workflows=[PRReviewWorkflow],
        activities=[
            fetch_pr_context_activity,
            clone_pr_head_activity,
            build_seed_set_activity,
            retrieve_kg_candidates_activity,
            retrieve_and_assemble_context_activity,
            generate_review_activity,
            persist_pr_review_metadata_activity,
            anchor_and_publish_activity,
            cleanup_pr_clone_activity,
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