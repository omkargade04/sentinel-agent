from typing import Dict, Any, Optional
from fastapi import Depends
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from src.core.config import settings
from src.services.github.installation_service import InstallationService
from src.utils.logging.otel_logger import logger
from src.core.database import get_db
from src.models.db.users import User
from src.models.db.repositories import Repository
from sqlalchemy.orm import Session
import secrets
import httpx
from src.utils.exception import AppException, BadRequestException
from src.models.schemas.users import User as UserSchema
from src.models.schemas.github_installations import InstallationEvent


class GithubService:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db
        self.installation_service = InstallationService(db)
    
    def handle_auth(self) -> Dict[str, Any]:
        """Handle GitHub OAuth authentication"""
        state: str = secrets.token_hex(16)
        redirect_uri: str = settings.GITHUB_REDIRECT_URI
        client_id: str = settings.GITHUB_OAUTH_CLIENT_ID
        
        try:
            github_auth_url: str = (
                "https://github.com/login/oauth/authorize"
                f"?client_id={client_id}"
                f"&redirect_uri={redirect_uri}"
                "&scope=read:user%20user:email"
                f"&state={state}"
            )
            return RedirectResponse(url=github_auth_url)
        except Exception as e:
            logger.error(f"Error generating GitHub auth URL: {str(e)}")
            raise AppException(
                status_code=500, 
                message="There was an issue with the authentication. Please try again or contact support."
            )  
    
    async def handle_callback(self, code: str, state: str) -> Dict[str, Any]:
        """Handle GitHub OAuth callback and store user"""
        try:
            logger.info(f"GitHub OAuth callback received with state: {state}")
            token_url: str = "https://github.com/login/oauth/access_token"
            
            async with httpx.AsyncClient() as client:
                headers = {"Accept": "application/json"}
                data = {
                    "client_id": settings.GITHUB_OAUTH_CLIENT_ID,
                    "client_secret": settings.GITHUB_OAUTH_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": settings.GITHUB_REDIRECT_URI
                }
                response = await client.post(token_url, headers=headers, data=data)
                
                if response.status_code != 200:
                    logger.error(f"Failed to exchange code for token: {response.status_code} {response.text}")
                    raise BadRequestException("Failed to exchange authorization code for an access token.")
                
                token_data: Dict[str, Any] = response.json()
                
            access_token: str = token_data.get("access_token")
            if not access_token:
                logger.error(f"No access token in response: {token_data}")
                raise BadRequestException("No access token was received from GitHub.")
                
            user_data: Dict[str, Any] = await self._get_user(access_token)
            
            github_installation_url = f"https://github.com/apps/{settings.GITHUB_APP_NAME}/installations/select_target?state={state}"
            
            return RedirectResponse(url=github_installation_url)
        except Exception as e:
            logger.error(f"Error handling GitHub callback: {str(e)}")
            # Re-raise as a generic AppException if it's not already one of our custom exceptions
            if not isinstance(e, AppException):
                raise AppException(
                    status_code=500,
                    message="An unexpected error occurred during the installation process."
                )
            raise e
        
    async def _get_user(self, access_token: str) -> Dict[str, Any]:
        """Get user from GitHub"""
        async with httpx.AsyncClient() as client:
            user_response = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            if user_response.status_code != 200:
                logger.error(f"Failed to get user from GitHub: {user_response.status_code} {user_response.text}")
                raise AppException(status_code=user_response.status_code, message="Failed to get user from GitHub.")
        user_data: Dict[str, Any] = user_response.json()
        return user_data
    
    async def _store_user(self, db: Session, user_data: Dict[str, Any], access_token: str, state: str) -> User:
        """Store or update user in database"""
        email: str = user_data.get("email")

        existing_user: UserSchema = db.query(User).filter(User.email == email).first()
        
        if existing_user:
            logger.info(f"User {email} already exists, updating...")
            user = existing_user
        else:
            logger.info(f"Creating new user: {email}")
            user = User(
                email=email,
            )
            db.add(user)
        
        db.commit()
        db.refresh(user)
        
        return user

    async def process_webhook(self, body: Dict[str, Any], event_type: str) -> Dict[str, Any]:
        """Process GitHub webhook events"""
        logger.info(f"Processing GitHub webhook event: {event_type}")

        try:
            if event_type in ["installation", "installation_repositories"]:
                payload = body
                action = payload.get("action")

                if event_type == "installation":
                    if action == "created":
                        self.installation_service.process_installation_created(payload)
                    elif action == "deleted":
                        self.installation_service.process_installation_deleted(payload)
                    else:
                        logger.warning(f"Unhandled installation action: {action}")
                
                elif event_type == "installation_repositories":
                    if action in ["added", "removed"]:
                        self.installation_service.process_repositories_changed(payload)
                    else:
                        logger.warning(f"Unhandled installation_repositories action: {action}")

            elif event_type == "pull_request":
                result = await self._handle_pull_request_webhook(body)
                if result:
                    return result
                
            else:
                logger.info(f"Unhandled webhook event type: {event_type}")
            
            return {
                "status": "success",
                "message": f"Webhook '{event_type}' processed successfully"
            }
        
        except ValidationError as e:
            logger.error(f"Webhook payload validation error for event '{event_type}': {e}")
            raise BadRequestException(f"Invalid webhook payload for event '{event_type}'.")
            
        except Exception as e:
            logger.error(f"Error processing webhook {event_type}: {str(e)}")
            # Re-raise custom exceptions, wrap generic ones
            if not isinstance(e, AppException):
                raise AppException(status_code=500, message=f"Failed to process webhook '{event_type}'")
            raise e
            
    async def _handle_pull_request_webhook(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Handle pull_request webhook events to trigger automated code reviews.
        
        Triggers PRReviewWorkflow for:
        - opened: New PR created
        - reopened: Previously closed PR reopened
        - synchronize: New commits pushed to PR
        
        Args:
            payload: GitHub webhook payload
            
        Returns:
            Response dict if handled, None if ignored
        """
        from src.core.temporal_client import temporal_client
        from src.models.schemas.pr_review import PRReviewRequest
        from src.workflows.pr_review_workflow import (
            PRReviewWorkflow,
            create_pr_review_workflow_id,
            create_pr_review_task_queue
        )
        
        action = payload.get("action")
        pr_data = payload.get("pull_request", {})
        repo_data = payload.get("repository", {})
        installation_data = payload.get("installation", {})
        
        # Only handle specific actions
        supported_actions = {"opened", "reopened", "synchronize"}
        if action not in supported_actions:
            logger.info(f"Ignoring pull_request action: {action}")
            return None
        
        # Extract PR details
        pr_number = pr_data.get("number")
        head_sha = pr_data.get("head", {}).get("sha")
        base_sha = pr_data.get("base", {}).get("sha")
        head_repo_full_name = pr_data.get("head", {}).get("repo", {}).get("full_name")
        base_repo_full_name = pr_data.get("base", {}).get("repo", {}).get("full_name")
        
        # Extract repository details
        github_repo_id = repo_data.get("id")
        github_repo_name = repo_data.get("full_name")
        
        # Extract installation ID
        installation_id = installation_data.get("id")
        
        logger.info(
            f"Processing pull_request:{action} for {github_repo_name}#{pr_number} "
            f"(head: {head_sha[:8] if head_sha else 'unknown'})"
        )
        
        # Validate required fields
        if not all([pr_number, head_sha, base_sha, github_repo_id, github_repo_name, installation_id]):
            logger.warning(
                f"Missing required fields in pull_request webhook: "
                f"pr_number={pr_number}, head_sha={head_sha}, base_sha={base_sha}, "
                f"github_repo_id={github_repo_id}, installation_id={installation_id}"
            )
            return {
                "status": "ignored",
                "reason": "Missing required fields in webhook payload"
            }
        
        # v0 limitation: Reject fork PRs
        if head_repo_full_name != base_repo_full_name:
            logger.info(
                f"Ignoring fork PR: head={head_repo_full_name}, base={base_repo_full_name}"
            )
            return {
                "status": "ignored",
                "reason": "Fork PRs not supported in v0"
            }
        
        # Look up internal repository ID
        repository = self.db.query(Repository).filter(
            Repository.github_repo_id == github_repo_id
        ).first()
        
        if not repository:
            logger.warning(
                f"Repository not found in database: github_repo_id={github_repo_id}, "
                f"name={github_repo_name}. Repository may not be indexed yet."
            )
            return {
                "status": "ignored",
                "reason": f"Repository {github_repo_name} not indexed yet"
            }
        
        # Build PR review request
        try:
            review_request = PRReviewRequest(
                installation_id=installation_id,
                repo_id=repository.id,
                github_repo_id=github_repo_id,
                github_repo_name=github_repo_name,
                pr_number=pr_number,
                head_sha=head_sha,
                base_sha=base_sha
            )
        except ValidationError as e:
            logger.error(f"Failed to build PRReviewRequest: {e}")
            return {
                "status": "error",
                "reason": f"Invalid PR data: {e}"
            }
        
        # Start Temporal workflow
        try:
            client = await temporal_client.get_client()
            workflow_id = create_pr_review_workflow_id(
                str(repository.id),
                pr_number
            )
            
            handle = await client.start_workflow(
                PRReviewWorkflow.run,
                review_request,
                id=workflow_id,
                task_queue=create_pr_review_task_queue()
            )
            
            logger.info(
                f"Started PR review workflow {workflow_id} for "
                f"{github_repo_name}#{pr_number}"
            )
            
            return {
                "status": "success",
                "message": f"PR review workflow started for {github_repo_name}#{pr_number}",
                "workflow_id": workflow_id,
                "run_id": str(handle.first_execution_run_id or "")
            }
            
        except Exception as e:
            logger.error(
                f"Failed to start PR review workflow for {github_repo_name}#{pr_number}: {e}",
                exc_info=True
            )
            # Don't raise - webhook should return 200 even if workflow fails to start
            return {
                "status": "error",
                "reason": f"Failed to start workflow: {str(e)}"
            }
