import jwt
import time
from typing import Dict, Any
from src.utils.logging.otel_logger import logger
from src.core.config import settings
from src.utils.exception import AppException, BadRequestException


class GithubHelpers:
    """Helper utilities for GitHub integration"""
    
    def __init__(self):
        pass
    
    def generate_jwt_token(self) -> str:
        """Generate JWT token for GitHub App authentication"""
        try:
            app_id = getattr(settings, 'GITHUB_APP_ID', None)
            private_key = getattr(settings, 'GITHUB_APP_PRIVATE_KEY', None)
            
            if not app_id or not private_key:
                raise ValueError("GitHub App ID and Private Key must be configured")
            
            now = int(time.time())
            payload = {
                'iat': now,
                'exp': now + (10 * 60),
                'iss': app_id
            }
            
            token = jwt.encode(payload, private_key, algorithm='RS256')
            
            logger.info("Generated JWT token for GitHub App authentication")
            return token
            
        except Exception as e:
            logger.error(f"Error generating JWT token: {str(e)}")
            raise AppException(status_code=500, message="Failed to generate JWT for GitHub App authentication.")
    
    def validate_webhook_payload(self, payload: Dict[str, Any], event_type: str):
        """Validate webhook payload structure"""
        required_fields = []
        try:
            if event_type == "installation":
                required_fields = ["action", "installation"]
                if payload.get("action") == "created":
                    required_fields.append("repositories")
                    
            elif event_type == "installation_repositories":
                required_fields = ["action", "installation"]
                if payload.get("action") == "added":
                    required_fields.append("repositories_added")
                elif payload.get("action") == "removed":
                    required_fields.append("repositories_removed")
                    
            else:
                return

            for field in required_fields:
                if field not in payload:
                    raise BadRequestException(f"Missing required field '{field}' in {event_type} webhook payload")

        except Exception as e:
            logger.error(f"Error validating webhook payload: {str(e)}")
            if not isinstance(e, AppException):
                raise AppException(status_code=500, message="An unexpected error occurred during payload validation.")
            raise e
    
    def extract_repository_info(self, repo_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and normalize repository information from GitHub API response"""
        try:
            return {
                "id": repo_data["id"],
                "name": repo_data["name"],
                "full_name": repo_data["full_name"],
                "private": repo_data["private"],
                "default_branch": repo_data.get("default_branch", "main"),
                "description": repo_data.get("description", ""),
                "language": repo_data.get("language", ""),
                "clone_url": repo_data.get("clone_url", ""),
                "ssh_url": repo_data.get("ssh_url", ""),
                "html_url": repo_data.get("html_url", "")
            }
        except KeyError as e:
            logger.error(f"Missing required repository field: {str(e)}")
            raise BadRequestException(f"Invalid repository data received from GitHub: missing key {str(e)}")
        except Exception as e:
            logger.error(f"Error extracting repository info: {str(e)}")
            raise AppException(status_code=500, message="Failed to extract repository information.")