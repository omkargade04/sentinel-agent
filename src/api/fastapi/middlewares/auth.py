from fastapi import Depends, HTTPException, status, Request, Cookie
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from supabase import Client
from typing import Optional

from src.core.config import settings
from src.core.database import get_db
from src.core.supabase_client import get_supabase_client
from src.models.db.users import User

bearer_scheme = HTTPBearer()

class IsAuthenticated:
    def __init__(
        self,
        db: Session = Depends(get_db),
        supabase: Client = Depends(get_supabase_client)
    ):
        self.db = db
        self.supabase = supabase
        

    def __call__(self, request: Request, access_token: Optional[str] = Cookie(None)) -> User:
        """
        Validates the JWT access token from the request cookies using Supabase.

        Returns the user object from the local database if the token is valid.
        
        Raises:
            HTTPException: If the token is invalid, missing, or the user is not found.
        
        Returns:
            User: The authenticated user object from the database.
        """
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token is missing from cookies"
            )

        try:
            auth_response = self.supabase.auth.get_user(access_token)

            if auth_response.error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid token: {auth_response.error.message}"
                )

            supabase_user = auth_response.user
            if not supabase_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token or user not found in Supabase"
                )
            
            local_user = self.db.query(User).filter(User.email == supabase_user.email).first()

            if not local_user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Authenticated user not found in our database"
                )
            
            request.state.user = local_user
            return local_user

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Could not validate credentials: {str(e)}"
            )
