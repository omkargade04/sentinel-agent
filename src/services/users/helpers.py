import datetime
from datetime import timezone
from src.models.db.github_installations import GithubInstallation
from src.models.db.users import User
from src.models.schemas.users import UserRegister
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from supabase import Client
from src.utils.logging.otel_logger import logger
from src.utils.exception import (
    AppException,
    DuplicateResourceException,
    BadRequestException,
    InstallationNotFoundError,
)

class UserHelpers:
    def __init__(self, db: Session, supabase: Client):
        self.db = db
        self.supabase = supabase
    
    def _user_exists(self, email: str) -> dict:
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
            logger.error(f"Database error while checking if user exists: {e}")
            raise AppException(status_code=500, message="Database error occurred.")
        except Exception as e:
            logger.error(f"Error checking if user exists: {e}")
            raise AppException(status_code=500, message="An unexpected error occurred.")
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
                raise BadRequestException("Supabase authentication failed - invalid response structure")
            
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
            if "already exists" in str(e):
                raise DuplicateResourceException("User with this email already exists.")
            raise BadRequestException(f"Authentication service error: {str(e)}")

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
            logger.error(f"Database error while creating local user: {e}")
            raise AppException(status_code=500, message="Database error occurred while creating user.")
        finally:
            self.db.close()
            
    def _authenticate_with_supabase(self, email: str, password: str) -> dict:
        """Authenticate user with Supabase"""
        try:
            auth_response = self.supabase.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            
            if not hasattr(auth_response, 'user') or not auth_response.user or not hasattr(auth_response, 'session') or not auth_response.session:
                raise BadRequestException("Invalid credentials")
            
            logger.info(f"Login successful for user: {auth_response.user.email}")
            return {
                "status": "success",
                "access_token": auth_response.session.access_token,
                "refresh_token": auth_response.session.refresh_token,
            }
            
        except Exception as e:
            logger.error(f"Supabase login error: {e}")
            raise BadRequestException("Invalid credentials")

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
            logger.error(f"Database error while updating last login: {e}")
            raise AppException(status_code=500, message="Database error occurred.")
        except Exception as e:
            logger.error(f"Error updating last login: {e}")
            raise AppException(status_code=500, message="An unexpected error occurred.")
        finally:
            self.db.close()
    
    def _set_user_id_for_installation(self, current_user: User, installation_id: str) -> dict:
        """Set the user ID for the installation"""
        github_installation = self.db.query(GithubInstallation).filter(GithubInstallation.installation_id == installation_id).first()
        if not github_installation:
            raise InstallationNotFoundError(f"Installation with ID {installation_id} not found.")
        
        try:
            github_installation.user_id = current_user.user_id
            self.db.commit()
            self.db.refresh(github_installation)
            return {
                "status": "success",
                "message": "User ID for installation set successfully"
            }
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"Error setting user ID for installation: {e}")
            raise AppException(status_code=500, message="Database error occurred.")
        except Exception as e:
            logger.error(f"Error setting user ID for installation: {e}")
            raise AppException(status_code=500, message="An unexpected error occurred.")
        finally:
            self.db.close()
        
    def _logout(self, current_user: User) -> None:
        """Logout the currently authenticated user"""
        self.supabase.auth.sign_out()