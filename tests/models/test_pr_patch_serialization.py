"""
Unit tests for PRFilePatch serialization and enum handling.

Tests the serialization round-trip scenario where:
1. PRFilePatch with ChangeType enum is serialized with model_dump()
2. use_enum_values=True converts enum to string
3. Deserialization should handle both enum and string values correctly
"""

import pytest
from src.models.schemas.pr_review.pr_patch import (
    PRFilePatch,
    PRHunk,
    ChangeType,
    get_change_type_value,
)
from src.utils.validation import (
    validate_patches,
    validate_change_type,
    safe_enum_value,
)
from src.exceptions.pr_review_exceptions import (
    PatchReconstructionException,
    TypeCoercionException,
)


class TestChangeTypeEnumHandling:
    """Tests for ChangeType enum handling and conversion."""

    def test_get_change_type_value_from_enum(self):
        """get_change_type_value should extract value from ChangeType enum."""
        result = get_change_type_value(ChangeType.MODIFIED)
        assert result == "modified"

    def test_get_change_type_value_from_string(self):
        """get_change_type_value should return string as-is."""
        result = get_change_type_value("modified")
        assert result == "modified"

    def test_get_change_type_value_invalid_type(self):
        """get_change_type_value should raise TypeError for invalid types."""
        with pytest.raises(TypeError) as exc_info:
            get_change_type_value(123)
        assert "Expected ChangeType or str" in str(exc_info.value)

    def test_validate_change_type_from_enum(self):
        """validate_change_type should return enum unchanged."""
        result = validate_change_type(ChangeType.ADDED)
        assert result == ChangeType.ADDED
        assert isinstance(result, ChangeType)

    def test_validate_change_type_from_string(self):
        """validate_change_type should convert valid string to enum."""
        result = validate_change_type("removed")
        assert result == ChangeType.REMOVED
        assert isinstance(result, ChangeType)

    def test_validate_change_type_invalid_string(self):
        """validate_change_type should raise for invalid string values."""
        with pytest.raises(TypeCoercionException):
            validate_change_type("invalid_change_type")


class TestPRFilePatchSerialization:
    """Tests for PRFilePatch serialization round-trip."""

    @pytest.fixture
    def sample_hunk(self):
        """Create a sample PRHunk for testing."""
        return PRHunk(
            hunk_id="hunk_1_test_file_py",
            header="@@ -10,5 +10,6 @@",
            old_start=10,
            old_count=5,
            new_start=10,
            new_count=6,
            lines=[
                " def test_function():",
                "-    old_line",
                "+    new_line",
                "+    added_line",
                " "
            ],
            new_changed_lines=[11, 12]
        )

    @pytest.fixture
    def sample_patch(self, sample_hunk):
        """Create a sample PRFilePatch with enum change_type."""
        return PRFilePatch(
            file_path="src/test_file.py",
            change_type=ChangeType.MODIFIED,
            patch="@@ -10,5 +10,6 @@\n def test...",
            hunks=[sample_hunk],
            additions=2,
            deletions=1,
            binary_file=False
        )

    def test_model_dump_converts_enum_to_string(self, sample_patch):
        """model_dump() should convert ChangeType enum to string."""
        dumped = sample_patch.model_dump()
        assert dumped["change_type"] == "modified"
        assert isinstance(dumped["change_type"], str)

    def test_change_type_str_property_with_enum(self, sample_patch):
        """change_type_str should work when change_type is enum."""
        assert sample_patch.change_type_str == "modified"

    def test_change_type_str_property_after_round_trip(self, sample_patch):
        """change_type_str should work after serialization/deserialization."""
        # Serialize
        dumped = sample_patch.model_dump()

        # Deserialize (simulates what happens in activities)
        reconstructed = PRFilePatch(**dumped)

        # Both should work
        assert reconstructed.change_type_str == "modified"

    def test_full_serialization_round_trip(self, sample_patch):
        """Full round-trip should preserve all data correctly."""
        # Serialize
        dumped = sample_patch.model_dump()

        # Deserialize
        reconstructed = PRFilePatch(**dumped)

        # Verify all fields
        assert reconstructed.file_path == sample_patch.file_path
        assert reconstructed.change_type_str == sample_patch.change_type_str
        assert reconstructed.additions == sample_patch.additions
        assert reconstructed.deletions == sample_patch.deletions
        assert reconstructed.binary_file == sample_patch.binary_file
        assert len(reconstructed.hunks) == len(sample_patch.hunks)

    def test_pre_validator_normalizes_string_to_enum(self):
        """Pre-validator should convert string change_type to enum during construction."""
        # Construct with string value (simulating deserialization)
        patch = PRFilePatch(
            file_path="test.py",
            change_type="added",  # String, not enum
            additions=1,
            deletions=0
        )

        # After validation, change_type should be normalized
        # The change_type_str property should still work
        assert patch.change_type_str == "added"

    def test_pre_validator_accepts_enum(self):
        """Pre-validator should accept ChangeType enum directly."""
        patch = PRFilePatch(
            file_path="test.py",
            change_type=ChangeType.RENAMED,
            previous_filename="old_test.py",
            additions=0,
            deletions=0
        )

        assert patch.change_type_str == "renamed"

    def test_pre_validator_rejects_invalid_change_type(self):
        """Pre-validator should reject invalid change_type values."""
        with pytest.raises(ValueError) as exc_info:
            PRFilePatch(
                file_path="test.py",
                change_type="invalid_type",
                additions=0,
                deletions=0
            )
        assert "Invalid change_type value" in str(exc_info.value)


