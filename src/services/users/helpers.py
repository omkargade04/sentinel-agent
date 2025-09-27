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
        try:    
            user = self.db.query(User).filter(User.email == email).first()
            if not user:
                return None
            return {
                "user_id": str(user.user_id),
                "email": user.email
            }
        except SQLAlchemyError as e:
            self.db.rollback()
            return {"status": "failure", "message": f"Database error: {str(e)}"}
        except Exception as e:
            logger.error(f"Error checking if user exists: {e}")
            return {"status": "failure", "message": "Error checking if user exists"}
        finally:
            self.db.close()

    def _create_supabase_user(self, email: str, password: str) -> dict:
        """Create user in Supabase Auth"""
        try:
            auth_response = self.supabase.auth.sign_up({
                "email": email,
                "password": password,
            })
            
            if not hasattr(auth_response, 'user') or not auth_response.user:
                return {
                    "status": "failure", 
                    "message": "Supabase authentication failed - invalid response structure"
                }
            
            if not hasattr(auth_response, 'session') or not auth_response.session:
                logger.info(f"User created but email confirmation required for: {auth_response.user.email}")
                return {
                    "status": "success", 
                    "supabase_user_id": auth_response.user.id,
                    "message": "User created successfully. Please check your email for confirmation.",
                    "requires_confirmation": True
                }
                
            logger.info(f"Auth response successful for user: {auth_response.user.email}")
            return {
                "status": "success",
                "supabase_user_id": auth_response.user.id,
                "access_token": auth_response.session.access_token,
                "refresh_token": auth_response.session.refresh_token,
            }
            
        except Exception as e:
            logger.error(f"Supabase registration error: {e}")
            return {"status": "failure", "message": f"Authentication service error: {str(e)}"}

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
        finally:
            self.db.close()
            
    def _authenticate_with_supabase(self, email: str, password: str) -> dict:
        """Authenticate user with Supabase"""
        try:
            auth_response = self.supabase.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            
            if not hasattr(auth_response, 'user') or not auth_response.user:
                return {
                    "status": "failure", 
                    "message": "Invalid credentials"
                }
            
            if not hasattr(auth_response, 'session') or not auth_response.session:
                return {
                    "status": "failure", 
                    "message": "Authentication failed - no session created"
                }
            
            logger.info(f"Login successful for user: {auth_response.user.email}")
            return {
                "status": "success",
                "access_token": auth_response.session.access_token,
                "refresh_token": auth_response.session.refresh_token,
            }
            
        except Exception as e:
            logger.error(f"Supabase login error: {e}")
            return {"status": "failure", "message": "Invalid credentials"}

    def _update_last_login(self, email: str) -> None:
        """Update user's last login timestamp"""
        try:
            user = self.db.query(User).filter(User.email == email).first()
            if user:
                user.updated_at = datetime.datetime.now(timezone.utc)
                self.db.commit()
                self.db.refresh(user)
        except SQLAlchemyError as e:
            self.db.rollback()
            return {"status": "failure", "message": f"Database error: {str(e)}"}
        except Exception as e:
            logger.error(f"Error updating last login: {e}")
            return {"status": "failure", "message": "Error updating last login"}
        finally:
            self.db.close()
    
    def _logout(self, current_user: User) -> None:
        """Logout the currently authenticated user"""
        self.supabase.auth.sign_out()