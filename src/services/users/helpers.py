import datetime
from datetime import timezone
from src.models.db.users import User
from src.models.schemas.users import UserRegister
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from supabase import Client
from src.utils.logging.otel_logger import logger

class UserHelpers:
    def __init__(self, db: Session, supabase: Client):
        self.db = db
        self.supabase = supabase
    
    def _user_exists(self, email: str) -> bool:
        """Check if a user with the given email exists in the local database."""
        user = self.db.query(User).filter(User.email == email).first()
        if not user:
            return None
        
        return {
            "user_id": str(user.user_id),
            "email": user.email
        }

    def _create_supabase_user(self, email: str, password: str) -> dict:
        """Create user in Supabase Auth"""
        try:
            auth_response = self.supabase.auth.sign_up({
                "email": email,
                "password": password,
            })
            
            if auth_response.error:
                return {
                    "status": "failure", 
                    "message": f"Auth error: {auth_response.error.message}"
                }
            
            return {
                "status": "success",
                "supabase_user_id": auth_response.user.id,
                "access_token": auth_response.session.access_token,
                "refresh_token": auth_response.session.refresh_token,
                "token_expires_at": auth_response.session.expires_at
            }
            
        except Exception as e:
            return {"status": "failure", "message": f"Supabase error: {str(e)}"}

    def _create_local_user(self, register_request: UserRegister, supabase_user_id: str) -> dict:
        """Create user record in local database"""
        try:
            new_user = User(
                email=register_request.email,
                supabase_user_id=supabase_user_id,
                created_at=datetime.datetime.now(timezone.utc)
            )
            
            self.db.add(new_user)
            self.db.commit()
            self.db.refresh(new_user)
            
            return {
                "status": "success",
                "user": {
                    "user_id": str(new_user.user_id),
                    "email": new_user.email,
                }
            }
            
        except SQLAlchemyError as e:
            self.db.rollback()
            return {"status": "failure", "message": f"Database error: {str(e)}"}

    def _authenticate_with_supabase(self, email: str, password: str) -> dict:
        """Authenticate user with Supabase"""
        try:
            auth_response = self.supabase.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            
            if auth_response.error:
                return {"status": "failure", "message": "Invalid credentials"}
            
            return {
                "status": "success",
                "access_token": auth_response.session.access_token,
                "refresh_token": auth_response.session.refresh_token,
                "token_expires_at": auth_response.session.expires_at
            }
            
        except Exception as e:
            return {"status": "failure", "message": f"Authentication error: {str(e)}"}

    def _update_last_login(self, email: str) -> None:
        """Update user's last login timestamp"""
        user = self.db.query(User).filter(User.email == email).first()
        if user:
            user.updated_at = datetime.datetime.now(timezone.utc)
            self.db.commit()
    
    def _logout(self, current_user: User) -> None:
        """Logout the currently authenticated user"""
        self.supabase.auth.sign_out(current_user.supabase_user_id)