class TestValidatePatches:
    """Tests for validate_patches utility function."""

    @pytest.fixture
    def valid_patch_dict(self):
        """Create a valid patch dict for testing."""
        return {
            "file_path": "src/example.py",
            "change_type": "modified",
            "additions": 5,
            "deletions": 2,
            "binary_file": False,
            "hunks": []
        }

    def test_validate_patches_with_valid_data(self, valid_patch_dict):
        """validate_patches should successfully reconstruct valid patches."""
        patches = validate_patches([valid_patch_dict])
        assert len(patches) == 1
        assert isinstance(patches[0], PRFilePatch)
        assert patches[0].change_type_str == "modified"

    def test_validate_patches_with_existing_objects(self):
        """validate_patches should pass through existing PRFilePatch objects."""
        existing = PRFilePatch(
            file_path="test.py",
            change_type=ChangeType.ADDED,
            additions=10,
            deletions=0
        )

        patches = validate_patches([existing])
        assert len(patches) == 1
        assert patches[0] is existing

    def test_validate_patches_mixed_input(self, valid_patch_dict):
        """validate_patches should handle mixed dicts and objects."""
        existing = PRFilePatch(
            file_path="existing.py",
            change_type=ChangeType.REMOVED,
            additions=0,
            deletions=5
        )

        patches = validate_patches([valid_patch_dict, existing])
        assert len(patches) == 2

    def test_validate_patches_skips_invalid_when_not_strict(self):
        """validate_patches should skip invalid patches in non-strict mode."""
        valid_dict = {
            "file_path": "valid.py",
            "change_type": "added",
            "additions": 1,
            "deletions": 0
        }
        invalid_dict = {
            "file_path": "",  # Empty path should fail validation
            "change_type": "modified",
            "additions": 0,
            "deletions": 0
        }

        patches = validate_patches([valid_dict, invalid_dict], strict=False)
        assert len(patches) == 1
        assert patches[0].file_path == "valid.py"

    def test_validate_patches_raises_in_strict_mode(self):
        """validate_patches should raise on first error in strict mode."""
        invalid_dict = {
            "file_path": "",
            "change_type": "modified",
            "additions": 0,
            "deletions": 0
        }

        with pytest.raises(PatchReconstructionException):
            validate_patches([invalid_dict], strict=True)

    def test_validate_patches_empty_input(self):
        """validate_patches should handle empty input."""
        patches = validate_patches([])
        assert len(patches) == 0


class TestSafeEnumValue:
    """Tests for the safe_enum_value utility function."""

    def test_safe_enum_value_with_enum(self):
        """safe_enum_value should extract value from enum."""
        result = safe_enum_value(ChangeType.MODIFIED, ChangeType)
        assert result == "modified"

    def test_safe_enum_value_with_string(self):
        """safe_enum_value should return string as-is."""
        result = safe_enum_value("modified", ChangeType)
        assert result == "modified"

    def test_safe_enum_value_with_invalid_type(self):
        """safe_enum_value should raise TypeCoercionException for invalid types."""
        with pytest.raises(TypeCoercionException):
            safe_enum_value(123, ChangeType)
