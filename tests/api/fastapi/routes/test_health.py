import pytest
from unittest.mock import patch

from src.api.fastapi.routes.health import health_check, ping


class TestHealthEndpoints:
    """Test suite for health check endpoints."""

    @patch('src.api.fastapi.routes.health.logger')
    def test_health_check_endpoint_success(self, mock_logger):
        """Test that health_check function returns correct response and logs info."""
        # Act
        response = health_check()
        
        # Assert
        assert response == {"status": "ok"}
        mock_logger.info.assert_called_once_with("Health check endpoint hit")

    @patch('src.api.fastapi.routes.health.logger')
    def test_ping_endpoint_success(self, mock_logger):
        """Test that ping function returns correct response and logs info."""
        # Act
        response = ping()
        
        # Assert
        assert response == {"status": "pong"}
        mock_logger.info.assert_called_once_with("Ping endpoint hit")