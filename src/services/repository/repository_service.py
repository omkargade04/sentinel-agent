from src.models.db.users import User
from src.models.db.repositories import Repository
from src.utils.logging.otel_logger import logger
from typing import Dict, Any, List
from sqlalchemy.exc import SQLAlchemyError
import httpx
from src.services.repository.helpers import RepositoryHelpers


class RepositoryService:
    def __init__(self):
        self.helpers = RepositoryHelpers()

    async def get_all_repositories(self, current_user: User) -> Dict[str, Any]:
        """Get a list of all repositories"""
        installation_id = current_user.github_installations[0].installation_id
        try:
            installation_token = await self.helpers.generate_installation_token(installation_id)
            repositories = await self._get_all_repositories(installation_token)
            return {
                "status": "success",
                "message": f"All repositories fetched successfully",
                "repositories": repositories
            }
        except Exception as e:
            logger.error(f"Error getting all repositories for user {current_user.email}: {str(e)}")
            return {
                "status": "error",
                "message": f"Error getting all repositories for user {current_user.email}: {str(e)}",
                "repositories": []
            }
        
    async def _get_all_repositories(self, installation_token: int) -> List[Dict[str, Any]]:
        """Get a list of all repositories"""
        repos_url = f"https://api.github.com/installation/repositories"
        
        try:
            async with httpx.AsyncClient() as client:
                headers = {
                    "Authorization": f"Bearer {installation_token}",
                    "Accept": "application/vnd.github+json"
                }
                response = await client.get(repos_url, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"Failed to get all repositories: {response.status_code} {response.text}")
                    raise Exception(f"Failed to get all repositories: {response.status_code} {response.text}")
                
                repositories = response.json()
                return {
                    "status": "success",
                    "message": f"All repositories fetched successfully",
                    "repositories": repositories
                }
        except Exception as e:
            logger.error(f"Error getting all repositories: {str(e)}")
            return {
                "status": "error",
                "message": f"Failed to get all repositories: {str(e)}",
                "repositories": []
            }
        
    async def get_user_selected_repositories(self, current_user: User) -> Dict[str, Any]:
        """Get a list of user's repositories"""
        installation_id = current_user.github_installations[0].installation_id
        try:
            result = self.db.query(Repository).filter(Repository.installation_id == installation_id).all()
            return {
                "status": "success",
                "message": f"Repositories fetched successfully",
                "repositories": result
            }
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"Error getting repositories for user {current_user.email}: {str(e)}")
            return {
                "status": "error",
                "message": f"Error getting repositories for user {current_user.email}: {str(e)}",
                "repositories": []
            }
        except Exception as e:
            logger.error(f"Error getting repositories for user {current_user.email}: {str(e)}")
            return {
                "status": "error",
                "message": f"Error getting repositories for user {current_user.email}: {str(e)}",
                "repositories": []
            }