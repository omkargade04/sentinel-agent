from fastapi import Depends, HTTPException, status, Request, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from supabase import Client
from typing import Optional

from src.core.config import settings
from src.core.database import get_db
from src.core.supabase_client import get_supabase_client
from src.models.db.users import User
from src.utils.logging.otel_logger import logger

bearer_scheme = HTTPBearer(auto_error=False)

def get_current_user(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    authorization: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    supabase: Client = Depends(get_supabase_client)
) -> User:
    """
    Validates the JWT access token from cookies or Authorization header using Supabase.
    
    Priority: 
    1. Authorization header (Bearer token)
    2. Cookie (access_token)

    Returns the user object from the local database if the token is valid.
    
    Raises:
        HTTPException: If the token is invalid, missing, or the user is not found.
    
    Returns:
        User: The authenticated user object from the database.
    """
    token = None
    
    if authorization:
        token = authorization.credentials
        logger.info(f"Using token from Authorization header")
    elif access_token:
        token = access_token
        logger.info(f"Using token from cookie")
    
    if not token:
        logger.error("No token found in either Authorization header or cookies")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is missing from both Authorization header and cookies"
        )

    try:
        auth_response = supabase.auth.get_user(token)
        
        supabase_user = auth_response.user
        if not supabase_user:
            logger.error("No user found in Supabase auth response")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token or user not found in Supabase"
            )
        
        local_user = db.query(User).filter(User.email == supabase_user.email).first()
        if not local_user:
            logger.error(f"User {supabase_user.email} not found in local database")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Authenticated user not found in our database"
            )
        
        logger.info(f"Authentication successful for user: {local_user.email}")
        request.state.user = local_user
        return local_user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {str(e)}"
        )
