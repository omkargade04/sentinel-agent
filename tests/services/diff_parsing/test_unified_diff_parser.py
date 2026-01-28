"""
Tests for UnifiedDiffParser

Tests diff parsing functionality with various GitHub diff formats.
"""

import pytest
from src.services.diff_parsing.unified_diff_parser import UnifiedDiffParser
from src.models.schemas.pr_review.pr_patch import FileChangeType, FileStatus
from src.exceptions.pr_review_exceptions import (
    InvalidDiffFormatException,
    PRHunkParsingException,
    BinaryFileException
)


@pytest.fixture
def diff_parser():
    """Create UnifiedDiffParser instance for testing."""
    return UnifiedDiffParser()


@pytest.fixture
def sample_file_data():
    """Sample file data from GitHub API."""
    return {
        "filename": "src/example.py",
        "status": "modified",
        "additions": 3,
        "deletions": 1,
        "changes": 4,
        "patch": """@@ -1,4 +1,6 @@
 def example_function():
-    return False
+    # Added a comment
+    return True
+    # Another new line
     pass"""
    }


@pytest.fixture
def complex_diff_data():
    """Complex diff with multiple hunks."""
    return {
        "filename": "src/complex.py",
        "status": "modified",
        "additions": 8,
        "deletions": 3,
        "changes": 11,
        "patch": """@@ -10,6 +10,9 @@ class ExampleClass:
     def method_one(self):
-        return None
+        # Updated implementation
+        result = self.calculate()
+        return result

     def method_two(self):
@@ -25,4 +28,7 @@ class ExampleClass:
         pass

     def new_method(self):
+        # This is a new method
+        for i in range(10):
+            print(i)
         return True"""
    }


@pytest.fixture
def binary_file_data():
    """Binary file data from GitHub API."""
    return {
        "filename": "image.png",
        "status": "added",
        "additions": 0,
        "deletions": 0,
        "changes": 0,
        "binary": True,
        "patch": None
    }


@pytest.fixture
def renamed_file_data():
    """Renamed file data from GitHub API."""
    return {
        "filename": "src/new_name.py",
        "previous_filename": "src/old_name.py",
        "status": "renamed",
        "additions": 0,
        "deletions": 0,
        "changes": 0,
        "patch": ""
    }


