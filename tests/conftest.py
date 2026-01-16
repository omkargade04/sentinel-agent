"""
Global test configuration and fixtures for PR Review tests.

Provides common fixtures and test utilities used across multiple test modules.
"""

import pytest
import asyncio
import uuid
from datetime import datetime
from typing import AsyncGenerator, Generator

from src.core.pr_review_config import PRReviewSettings, create_development_config
from src.models.schemas.pr_review import PRReviewRequest


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_pr_review_settings() -> PRReviewSettings:
    """Create test-specific PR review settings with reduced limits."""
    settings = create_development_config()

    # Override with test-friendly values
    settings.limits.max_changed_files = 10
    settings.limits.max_context_items = 5
    settings.limits.max_total_characters = 10000
    settings.limits.max_clone_size_mb = 100
    settings.timeouts.github_api_timeout = 5
    settings.timeouts.clone_pr_head_timeout = 30
    settings.enable_dry_run_mode = True

    return settings


@pytest.fixture
def sample_repo_id() -> uuid.UUID:
    """Generate a sample repository UUID."""
    return uuid.uuid4()


@pytest.fixture
def sample_installation_id() -> int:
    """Sample GitHub installation ID."""
    return 12345678


@pytest.fixture
def sample_github_repo_id() -> int:
    """Sample GitHub repository ID."""
    return 987654321


@pytest.fixture
def sample_pr_number() -> int:
    """Sample PR number."""
    return 42


@pytest.fixture
def sample_head_sha() -> str:
    """Sample head commit SHA."""
    return "1234567890abcdef1234567890abcdef12345678"


@pytest.fixture
def sample_base_sha() -> str:
    """Sample base commit SHA."""
    return "abcdef1234567890abcdef1234567890abcdef12"


@pytest.fixture
def sample_pr_review_request(
    sample_installation_id: int,
    sample_repo_id: uuid.UUID,
    sample_github_repo_id: int,
    sample_pr_number: int,
    sample_head_sha: str,
    sample_base_sha: str
) -> PRReviewRequest:
    """Create a sample PR review request."""
    return PRReviewRequest(
        installation_id=sample_installation_id,
        repo_id=sample_repo_id,
        github_repo_id=sample_github_repo_id,
        github_repo_name="test-owner/test-repo",
        pr_number=sample_pr_number,
        head_sha=sample_head_sha,
        base_sha=sample_base_sha
    )


@pytest.fixture
def sample_github_pr_details() -> dict:
    """Sample PR details from GitHub API."""
    return {
        "id": 123456789,
        "number": 42,
        "title": "Add new test feature",
        "body": "This PR adds a new test feature with proper error handling.",
        "state": "open",
        "draft": False,
        "mergeable": True,
        "mergeable_state": "clean",
        "merged": False,
        "user": {
            "login": "test-contributor",
            "id": 12345,
            "type": "User"
        },
        "assignees": [],
        "requested_reviewers": [],
        "labels": [
            {"name": "enhancement", "color": "84b6eb"},
            {"name": "needs-review", "color": "fbca04"}
        ],
        "created_at": "2024-01-15T10:00:00Z",
        "updated_at": "2024-01-15T12:30:00Z",
        "closed_at": None,
        "merged_at": None,
        "base": {
            "ref": "main",
            "sha": "abcdef1234567890abcdef1234567890abcdef12",
            "repo": {
                "name": "test-repo",
                "full_name": "test-owner/test-repo"
            }
        },
        "head": {
            "ref": "feature/new-test-feature",
            "sha": "1234567890abcdef1234567890abcdef12345678",
            "repo": {
                "name": "test-repo",
                "full_name": "test-owner/test-repo"
            }
        },
        "commits": 3,
        "additions": 42,
        "deletions": 15,
        "changed_files": 4
    }


