from supabase_auth import AuthResponse
from src.models.db.users import User
from src.models.schemas.users import UserRegister, UserLogin
from fastapi import Depends, Request
from src.core.database import get_db
from sqlalchemy.orm import Session
from supabase import Client
from src.core.supabase_client import get_supabase_client
from src.services.users.helpers import UserHelpers
from src.utils.exception import (
    DuplicateResourceException,
    UserNotFoundError,
    UnauthorizedException,
    BadRequestException
)

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
            raise DuplicateResourceException("User with this email already exists.")

        auth_response: AuthResponse = self.helpers._create_supabase_user(
            register_request.email, register_request.password
        )

        self.helpers._create_local_user(register_request, auth_response['supabase_user_id'])
        
        # Handle cases where email confirmation is required
        if auth_response.get("requires_confirmation"):
            return {
                "message": auth_response["message"],
                "requires_confirmation": True
            }

        return {
            "access_token": auth_response.get("access_token"),
            "refresh_token": auth_response.get("refresh_token"),
            "message": "User registered successfully"
        }

    def login(self, login_request: UserLogin) -> dict:
        """
        Handles user login by authenticating with Supabase.
        """
        if not self.helpers._user_exists(login_request.email):
            raise UserNotFoundError("User not found.")

        auth_response: AuthResponse = self.helpers._authenticate_with_supabase(
            login_request.email, login_request.password
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
            response: AuthResponse = self.supabase.auth.set_session(
                access_token="",
                refresh_token=refresh_token
            )
            
            if not response.session:
                raise UnauthorizedException("Could not refresh token")

            return {
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token,
            }
        except Exception as e:
            raise UnauthorizedException(f"Invalid refresh token: {str(e)}")

    def whoami(self, current_user: User) -> dict:
        """
        Returns the profile of the currently authenticated user.
        """
        if not current_user:
            raise UserNotFoundError("User not found.")
        return {
            "user_id": str(current_user.user_id),
            "email": current_user.email,
            "created_at": current_user.created_at,
            "updated_at": current_user.updated_at
        }

    def set_user_id_for_installation(self, current_user: User, installation_id: int) -> dict:
        """
        Set the user ID for the installation.
        """
        if not installation_id:
            raise BadRequestException("installation_id query parameter is required.")
            
        self.helpers._set_user_id_for_installation(current_user, installation_id)
        return {
            "status": "success",
            "message": "User ID for installation set successfully"
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