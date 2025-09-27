from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.requests import Request
from fastapi.responses import JSONResponse
import json
import hmac
import hashlib
from typing import Optional
from src.utils.logging.otel_logger import logger
from src.services.github.github_service import GithubFactory
from src.core.config import settings

router = APIRouter(
    prefix="/github",
    tags=["Github"],
)

def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature"""
    if not signature:
        return False
    
    try:
        sha_name, signature = signature.split('=')
        if sha_name != 'sha256':
            return False
        
        mac = hmac.new(secret.encode(), payload, hashlib.sha256)
        return hmac.compare_digest(mac.hexdigest(), signature)
    except Exception:
        return False

@router.get("/callback")
async def github_callback(
    code: Optional[str] = None, 
    installation_id: Optional[str] = None,
    github_service: GithubFactory = Depends(GithubFactory)
):
    """Handle GitHub App installation callback"""
    logger.info(f"GitHub callback received - code: {code}, installation_id: {installation_id}")
    
    if not code or not installation_id:
        raise HTTPException(status_code=400, detail="Missing required parameters")
    
    return github_service.handle_callback(code, installation_id)

@router.post("/events")
async def github_webhook(
    request: Request,
    x_github_event: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None),
    github_service: GithubFactory = Depends(GithubFactory)
):
    """Handle GitHub webhook events"""
    try:
        # Get raw body for signature verification
        body_bytes = await request.body()
        
        # Verify webhook signature
        webhook_secret = getattr(settings, 'GITHUB_WEBHOOK_SECRET', None)
        if webhook_secret and not verify_webhook_signature(body_bytes, x_hub_signature_256, webhook_secret):
            logger.warning("Invalid webhook signature")
            raise HTTPException(status_code=401, detail="Invalid signature")
        
        # Parse JSON body
        try:
            body = json.loads(body_bytes.decode('utf-8'))
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")
        
        if not x_github_event:
            raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")
        
        logger.info(f"GitHub webhook received - event: {x_github_event}")
        
        # Process webhook
        result = await github_service.process_webhook(body, x_github_event)
        
        return JSONResponse(content=result, status_code=200)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")