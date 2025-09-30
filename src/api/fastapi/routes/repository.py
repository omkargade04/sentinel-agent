from fastapi import APIRouter, Depends
from src.models.db.users import User
from src.api.fastapi.middlewares.auth import get_current_user
from src.services.repository.repository_service import RepositoryService

router = APIRouter(
    prefix = "/repository",
    tags = ["Repository"],
)

@router.get("/all")
async def get_all_repositories(
    current_user: User = Depends(get_current_user), 
    repository_service: RepositoryService = Depends(RepositoryService)
):
    """Get a list of all repositories"""
    return repository_service.get_all_repositories(current_user)

@router.get("/user-selected")
async def get_user_selected_repositories(
    current_user: User = Depends(get_current_user), 
    repository_service: RepositoryService = Depends(RepositoryService)
):
    """Get a list of user's repositories"""
    return repository_service.get_user_selected_repositories(current_user)