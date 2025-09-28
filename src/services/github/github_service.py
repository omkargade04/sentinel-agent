from typing import Dict, Any
from fastapi import Depends
from fastapi.responses import RedirectResponse
from src.core.config import settings
from src.services.github.installation_service import InstallationRepositoriesService, InstallationService
from src.utils.logging.otel_logger import logger
from src.core.database import get_db
from src.models.db.users import User
from sqlalchemy.orm import Session
import secrets
import httpx

class GithubService:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db
    
    def handle_auth(self) -> Dict[str, Any]:
        """Handle GitHub OAuth authentication"""
        state = secrets.token_hex(16)
        redirect_uri = settings.GITHUB_REDIRECT_URI
        client_id = settings.GITHUB_OAUTH_CLIENT_ID
        
        try:
            github_auth_url = (
                "https://github.com/login/oauth/authorize"
                f"?client_id={client_id}"
                f"&redirect_uri={redirect_uri}"
                "&scope=read:user%20user:email"
                f"&state={state}"
            )
            return RedirectResponse(url=github_auth_url)
        except Exception as e:
            logger.error(f"Error generating GitHub auth URL: {str(e)}")
            return {
                "status": "error",
                "message": "There was an issue with the authentication. Please try again or contact support."
            }  
    
    async def handle_callback(self, code: str, state: str) -> Dict[str, Any]:
        """Handle GitHub OAuth callback and store user"""
        try:
            logger.info(f"GitHub OAuth callback received with state: {state}")
            token_url = "https://github.com/login/oauth/access_token"
            
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
                    raise Exception("Failed to exchange authorization code")
                
                token_data = response.json()
                
            access_token = token_data.get("access_token")
            if not access_token:
                logger.error(f"No access token in response: {token_data}")
                raise Exception("No access token received")
                
            user_data = await self._get_user(access_token)
            
            github_installation_url = f"https://github.com/apps/{settings.GITHUB_APP_NAME}/installations/select_target?state={state}"
            
            return RedirectResponse(url=github_installation_url)
        except Exception as e:
            logger.error(f"Error handling GitHub callback: {str(e)}")
            return {
                "status": "error",
                "message": "There was an issue with the installation. Please try again or contact support."
            }
        
    async def _get_user(self, access_token: str) -> Dict[str, Any]:
        """Get user from GitHub"""
        async with httpx.AsyncClient() as client:
            user_response = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            if user_response.status_code != 200:
                logger.error(f"Failed to get user from GitHub: {user_response.status_code} {user_response.text}")
                raise Exception(f"Failed to get user from GitHub: {user_response.status_code} {user_response.text}")
        user_data = user_response.json()
        return user_data
    
    async def _store_user(self, db: Session, user_data: Dict[str, Any], access_token: str, state: str) -> User:
        """Store or update user in database"""
        github_id = user_data.get("id")
        email = user_data.get("email")
        login = user_data.get("login")

        existing_user = db.query(User).filter(User.email == email).first()
        
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
        try:
            logger.info(f"Processing GitHub webhook event: {event_type}")
            
            if event_type == "installation":
                action = body.get("action")
                if action == "created":
                    installation_service = InstallationService()
                    return await installation_service.process_installation_created(body)
                elif action == "deleted":
                    installation_service = InstallationService()
                    return await installation_service.process_installation_deleted(body)
                else:
                    logger.warning(f"Unhandled installation action: {action}")
            
            elif event_type == "installation_repositories":
                action = body.get("action")
                if action in ["added", "removed"]:
                    installation_repositories_service = InstallationRepositoriesService()
                    return await installation_repositories_service.process_repositories_changed(body, action)
                else:
                    logger.warning(f"Unhandled installation_repositories action: {action}")
            
            elif event_type == "pull_request":
                # TODO: Implement PR webhook handling for code reviews
                logger.info("PR webhook received - not implemented yet")
                
            else:
                logger.info(f"Unhandled webhook event type: {event_type}")
            
            return {
                "status": "success",
                "message": f"Webhook {event_type} processed successfully"
            }
            
        except Exception as e:
            logger.error(f"Error processing webhook {event_type}: {str(e)}")
            return {
                "status": "error",
                "message": f"Failed to process webhook {event_type}"
            }