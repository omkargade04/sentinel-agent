import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from src.services.users.user_service import UserService
from src.models.schemas.users import UserRegister, UserLogin
from src.models.db.users import User
from datetime import datetime, timezone

class TestUserService:

    def setup_method(self):
        """Set up test fixtures before each test method is called."""
        # Mock DB session
        self.mock_db = MagicMock()
        
        # Mock Supabase client
        self.mock_supabase = MagicMock()
        
        # Create a patcher for UserHelpers
        self.patcher = patch('src.services.users.user_service.UserHelpers')
        self.mock_helpers_class = self.patcher.start()
        
        # Create a mock instance that will be returned when UserHelpers is instantiated
        self.mock_helpers = MagicMock()
        self.mock_helpers_class.return_value = self.mock_helpers
        
        # Create the service with mocked dependencies
        self.user_service = UserService(
            db=self.mock_db,
            supabase=self.mock_supabase
        )
        
        # Test data
        self.test_email = "test@example.com"
        self.test_password = "securePassword123"

    def teardown_method(self):
        """Tear down test fixtures after each test method is called."""
        self.patcher.stop()

    def test_register_success(self):
        register_request = UserRegister(
            email=self.test_email,
            password=self.test_password
        )
        
        # Mock the helper methods
        self.mock_helpers._user_exists.return_value = None
        self.mock_helpers._create_supabase_user.return_value = {
            "status": "success",
            "supabase_user_id": "fake-uuid",
            "access_token": "fake-access-token",
            "refresh_token": "fake-refresh-token"
        }
        self.mock_helpers._create_local_user.return_value = {
            "status": "success",
            "user": {"user_id": "local-user-id", "email": self.test_email}
        }
        
        # Act
        result = self.user_service.register(register_request)
        
        # Assert
        # Verify helper methods were called with correct arguments
        self.mock_helpers._user_exists.assert_called_once_with(self.test_email)
        self.mock_helpers._create_supabase_user.assert_called_once_with(
            self.test_email, self.test_password
        )
        self.mock_helpers._create_local_user.assert_called_once_with(
            register_request, "fake-uuid"
        )
        
        # Verify the result
        assert result["access_token"] == "fake-access-token"
        assert result["refresh_token"] == "fake-refresh-token"
        assert result["message"] == "User registered successfully"

    def test_register_user_already_exists(self):
        # Arrange
        register_request = UserRegister(
            email=self.test_email,
            password=self.test_password
        )
        
        # Mock the helper method to indicate user exists
        self.mock_helpers._user_exists.return_value = {
            "user_id": "existing-user-id",
            "email": self.test_email
        }
        
        # Act & Assert
        with pytest.raises(HTTPException) as excinfo:
            self.user_service.register(register_request)
        
        # Verify correct exception was raised
        assert excinfo.value.status_code == 409
        assert "already exists" in str(excinfo.value.detail)
        
        # Verify helper methods were called correctly
        self.mock_helpers._user_exists.assert_called_once_with(self.test_email)
        self.mock_helpers._create_supabase_user.assert_not_called()
        self.mock_helpers._create_local_user.assert_not_called()

    def test_login_success(self):
        # Arrange
        login_request = UserLogin(
            email=self.test_email,
            password=self.test_password
        )
        
        # Mock helper methods
        self.mock_helpers._user_exists.return_value = {
            "user_id": "existing-user-id",
            "email": self.test_email
        }
        self.mock_helpers._authenticate_with_supabase.return_value = {
            "status": "success",
            "access_token": "login-access-token",
            "refresh_token": "login-refresh-token"
        }
        
        # Act
        result = self.user_service.login(login_request)
        
        # Assert
        # Verify helper methods were called correctly
        self.mock_helpers._user_exists.assert_called_once_with(self.test_email)
        self.mock_helpers._authenticate_with_supabase.assert_called_once_with(
            self.test_email, self.test_password
        )
        self.mock_helpers._update_last_login.assert_called_once_with(self.test_email)
        
        # Verify the result
        assert result["access_token"] == "login-access-token"
        assert result["refresh_token"] == "login-refresh-token"

    def test_login_user_not_found(self):
        # Arrange
        login_request = UserLogin(
            email=self.test_email,
            password=self.test_password
        )
        
        # Mock helper method to indicate user doesn't exist
        self.mock_helpers._user_exists.return_value = None
        
        # Act & Assert
        with pytest.raises(HTTPException) as excinfo:
            self.user_service.login(login_request)
        
        # Verify correct exception was raised
        assert excinfo.value.status_code == 404
        assert "User not found" in str(excinfo.value.detail)
        
        # Verify helper methods were called correctly
        self.mock_helpers._user_exists.assert_called_once_with(self.test_email)
        self.mock_helpers._authenticate_with_supabase.assert_not_called()
        self.mock_helpers._update_last_login.assert_not_called()

    def test_refresh_token_success(self):
        # Arrange
        refresh_token = "old-refresh-token"
        
        # Mock Supabase response
        mock_session_response = MagicMock()
        mock_session_response.session.access_token = "refreshed-access-token"
        mock_session_response.session.refresh_token = "refreshed-refresh-token"
        mock_session_response.error = None
        self.mock_supabase.auth.set_session.return_value = mock_session_response
        
        # Act
        result = self.user_service.refresh_token(refresh_token)
        
        # Assert
        # Verify Supabase was called with correct token
        self.mock_supabase.auth.set_session.assert_called_once_with(
            access_token="",
            refresh_token=refresh_token
        )
        
        # Verify the result
        assert result["access_token"] == "refreshed-access-token"
        assert result["refresh_token"] == "refreshed-refresh-token"

    def test_refresh_token_failure(self):
        # Arrange
        refresh_token = "invalid-token"
        
        # Mock Supabase response with error
        mock_session_response = MagicMock()
        mock_session_response.error = MagicMock()
        mock_session_response.error.message = "Invalid refresh token"
        self.mock_supabase.auth.set_session.return_value = mock_session_response
        
        # Act & Assert
        with pytest.raises(HTTPException) as excinfo:
            self.user_service.refresh_token(refresh_token)
        
        # Verify correct exception was raised
        assert excinfo.value.status_code == 401
        assert "Could not refresh token" in str(excinfo.value.detail)

    def test_me_returns_user_profile(self):
        # Arrange
        # Create a mock User object that would be returned by the IsAuthenticated dependency
        mock_user = MagicMock()
        mock_user.user_id = "user-uuid-123"
        mock_user.email = self.test_email
        mock_user.created_at = datetime.now(timezone.utc)
        mock_user.updated_at = datetime.now(timezone.utc)
        
        # Act
        result = self.user_service.me(mock_user)
        
        # Assert
        # Verify the result contains the user's profile data
        assert result["user_id"] == str(mock_user.user_id)
        assert result["email"] == mock_user.email
        assert "created_at" in result
        assert "updated_at" in result