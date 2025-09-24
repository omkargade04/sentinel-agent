import supabase
from src.models.db.users import User
from src.models.schemas.users import UserRegister, UserLogin
from fastapi import Depends, HTTPException, status
from src.core.database import get_db
from sqlalchemy.orm import Session
from supabase import Client
from src.core.config import settings
from src.core.supabase_client import get_supabase_client
from src.services.users.helpers import UserHelpers
from src.utils.logging.otel_logger import logger

class UserService:
    def __init__(
        self,
        db: Session = Depends(get_db),
        supabase: Client = Depends(get_supabase_client)
    ):
        self.db = db
        self.supabase = supabase
        self.helpers = UserHelpers(self.db, self.supabase)

    def register(self, register_request: UserRegister) -> dict:
        """
        Handles user registration by creating a user in Supabase and a corresponding
        record in the local database.
        """
        if self.helpers._user_exists(register_request.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email already exists."
            )
        auth_response = self.helpers._create_supabase_user(
            register_request.email, register_request.password
        )
        if auth_response['status'] == 'failure':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Authentication error: {auth_response['message']}"
            )

        self.helpers._create_local_user(register_request, auth_response['supabase_user_id'])
        return {
            "access_token": auth_response["access_token"],
            "refresh_token": auth_response["refresh_token"],
            "message": "User registered successfully"
        }

    def login(self, login_request: UserLogin) -> dict:
        """
        Handles user login by authenticating with Supabase.
        """
        if not self.helpers._user_exists(login_request.email):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found."
            )
        auth_response = self.helpers._authenticate_with_supabase(
            login_request.email, login_request.password
        )
        if auth_response['status'] == 'failure':
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Login failed: {auth_response['message']}"
            )
        
        self.helpers._update_last_login(login_request.email)

        return {
            "access_token": auth_response["access_token"],
            "refresh_token": auth_response["refresh_token"],
        }

    def refresh_token(self, refresh_token: str) -> dict:
        """
        Refreshes the session using a refresh token.
        """
        try:
            response = self.supabase.auth.set_session(
                access_token="",
                refresh_token=refresh_token
            )
            
            if response.error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Could not refresh token: {response.error.message}",
                )

            return {
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token,
            }
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid refresh token: {str(e)}",
            )

    def me(self, current_user: User) -> dict:
        """
        Returns the profile of the currently authenticated user.
        """
        if not current_user:
             raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found."
            )
        return {
            "user_id": str(current_user.user_id),
            "email": current_user.email,
            "created_at": current_user.created_at,
            "updated_at": current_user.updated_at
        }

    def logout(self, current_user: User) -> dict:
        """
        Logs out the currently authenticated user.
        """
        self.helpers._logout(current_user)
        return {
            "status": "success",
            "message": "Logged out successfully"
        }