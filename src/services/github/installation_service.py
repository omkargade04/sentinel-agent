import datetime
from datetime import timezone
from typing import List
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

    def process_installation_created(self, payload: InstallationEvent) -> None:
        """
        Process the 'installation' event from GitHub when a new app installation is created.
        This method handles the creation of a new installation record and the processing
        of associated repositories.
        """
        installation_id = payload.installation.id
        existing_installation = (
            self.db.query(GithubInstallation)
            .filter(GithubInstallation.installation_id == installation_id)
            .first()
        )

        if existing_installation:
            logger.warning(
                f"Installation with ID {installation_id} already exists. Updating if necessary."
            )
            existing_installation.is_active = True
            existing_installation.updated_at = datetime.datetime.now(timezone.utc)
        else:
            try:
                new_installation = GithubInstallation(
                    installation_id=installation_id,
                    user_id=None,
                    github_account_id=payload.installation.account.id,
                    github_account_username=payload.installation.account.login,
                    github_account_type=payload.installation.account.type,
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

        if payload.repositories:
            self._process_repositories(
                installation_id, payload.repositories, "added"
            )
        
        self.db.commit()

    def process_installation_deleted(self, payload: InstallationEvent) -> None:
        """
        Process the 'installation' event from GitHub when an app installation is deleted.
        This method deactivates the installation and all associated repositories.
        """
        installation_id = payload.installation.id
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
            installation.is_active = False
            installation.updated_at = datetime.datetime.now(timezone.utc)

            self.db.query(Repository).filter(
                Repository.installation_id == installation.id
            ).update({"is_active": False})

            self.db.commit()
            logger.info(
                f"Installation with ID {installation_id} and its repositories have been deactivated."
            )
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(
                f"Database error while deactivating installation {installation_id}: {e}"
            )
            raise AppException(
                status_code=500, message="Failed to deactivate installation."
            )

    def process_repositories_changed(self, payload: InstallationEvent) -> None:
        """
        Process the 'installation_repositories' event from GitHub when repositories are
        added or removed from an installation.
        """
        installation_id = payload.installation.id
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
            if payload.repositories_added:
                self._process_repositories(
                    installation_id, payload.repositories_added, "added"
                )
            if payload.repositories_removed:
                self._process_repositories(
                    installation_id, payload.repositories_removed, "removed"
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
        installation = (
            self.db.query(GithubInstallation)
            .filter(GithubInstallation.installation_id == installation_id)
            .first()
        )
        if not installation:
            raise InstallationNotFoundError(
                f"Cannot process repositories for non-existent installation ID {installation_id}"
            )

        for repo_data in repo_list:
            github_repo_id = repo_data.id
            repo = (
                self.db.query(Repository)
                .filter(Repository.github_repo_id == github_repo_id)
                .first()
            )

            if action == "added":
                if repo:
                    if not repo.is_active:
                        repo.is_active = True
                        repo.updated_at = datetime.datetime.now(timezone.utc)
                        logger.info(f"Re-activated existing repository: {repo_data.full_name}")
                else:
                    new_repo = Repository(
                        installation_id=installation.id,
                        github_repo_id=github_repo_id,
                        full_name=repo_data.full_name,
                        private=repo_data.private,
                        owner=repo_data.owner.login,
                        name=repo_data.name,
                        language=repo_data.language,
                        default_branch=repo_data.default_branch,
                        created_at=datetime.datetime.now(timezone.utc),
                        updated_at=datetime.datetime.now(timezone.utc),
                    )
                    self.db.add(new_repo)
                    logger.info(f"Added new repository: {repo_data.full_name}")
            
            elif action == "removed":
                if repo:
                    repo.is_active = False
                    repo.updated_at = datetime.datetime.now(timezone.utc)
                    logger.info(f"Deactivated repository: {repo_data.full_name}")
                else:
                    logger.warning(
                        f"Received request to remove a repository that does not exist in DB: {repo_data.full_name}"
                    )