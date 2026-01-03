import jwt
import time
from src.utils.logging.otel_logger import logger
from src.core.config import settings
import httpx
from src.utils.exception import AppException, UnauthorizedException

class RepositoryHelpers:
    """Helper utilities for Repository integration"""
    def __init__(self, db=None):
        self.db = db
    
    def generate_jwt_token(self) -> str:
        """Generate JWT token for Repository authentication"""
        try:
            app_id: str = getattr(settings, 'GITHUB_APP_ID', None)
            private_key_raw = getattr(settings, 'GITHUB_APP_PRIVATE_KEY', None)
            
            if not app_id or not private_key_raw:
                raise ValueError("GitHub App ID and Private Key must be configured")
            
            # Format the private key properly (replace literal \n with actual newlines)
            private_key = private_key_raw.replace('\\n', '\n')

            now: int = int(time.time())
            payload = {
                'iat': now,
                'exp': now + (10 * 60),
                'iss': app_id
            }
            
            token: str = jwt.encode(payload, private_key, algorithm='RS256')
            
            logger.info("Generated JWT token for Repository authentication")
            return token
            
        except Exception as e:
            logger.error(f"Error generating JWT token: {str(e)}")
            raise AppException(status_code=500, message="Failed to generate JWT for repository authentication.")
    
    async def generate_installation_token(self, installation_id: int) -> str:
        """Generate installation token for Repository authentication"""
        jwt: str = self.generate_jwt_token()
        token_url: str = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        
        async with httpx.AsyncClient() as client:
            headers = {
                "Authorization": f"Bearer {jwt}",
                "Accept": "application/vnd.github+json"
            }
            response = await client.post(token_url, headers=headers)
            
            if response.status_code != 201:
                logger.error(f"Failed to generate installation token: {response.status_code} {response.text}")
                raise UnauthorizedException(f"Failed to generate installation token for installation ID {installation_id}.")
            
            token: str = response.json()["token"]
            return token
       