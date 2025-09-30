import jwt
import time
from src.utils.logging.otel_logger import logger
from src.core.config import settings
import httpx

class RepositoryHelpers:
    """Helper utilities for Repository integration"""
    
    def __init__(self):
        pass
    
    def generate_jwt_token(self) -> str:
        """Generate JWT token for Repository authentication"""
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
            
            logger.info("Generated JWT token for Repository authentication")
            return token
            
        except Exception as e:
            logger.error(f"Error generating JWT token: {str(e)}")
            raise
    
    async def generate_installation_token(self, installation_id: int) -> str:
        """Generate installation token for Repository authentication"""
        jwt = self.generate_jwt_token()
        token_url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        
        async with httpx.AsyncClient() as client:
            headers = {
                "Authorization": f"Bearer {jwt}",
                "Accept": "application/vnd.github+json"
            }
            response = await client.post(token_url, headers=headers)
            
            if response.status_code != 201:
                logger.error(f"Failed to generate installation token: {response.status_code} {response.text}")
                raise Exception(f"Failed to generate installation token: {response.status_code} {response.text}")
            
            token = response.json()["token"]
            return token
       