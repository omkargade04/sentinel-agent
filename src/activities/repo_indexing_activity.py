from typing import List
from src.models.schemas.symbols import Symbol
from temporalio import activity

@activity.defn
class RepoIndexingActivity:
        
    @activity.defn
    async def clone_repo(self, repo_request: dict):
        # Clone the repo
        activity.logger.info(f"Cloning repo: {repo_request.github_repo_name}")
        local_path = f"/tmp/{repo_request.github_repo_name.replace('/', '-')}"
        return local_path
    
    @activity.defn
    async def parse_repo(self, local_path: str):
        # Parse the repo - symbols/AST
        activity.logger.info(f"Parsing repo: {local_path}")
        symbols = []
        return symbols
    
    @activity.defn
    async def index_symbols(self, symbols: List[Symbol]):
        # Index the symbols - Store embeddings
        activity.logger.info(f"Indexing {len(symbols)} symbols.")
        pass