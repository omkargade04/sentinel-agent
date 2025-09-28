from typing import Dict, Any, List
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.models.db.github_installations import GithubInstallation
from src.models.db.repositories import Repository
from src.core.database import SessionLocal
from src.utils.logging.otel_logger import logger

class InstallationService:
    def __init__(self):
        pass
    
    async def process_installation_created(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Process installation created webhook"""
        db: Session = SessionLocal()
        try:
            installation_data = body["installation"]
            installation_id = installation_data["id"]
            github_account_id = installation_data["account"]["id"]
            github_account_type = installation_data["account"]["type"]
            github_account_username = installation_data["account"]["login"]
            
            repositories = body.get("repositories", [])
            
            logger.info(f"Processing installation created for account: {github_account_username}")
            
            existing_installation = db.query(GithubInstallation).filter(
                GithubInstallation.installation_id == installation_id
            ).first()
            
            if existing_installation:
                logger.warning(f"Installation {installation_id} already exists")
                return {
                    "status": "warning",
                    "message": "Installation already exists",
                    "installation_id": installation_id
                }

            github_installation = GithubInstallation(
                installation_id=installation_id,
                github_account_id=github_account_id,
                github_account_type=github_account_type,
                github_account_username=github_account_username,
                user_id=None
            )
            
            db.add(github_installation)
            db.commit()
            db.refresh(github_installation)
            
            repo_count = await self._process_repositories(db, repositories, installation_id, "add")
            
            logger.info(f"Installation {installation_id} created with {repo_count} repositories")
            
            return {
                "status": "success",
                "message": "Installation created successfully",
                "installation_id": installation_id,
                "repositories_count": repo_count
            }
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error processing installation: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        except Exception as e:
            db.rollback()
            logger.error(f"Error processing installation: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error processing installation: {str(e)}")
        finally:
            db.close()
    
    async def process_installation_deleted(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Process installation deleted webhook"""
        db: Session = SessionLocal()
        try:
            installation_id = body["installation"]["id"]
            
            logger.info(f"Processing installation deletion: {installation_id}")
            
            installation = db.query(GithubInstallation).filter(
                GithubInstallation.installation_id == installation_id
            ).first()
            
            if not installation:
                logger.warning(f"Installation {installation_id} not found for deletion")
                return {
                    "status": "warning",
                    "message": "Installation not found"
                }
            
            deleted_repos = db.query(Repository).filter(
                Repository.installation_id == installation_id
            ).delete()
            
            db.delete(installation)
            db.commit()
            
            logger.info(f"Installation {installation_id} deleted with {deleted_repos} repositories")
            
            return {
                "status": "success",
                "message": "Installation deleted successfully",
                "repositories_deleted": deleted_repos
            }
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error deleting installation: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        except Exception as e:
            db.rollback()
            logger.error(f"Error deleting installation: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error deleting installation: {str(e)}")
        finally:
            db.close()
    
    async def _process_repositories(self, db: Session, repositories: List[Dict], installation_id: int, action: str) -> int:
        """Process repositories for installation"""
        count = 0
        
        for repo_data in repositories:
            try:
                if action == "add":
                    existing_repo = db.query(Repository).filter(
                        Repository.github_repo_id == repo_data["id"]
                    ).first()
                    
                    if existing_repo:
                        logger.warning(f"Repository {repo_data['full_name']} already exists")
                        continue
                    
                    repository = Repository(
                        installation_id=installation_id,
                        github_repo_id=repo_data["id"],
                        github_repo_name=repo_data["name"],
                        full_name=repo_data["full_name"],
                        default_branch=repo_data.get("default_branch", "main"),
                        private=repo_data["private"]
                    )
                    
                    db.add(repository)
                    count += 1
                    
                elif action == "remove":
                    deleted = db.query(Repository).filter(
                        Repository.github_repo_id == repo_data["id"]
                    ).delete()
                    count += deleted
                    
            except Exception as e:
                logger.error(f"Error processing repository {repo_data.get('full_name', 'unknown')}: {str(e)}")
                continue
        
        db.commit()
        return count

class InstallationRepositoriesService:
    def __init__(self):
        pass
    
    async def process_repositories_changed(self, body: Dict[str, Any], action: str) -> Dict[str, Any]:
        """Process installation repositories added/removed webhook"""
        db: Session = SessionLocal()
        try:
            installation_id = body["installation"]["id"]
            
            logger.info(f"Processing repositories {action} for installation: {installation_id}")
            
            installation = db.query(GithubInstallation).filter(
                GithubInstallation.installation_id == installation_id
            ).first()
            
            if not installation:
                logger.error(f"Installation {installation_id} not found")
                raise HTTPException(status_code=404, detail="Installation not found")
            
            total_processed = 0
            
            if action == "added":
                repositories_added = body.get("repositories_added", [])
                installation_service = InstallationService()
                total_processed = await installation_service._process_repositories(
                    db, repositories_added, installation_id, "add"
                )
                
            elif action == "removed":
                repositories_removed = body.get("repositories_removed", [])
                installation_service = InstallationService()
                total_processed = await installation_service._process_repositories(
                    db, repositories_removed, installation_id, "remove"
                )
            
            logger.info(f"Processed {total_processed} repositories for action: {action}")
            
            return {
                "status": "success",
                "message": f"Repositories {action} successfully",
                "repositories_processed": total_processed
            }
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error processing repositories: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        except Exception as e:
            db.rollback()
            logger.error(f"Error processing repositories: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error processing repositories: {str(e)}")
        finally:
            db.close()