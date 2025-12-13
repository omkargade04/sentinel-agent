import datetime
from datetime import timezone
from typing import Any, Dict, List, Optional
from uuid import UUID
from fastapi import Depends
from sqlalchemy.orm import Session
from src.core.database import get_db
from src.models.db.github_installations import GithubInstallation
from src.models.db.repositories import Repository
from src.models.schemas.github_installations import InstallationEvent, GitHubRepository
from src.utils.exception import (
    AppException,
    DuplicateResourceException,
    InstallationNotFoundError,
)
from src.utils.logging.otel_logger import logger
from sqlalchemy.exc import SQLAlchemyError


class InstallationService:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    def process_installation_created(self, payload: Dict[str, Any]) -> None:
        """
        Process the 'installation' event from GitHub when a new app installation is created.
        This method handles the creation of a new installation record and the processing
        of associated repositories.
        """
        installation: dict[str, Any] = payload.get("installation")
        installation_id: int = installation.get("id")
        account: dict[str, Any] = installation.get("account")
        existing_installation = (
            self.db.query(GithubInstallation)
            .filter(GithubInstallation.installation_id == installation_id)
            .first()
        )

        if existing_installation:
            logger.warning(
                f"Installation with ID {installation_id} already exists. Updating if necessary."
            )
            existing_installation.updated_at = datetime.datetime.now(timezone.utc)
        else:
            try:
                new_installation = GithubInstallation(
                    installation_id=installation_id,
                    user_id=None,
                    github_account_id=account.get("id"),
                    github_account_username=account.get("login"),
                    github_account_type=account.get("type"),
                    created_at=datetime.datetime.now(timezone.utc),
                    updated_at=datetime.datetime.now(timezone.utc),
                )
                self.db.add(new_installation)
                self.db.flush()
                logger.info(f"New installation created with ID: {new_installation.id}")

            except SQLAlchemyError as e:
                self.db.rollback()
                logger.error(
                    f"Database error while creating installation for ID {installation_id}: {e}"
                )
                raise AppException(
                    status_code=500, message="Failed to create installation record."
                )

        repositories: Optional[List[GitHubRepository]] = payload.get("repositories")
        logger.info(f"Repositories: {repositories}")
        if repositories:
            self._process_repositories(
                installation_id, repositories, "added"
            )
        
        self.db.commit()

    def process_installation_deleted(self, payload: Dict[str, Any]) -> None:
        """
        Process the 'installation' event from GitHub when an app installation is deleted.
        This method deactivates the installation and all associated repositories.
        """
        installation = payload.get("installation")
        installation_id = installation.get("id")
        installation = (
            self.db.query(GithubInstallation)
            .filter(GithubInstallation.installation_id == installation_id)
            .first()
        )

        if not installation:
            raise InstallationNotFoundError(
                f"Attempted to delete a non-existent installation with ID {installation_id}"
            )

        try:
            # Update the installation timestamp for deletion tracking
            installation.updated_at = datetime.datetime.now(timezone.utc)

            # For repositories, we'll just log the deletion for now
            # since the Repository model doesn't have is_active field
            repos = self.db.query(Repository).filter(
                Repository.installation_id == installation.installation_id
            ).all()
            
            for repo in repos:
                logger.info(f"Installation deleted - repository affected: {repo.full_name}")
                # TODO: Implement repository cleanup logic based on business requirements

            self.db.commit()
            logger.info(
                f"Installation with ID {installation_id} has been processed for deletion."
            )
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(
                f"Database error while deactivating installation {installation_id}: {e}"
            )
            raise AppException(
                status_code=500, message="Failed to deactivate installation."
            )

    def process_repositories_changed(self, payload: Dict[str, Any]) -> None:
        """
        Process the 'installation_repositories' event from GitHub when repositories are
        added or removed from an installation.
        """
        installation = payload.get("installation")
        installation_id = installation.get("id")
        installation = (
            self.db.query(GithubInstallation)
            .filter(GithubInstallation.installation_id == installation_id)
            .first()
        )

        if not installation:
            raise InstallationNotFoundError(
                f"Received repository change event for non-existent installation ID {installation_id}"
            )
        
        try:
            repositories_added = payload.get("repositories_added")
            repositories_removed = payload.get("repositories_removed")
            
            if repositories_added:
                self._process_repositories(
                    installation_id, repositories_added, "added"
                )
            if repositories_removed:
                self._process_repositories(
                    installation_id, repositories_removed, "removed"
                )
            self.db.commit()
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"Database error during repository change processing for installation {installation_id}: {e}")
            raise AppException(status_code=500, message="Failed to process repository changes.")


    def _process_repositories(
        self,
        installation_id: int,
        repo_list: List[GitHubRepository],
        action: str,
    ) -> None:
        """
        A helper method to add or remove repositories associated with an installation.
        This method is designed to be called within a larger transaction.
        """
        logger.info(f"Processing repositories")
        installation = (
            self.db.query(GithubInstallation)
            .filter(GithubInstallation.installation_id == installation_id)
            .first()
        )
        if not installation:
            raise InstallationNotFoundError(
                f"Cannot process repositories for non-existent installation ID {installation_id}"
            )
        logger.info(f"installation: {installation}")
        for repo_data in repo_list:
            logger.info(f"repo_data: {repo_data}")
            github_repo_id = repo_data.get('id')
            repo = (
                self.db.query(Repository)
                .filter(Repository.github_repo_id == github_repo_id)
                .first()
            )
            logger.info(f"repo: {repo}")
            if action == "added":
                if repo:
                    # Repository already exists, just update timestamp
                    repo.updated_at = datetime.datetime.now(timezone.utc)
                    logger.info(f"Updated existing repository: {repo_data.get('full_name')}")
                else:
                    new_repo = Repository(
                        installation_id=installation.installation_id,  # Use installation_id not id
                        github_repo_id=github_repo_id,
                        github_repo_name=repo_data.get('name'),
                        full_name=repo_data.get('full_name'),
                        private=repo_data.get('private', False),
                        default_branch=repo_data.get('default_branch', 'main'),
                        created_at=datetime.datetime.now(timezone.utc),
                        updated_at=datetime.datetime.now(timezone.utc),
                    )
                    self.db.add(new_repo)
                    logger.info(f"Added new repository: {repo_data.get('full_name')}")
            
            elif action == "removed":
                if repo:
                    # For removal, we could delete the repo or mark it somehow
                    # Since there's no is_active field, we'll just log for now
                    logger.info(f"Repository removal requested: {repo_data.get('full_name')}")
                    # TODO: Implement repository removal logic based on business requirements
                else:
                    logger.warning(
                        f"Received request to remove a repository that does not exist in DB: {repo_data.get('full_name')}"
                    )