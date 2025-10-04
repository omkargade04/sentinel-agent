from ast import List
from src.models.schemas.symbols import Symbol
from temporalio import activity
from src.models.schemas.repositories import RepoRequest

@activity.defn
class RepoIndexingActivity:
        
    async def clone_repo(self, repo_request: RepoRequest):
        # Clone the repo
        activity.logger.info(f"Cloning repo: {repo_request.github_repo_name}")
        local_path = f"/tmp/{repo_request.github_repo_name.replace('/', '-')}"
        return local_path
    
    async def parse_repo(self, local_path: str):
        # Parse the repo - symbols/AST
        activity.logger.info(f"Parsing repo: {local_path}")
        symbols = []
        return symbols
    
    async def index_symbols(self, symbols: List[Symbol]):
        # Index the symbols - Store embeddings
        activity.logger.info(f"Indexing {len(symbols)} symbols.")
        pass