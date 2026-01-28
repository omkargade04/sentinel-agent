"""
Integration Tests for build_seed_set_activity

Tests that the activity correctly handles patches with string change_type values
(simulating deserialization from fetch_pr_context_activity).

Note: These tests mock the SeedSetBuilder to avoid dependencies on tree_sitter.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import sys

from src.models.schemas.pr_review.pr_patch import PRFilePatch, ChangeType
from src.utils.validation import validate_patches


class TestValidatePatchesIntegration:
    """Tests for validate_patches utility used by build_seed_set_activity."""

    def test_validate_patches_handles_string_change_type(self):
        """validate_patches should handle patches with string change_type (from deserialization)."""
        patch_dict = {
            "file_path": "src/test_file.py",
            "change_type": "modified",  # String, not enum - simulating deserialization
            "additions": 5,
            "deletions": 2,
            "binary_file": False,
            "hunks": []
        }

        patches = validate_patches([patch_dict])

        assert len(patches) == 1
        assert isinstance(patches[0], PRFilePatch)
        # The key test: change_type_str should work without AttributeError
        assert patches[0].change_type_str == "modified"

    def test_validate_patches_handles_enum_change_type(self):
        """validate_patches should handle patches with enum change_type."""
        patch_dict = {
            "file_path": "src/test_file.py",
            "change_type": ChangeType.ADDED,  # Enum value
            "additions": 10,
            "deletions": 0,
            "binary_file": False,
            "hunks": []
        }

        patches = validate_patches([patch_dict])

        assert len(patches) == 1
        assert isinstance(patches[0], PRFilePatch)
        assert patches[0].change_type_str == "added"

    def test_validate_patches_handles_mixed_types(self):
        """validate_patches should handle mixed string/enum change_types."""
        patches_data = [
            {
                "file_path": "file1.py",
                "change_type": "added",  # String
                "additions": 10,
                "deletions": 0,
                "binary_file": False,
                "hunks": []
            },
            {
                "file_path": "file2.py",
                "change_type": ChangeType.MODIFIED,  # Enum
                "additions": 5,
                "deletions": 2,
                "binary_file": False,
                "hunks": []
            },
            {
                "file_path": "file3.py",
                "change_type": "removed",  # String
                "additions": 0,
                "deletions": 15,
                "binary_file": False,
                "hunks": []
            }
        ]

        patches = validate_patches(patches_data)

        assert len(patches) == 3
        # All should have working change_type_str
        assert patches[0].change_type_str == "added"
        assert patches[1].change_type_str == "modified"
        assert patches[2].change_type_str == "removed"

    def test_validate_patches_skips_invalid_patches(self):
        """validate_patches should skip invalid patches in non-strict mode."""
        patches_data = [
            {
                "file_path": "valid.py",
                "change_type": "modified",
                "additions": 1,
                "deletions": 0,
                "binary_file": False,
                "hunks": []
            },
            {
                "file_path": "",  # Invalid - empty path
                "change_type": "modified",
                "additions": 0,
                "deletions": 0,
                "hunks": []
            }
        ]

        patches = validate_patches(patches_data, strict=False)

        assert len(patches) == 1
        assert patches[0].file_path == "valid.py"


class TestPRFilePatchChangeTypeStr:
    """Direct tests for PRFilePatch.change_type_str property."""

    def test_change_type_str_with_enum_value(self):
        """change_type_str should work when change_type is an enum."""
        patch = PRFilePatch(
            file_path="test.py",
            change_type=ChangeType.MODIFIED,
            additions=1,
            deletions=1,
            binary_file=False
        )

        # This is the line that was failing in production
        assert patch.change_type_str == "modified"

    def test_change_type_str_after_serialization_roundtrip(self):
        """change_type_str should work after model_dump() and reconstruction."""
        original = PRFilePatch(
            file_path="test.py",
            change_type=ChangeType.ADDED,
            additions=10,
            deletions=0,
            binary_file=False
        )

        # Simulate serialization (what fetch_pr_context_activity does)
        dumped = original.model_dump()

        # Verify change_type is now a string (due to use_enum_values=True)
        assert isinstance(dumped["change_type"], str)
        assert dumped["change_type"] == "added"

        # Simulate deserialization (what build_seed_set_activity does)
        reconstructed = PRFilePatch(**dumped)

        # This should NOT raise AttributeError: 'str' object has no attribute 'value'
        assert reconstructed.change_type_str == "added"

    def test_change_type_str_all_change_types(self):
        """change_type_str should work for all ChangeType values after roundtrip."""
        for change_type in ChangeType:
            # Skip RENAMED which requires previous_filename
            if change_type == ChangeType.RENAMED:
                patch = PRFilePatch(
                    file_path="test.py",
                    change_type=change_type,
                    previous_filename="old_test.py",
                    additions=0,
                    deletions=0,
                    binary_file=False
                )
            else:
                patch = PRFilePatch(
                    file_path="test.py",
                    change_type=change_type,
                    additions=0,
                    deletions=0,
                    binary_file=False
                )

            # Serialize and deserialize
            dumped = patch.model_dump()
            reconstructed = PRFilePatch(**dumped)

            # change_type_str should work
            assert reconstructed.change_type_str == change_type.value


class TestBuildSeedSetActivityMocked:
    """Tests for build_seed_set_activity with fully mocked dependencies."""

    @pytest.mark.asyncio
    async def test_activity_validates_patches_before_processing(self):
        """Activity should validate patches through validate_patches utility."""
        # Create a mock module to replace seed_generation
        mock_seed_set_builder = MagicMock()
        mock_builder_instance = MagicMock()
        mock_seed_set_builder.return_value = mock_builder_instance

        mock_seed_set = MagicMock()
        mock_seed_set.total_symbols = 0
        mock_seed_set.seed_files = []
        mock_seed_set.model_dump.return_value = {"seed_symbols": [], "seed_files": []}

        mock_stats = MagicMock()
        mock_stats.files_processed = 1
        mock_stats.files_with_symbols = 0
        mock_stats.files_skipped = 1
        mock_stats.total_symbols_extracted = 0
        mock_stats.total_symbols_overlapping = 0
        mock_stats.parse_errors = 0
        mock_stats.unsupported_languages = 0

        mock_builder_instance.build_seed_set.return_value = (mock_seed_set, mock_stats)

        # Create a mock seed_generation module
        mock_module = MagicMock()
        mock_module.SeedSetBuilder = mock_seed_set_builder

        patches_data = [
            {
                "file_path": "test.py",
                "change_type": "modified",  # String - the problematic case
                "additions": 1,
                "deletions": 1,
                "binary_file": False,
                "hunks": []
            }
        ]

        input_data = {
            "clone_path": "/tmp/test",
            "patches": patches_data
        }

        # Mock the imports inside the activity function
        with patch.dict(sys.modules, {'src.services.seed_generation': mock_module}):
            with patch('src.activities.pr_review_activities.pr_review_settings') as mock_settings:
                mock_settings.limits.max_file_size_bytes = 1_000_000
                mock_settings.limits.max_symbols_per_file = 200

                # Import and call the activity
                from src.activities.pr_review_activities import build_seed_set_activity as activity

                result = await activity(input_data)

                assert "seed_set" in result
                assert "stats" in result