class TestUnifiedDiffParser:
    """Test suite for UnifiedDiffParser."""

    def test_parse_simple_file_success(self, diff_parser, sample_file_data):
        """Test parsing a simple modified file."""
        patches = diff_parser.parse_pr_files([sample_file_data])

        assert len(patches) == 1
        patch = patches[0]

        assert patch.file_path == "src/example.py"
        assert patch.change_type == FileChangeType.MODIFIED
        assert patch.status == FileStatus.MODIFIED
        assert patch.additions == 3
        assert patch.deletions == 1
        assert patch.changes == 4
        assert len(patch.hunks) == 1

        hunk = patch.hunks[0]
        assert hunk.old_start == 1
        assert hunk.old_count == 4
        assert hunk.new_start == 1
        assert hunk.new_count == 6
        assert len(hunk.new_changed_lines) == 3  # Three + lines

    def test_parse_complex_file_multiple_hunks(self, diff_parser, complex_diff_data):
        """Test parsing a file with multiple hunks."""
        patches = diff_parser.parse_pr_files([complex_diff_data])

        assert len(patches) == 1
        patch = patches[0]

        assert patch.file_path == "src/complex.py"
        assert len(patch.hunks) == 2

        # First hunk
        hunk1 = patch.hunks[0]
        assert hunk1.old_start == 10
        assert hunk1.new_start == 10

        # Second hunk
        hunk2 = patch.hunks[1]
        assert hunk2.old_start == 25
        assert hunk2.new_start == 28

    def test_parse_binary_file_exception(self, diff_parser, binary_file_data):
        """Test that binary files raise appropriate exception."""
        with pytest.raises(BinaryFileException) as exc_info:
            diff_parser.parse_pr_files([binary_file_data])

        assert "image.png" in str(exc_info.value)

    def test_parse_renamed_file(self, diff_parser, renamed_file_data):
        """Test parsing a renamed file with no content changes."""
        patches = diff_parser.parse_pr_files([renamed_file_data])

        assert len(patches) == 1
        patch = patches[0]

        assert patch.file_path == "src/new_name.py"
        assert patch.previous_filename == "src/old_name.py"
        assert patch.status == FileStatus.RENAMED
        assert patch.change_type == FileChangeType.RENAMED
        assert len(patch.hunks) == 0

    def test_hunk_id_generation(self, diff_parser):
        """Test deterministic hunk ID generation."""
        file_path = "src/test.py"
        hunk_header = "@@ -10,5 +10,7 @@ def test_function():"

        hunk_id1 = diff_parser.generate_hunk_id(file_path, hunk_header)
        hunk_id2 = diff_parser.generate_hunk_id(file_path, hunk_header)

        # Should be deterministic
        assert hunk_id1 == hunk_id2
        assert hunk_id1.startswith("hunk_")
        assert len(hunk_id1) == 17  # "hunk_" + 12 char hash

        # Different inputs should produce different IDs
        different_id = diff_parser.generate_hunk_id("other/file.py", hunk_header)
        assert hunk_id1 != different_id

    def test_extract_changed_lines(self, diff_parser):
        """Test changed line extraction from hunk."""
        hunk_lines = [
            "@@ -1,4 +1,6 @@",
            " def function():",
            "-    old_line",
            "+    new_line",
            "+    added_line",
            " unchanged_line",
            "+    final_added_line"
        ]

        changed_lines = diff_parser.extract_changed_lines(hunk_lines, 1)

        # Should have line numbers 2, 3, 5 (new version line numbers)
        assert changed_lines == [2, 3, 5]

    def test_invalid_hunk_header(self, diff_parser):
        """Test handling of invalid hunk headers."""
        invalid_file_data = {
            "filename": "invalid.py",
            "status": "modified",
            "additions": 1,
            "deletions": 1,
            "changes": 2,
            "patch": "invalid hunk header\n+new line\n-old line"
        }

        with pytest.raises(InvalidDiffFormatException):
            diff_parser.parse_pr_files([invalid_file_data])

    def test_file_status_determination(self, diff_parser):
        """Test file status determination from GitHub data."""
        test_cases = [
            ({"status": "added"}, FileStatus.ADDED),
            ({"status": "removed"}, FileStatus.DELETED),
            ({"status": "modified"}, FileStatus.MODIFIED),
            ({"status": "renamed"}, FileStatus.RENAMED),
            ({"status": "copied"}, FileStatus.COPIED),
            ({"status": "unknown"}, FileStatus.MODIFIED),  # Default
        ]

        for file_data, expected_status in test_cases:
            file_data.update({
                "filename": "test.py",
                "additions": 0,
                "deletions": 0,
                "changes": 0,
                "patch": ""
            })

            result_status = diff_parser._determine_file_status(file_data)
            assert result_status == expected_status

    def test_change_type_determination(self, diff_parser):
        """Test change type determination from file data."""
        test_cases = [
            ({"status": "added", "additions": 10, "deletions": 0}, FileChangeType.ADDED),
            ({"status": "removed", "additions": 0, "deletions": 10}, FileChangeType.DELETED),
            ({"status": "renamed", "additions": 0, "deletions": 0}, FileChangeType.RENAMED),
            ({"status": "modified", "additions": 5, "deletions": 3}, FileChangeType.MODIFIED),
            ({"status": "modified", "additions": 5, "deletions": 0}, FileChangeType.ADDED),
            ({"status": "modified", "additions": 0, "deletions": 5}, FileChangeType.DELETED),
        ]

        for file_data, expected_type in test_cases:
            result_type = diff_parser._determine_change_type(file_data)
            assert result_type == expected_type

    def test_binary_file_detection(self, diff_parser):
        """Test binary file detection methods."""
        # Explicit binary flag
        assert diff_parser._is_binary_file({"binary": True}) is True

        # Binary diff pattern
        binary_patch_file = {
            "filename": "test.zip",
            "patch": "Binary files a/test.zip and b/test.zip differ"
        }
        assert diff_parser._is_binary_file(binary_patch_file) is True

        # Binary extension
        binary_ext_file = {"filename": "image.png"}
        assert diff_parser._is_binary_file(binary_ext_file) is True

        # Regular text file
        text_file = {
            "filename": "script.py",
            "patch": "@@ -1,1 +1,1 @@\n-print('old')\n+print('new')"
        }
        assert diff_parser._is_binary_file(text_file) is False

    def test_patch_integrity_validation(self, diff_parser, sample_file_data):
        """Test patch integrity validation."""
        patches = diff_parser.parse_pr_files([sample_file_data])
        patch = patches[0]

        warnings = diff_parser.validate_patch_integrity(patch)

        # Should have no warnings for well-formed patch
        assert len(warnings) == 0

    def test_patch_integrity_validation_mismatch(self, diff_parser):
        """Test patch integrity validation with mismatched counts."""
        # Create file data with mismatched counts
        mismatched_file_data = {
            "filename": "test.py",
            "status": "modified",
            "additions": 5,  # Says 5 additions
            "deletions": 2,  # Says 2 deletions
            "changes": 7,
            "patch": "@@ -1,2 +1,3 @@\n def func():\n-    return False\n+    return True"  # Actually 1 addition, 1 deletion
        }

        patches = diff_parser.parse_pr_files([mismatched_file_data])
        patch = patches[0]

        warnings = diff_parser.validate_patch_integrity(patch)

        # Should have warnings about count mismatches
        assert len(warnings) >= 2
        assert any("Addition count mismatch" in warning for warning in warnings)
        assert any("Deletion count mismatch" in warning for warning in warnings)

    def test_empty_patch_handling(self, diff_parser):
        """Test handling of files with empty patches."""
        empty_patch_file = {
            "filename": "empty.py",
            "status": "modified",
            "additions": 0,
            "deletions": 0,
            "changes": 0,
            "patch": ""
        }

        patches = diff_parser.parse_pr_files([empty_patch_file])

        assert len(patches) == 1
        patch = patches[0]
        assert len(patch.hunks) == 0

    def test_missing_filename_error(self, diff_parser):
        """Test error handling for missing filename."""
        invalid_file_data = {
            "status": "modified",
            "additions": 1,
            "deletions": 0,
            "changes": 1,
            "patch": "@@ -1,1 +1,2 @@\n line1\n+line2"
        }

        with pytest.raises(InvalidDiffFormatException) as exc_info:
            diff_parser.parse_pr_files([invalid_file_data])

        assert "File missing filename" in str(exc_info.value)

    def test_large_file_handling(self, diff_parser):
        """Test handling of files with many hunks."""
        # Create a file with multiple hunks
        many_hunks_patch = ""
        for i in range(10):
            many_hunks_patch += f"@@ -{i*10+1},2 +{i*10+1},3 @@\n line\n-old{i}\n+new{i}\n+added{i}\n"

        large_file_data = {
            "filename": "large.py",
            "status": "modified",
            "additions": 20,
            "deletions": 10,
            "changes": 30,
            "patch": many_hunks_patch
        }

        patches = diff_parser.parse_pr_files([large_file_data])

        assert len(patches) == 1
        patch = patches[0]
        assert len(patch.hunks) == 10

        # Check that hunk IDs are unique
        hunk_ids = [hunk.hunk_id for hunk in patch.hunks]
        assert len(set(hunk_ids)) == len(hunk_ids)  # All unique