@pytest.fixture
def sample_github_pr_files() -> list:
    """Sample PR files from GitHub API."""
    return [
        {
            "sha": "bbcd538c8e72b8c175046e27cc8f907076331401",
            "filename": "src/features/new_feature.py",
            "status": "added",
            "additions": 35,
            "deletions": 0,
            "changes": 35,
            "blob_url": "https://github.com/test-owner/test-repo/blob/1234.../src/features/new_feature.py",
            "raw_url": "https://github.com/test-owner/test-repo/raw/1234.../src/features/new_feature.py",
            "contents_url": "https://api.github.com/repos/test-owner/test-repo/contents/src/features/new_feature.py?ref=1234...",
            "patch": """@@ -0,0 +1,35 @@
+\"\"\"
+New feature module for enhanced functionality.
+\"\"\"
+
+import logging
+from typing import Optional, Dict, Any
+
+
+class NewFeature:
+    \"\"\"Implements new feature functionality.\"\"\"
+
+    def __init__(self, config: Dict[str, Any]):
+        self.config = config
+        self.logger = logging.getLogger(__name__)
+
+    def process(self, data: Optional[str] = None) -> bool:
+        \"\"\"Process data with new feature logic.\"\"\"
+        if not data:
+            self.logger.warning("No data provided for processing")
+            return False
+
+        try:
+            # Enhanced processing logic
+            result = self._enhanced_processing(data)
+            self.logger.info(f"Processing completed: {result}")
+            return True
+        except Exception as e:
+            self.logger.error(f"Processing failed: {e}")
+            return False
+
+    def _enhanced_processing(self, data: str) -> str:
+        \"\"\"Internal processing with enhancements.\"\"\"
+        return data.upper().strip()"""
        },
        {
            "sha": "219f4b2f5b4b9f4a5a1e0c8e1c8e9f8e1c8e9f8e",
            "filename": "tests/test_new_feature.py",
            "status": "added",
            "additions": 25,
            "deletions": 0,
            "changes": 25,
            "blob_url": "https://github.com/test-owner/test-repo/blob/1234.../tests/test_new_feature.py",
            "raw_url": "https://github.com/test-owner/test-repo/raw/1234.../tests/test_new_feature.py",
            "contents_url": "https://api.github.com/repos/test-owner/test-repo/contents/tests/test_new_feature.py?ref=1234...",
            "patch": """@@ -0,0 +1,25 @@
+\"\"\"
+Tests for new feature module.
+\"\"\"
+
+import pytest
+from src.features.new_feature import NewFeature
+
+
+def test_new_feature_initialization():
+    \"\"\"Test feature initialization.\"\"\"
+    config = {"setting": "value"}
+    feature = NewFeature(config)
+    assert feature.config == config
+
+
+def test_process_with_valid_data():
+    \"\"\"Test processing with valid data.\"\"\"
+    feature = NewFeature({})
+    result = feature.process("test data")
+    assert result is True
+
+
+def test_process_with_no_data():
+    \"\"\"Test processing with no data.\"\"\"
+    feature = NewFeature({})
+    result = feature.process()
+    assert result is False"""
        },
        {
            "sha": "f4b5c6d7e8f9a0b1c2d3e4f5g6h7i8j9k0l1m2n3",
            "filename": "README.md",
            "status": "modified",
            "additions": 3,
            "deletions": 1,
            "changes": 4,
            "blob_url": "https://github.com/test-owner/test-repo/blob/1234.../README.md",
            "raw_url": "https://github.com/test-owner/test-repo/raw/1234.../README.md",
            "contents_url": "https://api.github.com/repos/test-owner/test-repo/contents/README.md?ref=1234...",
            "patch": """@@ -15,7 +15,9 @@ This project provides enhanced functionality for data processing.
 ## Features

 - Data validation and processing
-- Error handling and logging
+- Enhanced error handling and logging
+- New feature for advanced processing
+- Comprehensive test coverage

 ## Installation"""
        },
        {
            "sha": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0",
            "filename": "requirements.txt",
            "status": "modified",
            "additions": 2,
            "deletions": 0,
            "changes": 2,
            "blob_url": "https://github.com/test-owner/test-repo/blob/1234.../requirements.txt",
            "raw_url": "https://github.com/test-owner/test-repo/raw/1234.../requirements.txt",
            "contents_url": "https://api.github.com/repos/test-owner/test-repo/contents/requirements.txt?ref=1234...",
            "patch": """@@ -3,3 +3,5 @@ requests>=2.28.0
 pydantic>=2.0.0
 fastapi>=0.100.0
 uvicorn>=0.22.0
+pytest>=7.4.0
+pytest-asyncio>=0.21.0"""
        }
    ]


@pytest.fixture
def binary_file_data() -> dict:
    """Sample binary file data from GitHub API."""
    return {
        "sha": "binary123456789abcdef123456789abcdef12345678",
        "filename": "assets/logo.png",
        "status": "added",
        "additions": 0,
        "deletions": 0,
        "changes": 0,
        "binary": True,
        "blob_url": "https://github.com/test-owner/test-repo/blob/1234.../assets/logo.png",
        "raw_url": "https://github.com/test-owner/test-repo/raw/1234.../assets/logo.png",
        "contents_url": "https://api.github.com/repos/test-owner/test-repo/contents/assets/logo.png?ref=1234...",
        "patch": None
    }


@pytest.fixture
def renamed_file_data() -> dict:
    """Sample renamed file data from GitHub API."""
    return {
        "sha": "renamed123456789abcdef123456789abcdef12345678",
        "filename": "src/utils/new_helpers.py",
        "previous_filename": "src/utils/old_helpers.py",
        "status": "renamed",
        "additions": 0,
        "deletions": 0,
        "changes": 0,
        "blob_url": "https://github.com/test-owner/test-repo/blob/1234.../src/utils/new_helpers.py",
        "raw_url": "https://github.com/test-owner/test-repo/raw/1234.../src/utils/new_helpers.py",
        "contents_url": "https://api.github.com/repos/test-owner/test-repo/contents/src/utils/new_helpers.py?ref=1234...",
        "patch": ""
    }


@pytest.fixture
def mock_github_api_headers() -> dict:
    """Sample GitHub API response headers."""
    return {
        "x-ratelimit-limit": "5000",
        "x-ratelimit-remaining": "4999",
        "x-ratelimit-reset": "1705396800", # Example timestamp
        "x-ratelimit-used": "1",
        "x-github-api-version": "2022-11-28",
        "content-type": "application/json; charset=utf-8"
    }


# Test utilities
def assert_valid_uuid(uuid_string: str) -> bool:
    """Utility to validate UUID format in tests."""
    try:
        uuid.UUID(uuid_string)
        return True
    except ValueError:
        return False


def assert_valid_iso_datetime(datetime_string: str) -> bool:
    """Utility to validate ISO datetime format in tests."""
    try:
        datetime.fromisoformat(datetime_string.replace('Z', '+00:00'))
        return True
    except ValueError:
        return False


def assert_valid_sha(sha_string: str, length: int = 40) -> bool:
    """Utility to validate SHA format in tests."""
    if not sha_string or len(sha_string) != length:
        return False
    try:
        int(sha_string, 16)
        return True
    except ValueError:
        return False