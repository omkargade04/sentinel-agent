from src.models.db.users import User
from src.models.db.repositories import Repository
from src.utils.logging.otel_logger import logger
from typing import Dict, Any, List
from sqlalchemy.exc import SQLAlchemyError
import httpx
from src.services.repository.helpers import RepositoryHelpers
from src.utils.exception import AppException, UserNotFoundError


class RepositoryService:
    def __init__(self):
        self.helpers = RepositoryHelpers()

    async def get_all_repositories(self, current_user: User) -> List[Dict[str, Any]]:
        """Get a list of all repositories from GitHub for the user's installation."""
        if not current_user.github_installations:
            raise UserNotFoundError("No GitHub installation found for the current user.")
            
        installation_id = current_user.github_installations[0].installation_id
        try:
            installation_token = await self.helpers.generate_installation_token(installation_id)
            repositories = await self._fetch_all_repositories_from_github(installation_token)
            return repositories
            
        except Exception as e:
            logger.error(f"Error getting all repositories for user {current_user.email}: {str(e)}")
            if not isinstance(e, AppException):
                raise AppException(status_code=500, message="An unexpected error occurred while fetching repositories.")
            raise e
        
    async def _fetch_all_repositories_from_github(self, installation_token: str) -> List[Dict[str, Any]]:
        """Get a list of all repositories from the GitHub API."""
        repos_url = "https://api.github.com/installation/repositories"
        
        async with httpx.AsyncClient() as client:
            headers = {
                "Authorization": f"Bearer {installation_token}",
                "Accept": "application/vnd.github+json"
            }
            response = await client.get(repos_url, headers=headers)
            
            if response.status_code != 200:
                logger.error(f"Failed to get all repositories from GitHub API: {response.status_code} {response.text}")
                raise AppException(
                    status_code=response.status_code,
                    message="Failed to fetch repositories from GitHub."
                )
            
            repositories_data = response.json()
            return repositories_data.get("repositories", [])
        
    async def get_user_selected_repositories(self, current_user: User) -> List[Repository]:
        """Get a list of user's repositories from our database."""
        if not current_user.github_installations:
            raise UserNotFoundError("No GitHub installation found for the current user.")
            
        installation_id = current_user.github_installations[0].installation_id
        try:
            result = self.db.query(Repository).filter(Repository.installation_id == installation_id).all()
            return result
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"Database error getting repositories for user {current_user.email}: {str(e)}")
            raise AppException(status_code=500, message="A database error occurred while fetching repositories.")
        except Exception as e:
            logger.error(f"Unexpected error getting repositories for user {current_user.email}: {str(e)}")
            raise AppException(status_code=500, message="An unexpected error occurred while fetching repositories.")