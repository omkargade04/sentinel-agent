from datetime import timedelta
from temporalio.common import RetryPolicy
from src.activities.repo_indexing_activity import RepoIndexingActivity
from src.core.temporal_client import get_temporal_client
from temporalio import workflow

from src.models.schemas.repositories import RepoRequest


@workflow.defn
class RepoIndexingWorkflow:
       
    @workflow.run
    async def run(self, repo_request: RepoRequest):
        # Retry policy
        retry_policy = RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=10),
            maximum_interval=timedelta(seconds=30),
            backoff_coefficient=2.0,
        )
        
        # Step 1: Clone the repo
        local_path = await workflow.execute_activity(
            self.repo_indexing_activity.clone_repo,
            repo_request,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy
        )
        
        # Step 2: Parse the repo - symbols/AST
        symbols = await workflow.execute_activity(
            self.repo_indexing_activity.parse_repo,
            local_path,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy
        )
        
        # Step 3: Index the symbols - Store embeddings
        await workflow.execute_activity(
            self.repo_indexing_activity.index_symbols,
            symbols,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy
        )
        
        return f"Repo {repo_request.github_repo_name} indexed successfully"
        
    