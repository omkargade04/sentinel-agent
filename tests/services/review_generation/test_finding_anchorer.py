"""
Tests for FindingAnchorerNode

Tests the deterministic anchoring of LLM findings to diff positions.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.services.pr_review.review_generation.finding_anchorer import FindingAnchorerNode


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def anchorer_node():
    """Create a FindingAnchorerNode instance."""
    return FindingAnchorerNode()


@pytest.fixture
def sample_diff_mappings():
    """Create sample diff mappings for testing."""
    return {
        "file_mappings": {
            "src/utils.py": {
                "file_path": "src/utils.py",
                "hunks": [
                    {
                        "hunk_id": "hunk_1",
                        "file_path": "src/utils.py",
                        "old_start": 10,
                        "old_count": 5,
                        "new_start": 10,
                        "new_count": 8,
                        "lines": [
                            " context line",
                            "+added line 1",
                            "+added line 2",
                            " more context",
                            "+added line 3",
                        ],
                        "line_count": 5,
                        "added_line_indexes": [1, 2, 4],
                        "removed_line_indexes": [],
                    },
                    {
                        "hunk_id": "hunk_2",
                        "file_path": "src/utils.py",
                        "old_start": 50,
                        "old_count": 3,
                        "new_start": 53,
                        "new_count": 5,
                        "lines": [
                            " context",
                            "+new code",
                            " more context",
                        ],
                        "line_count": 3,
                        "added_line_indexes": [1],
                        "removed_line_indexes": [],
                    },
                ],
                "hunk_ids": ["hunk_1", "hunk_2"],
                "total_additions": 4,
                "total_deletions": 0,
            },
            "src/main.py": {
                "file_path": "src/main.py",
                "hunks": [
                    {
                        "hunk_id": "hunk_3",
                        "file_path": "src/main.py",
                        "old_start": 1,
                        "old_count": 2,
                        "new_start": 1,
                        "new_count": 3,
                        "lines": [
                            "+import os",
                            " existing line",
                        ],
                        "line_count": 2,
                        "added_line_indexes": [0],
                        "removed_line_indexes": [],
                    },
                ],
                "hunk_ids": ["hunk_3"],
                "total_additions": 1,
                "total_deletions": 0,
            },
        },
        "all_file_paths": ["src/utils.py", "src/main.py"],
        "all_hunk_ids": ["hunk_1", "hunk_2", "hunk_3"],
        "allowed_anchors": [
            ("src/utils.py", "hunk_1"),
            ("src/utils.py", "hunk_2"),
            ("src/main.py", "hunk_3"),
        ],
        "line_to_hunk_lookup": {
            "src/utils.py": {
                10: ("hunk_1", 0),
                11: ("hunk_1", 1),
                12: ("hunk_1", 2),
                53: ("hunk_2", 0),
                54: ("hunk_2", 1),
            },
            "src/main.py": {
                1: ("hunk_3", 0),
            },
        },
        "total_files": 2,
        "total_hunks": 3,
        "total_changed_lines": 5,
    }


@pytest.fixture
def sample_raw_llm_output():
    """Create sample LLM output for testing."""
    return {
        "findings": [
            {
                "title": "Missing null check",
                "message": "The function doesn't validate input",
                "severity": "high",
                "category": "bug",
                "file_path": "src/utils.py",
                "suggested_fix": "Add null check at the beginning",
                "confidence": 0.85,
                "hunk_id": "hunk_1",
                "line_hint": 1,  # Valid line in hunk
                "related_symbols": ["calculate"],
                "code_examples": [],
            },
            {
                "title": "Performance issue",
                "message": "Inefficient loop detected",
                "severity": "medium",
                "category": "performance",
                "file_path": "src/main.py",
                "suggested_fix": "Use list comprehension",
                "confidence": 0.7,
                "hunk_id": "hunk_3",
                "line_hint": 0,
                "related_symbols": [],
                "code_examples": [],
            },
        ],
        "summary": "Test summary",
    }


# ============================================================================
# BASIC ANCHORING TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_anchor_finding_with_valid_hint(anchorer_node, sample_diff_mappings):
    """Test anchoring when LLM provides valid hunk_id and line_hint."""
    state = {
        "raw_llm_output": {
            "findings": [
                {
                    "title": "Test finding",
                    "message": "Test message",
                    "severity": "high",
                    "category": "bug",
                    "file_path": "src/utils.py",
                    "suggested_fix": "Fix it",
                    "confidence": 0.8,
                    "hunk_id": "hunk_1",
                    "line_hint": 2,  # Within hunk bounds (0-4)
                },
            ],
            "summary": "Test",
        },
        "diff_mappings": sample_diff_mappings,
        "context_pack": {},
    }
    
    result = await anchorer_node.execute(state)
    
    assert len(result["anchored_findings"]) == 1
    assert len(result["unanchored_findings"]) == 0
    
    finding = result["anchored_findings"][0]
    assert finding["hunk_id"] == "hunk_1"
    assert finding["line_in_hunk"] == 2
    assert finding["is_anchored"] is True
    assert finding["anchoring_method"] == "hint"


@pytest.mark.asyncio
async def test_anchor_finding_file_not_in_diff(anchorer_node, sample_diff_mappings):
    """Test anchoring when file is not in the diff."""
    state = {
        "raw_llm_output": {
            "findings": [
                {
                    "title": "Test finding",
                    "message": "Test message",
                    "severity": "high",
                    "category": "bug",
                    "file_path": "src/unknown.py",  # Not in diff
                    "suggested_fix": "Fix it",
                    "confidence": 0.8,
                    "hunk_id": "hunk_1",
                    "line_hint": 0,
                },
            ],
            "summary": "Test",
        },
        "diff_mappings": sample_diff_mappings,
        "context_pack": {},
    }
    
    result = await anchorer_node.execute(state)
    
    assert len(result["anchored_findings"]) == 0
    assert len(result["unanchored_findings"]) == 1


@pytest.mark.asyncio
async def test_anchor_finding_invalid_hunk_id(anchorer_node, sample_diff_mappings):
    """Test anchoring with invalid hunk_id falls back to fallback method."""
    state = {
        "raw_llm_output": {
            "findings": [
                {
                    "title": "Test finding",
                    "message": "Test message",
                    "severity": "high",
                    "category": "bug",
                    "file_path": "src/utils.py",
                    "suggested_fix": "Fix it",
                    "confidence": 0.8,
                    "hunk_id": "invalid_hunk",  # Invalid
                    "line_hint": 0,
                },
            ],
            "summary": "Test",
        },
        "diff_mappings": sample_diff_mappings,
        "context_pack": {},
    }
    
    result = await anchorer_node.execute(state)
    
    # Should fallback to first hunk in file
    assert len(result["anchored_findings"]) == 1
    finding = result["anchored_findings"][0]
    assert finding["anchoring_method"] == "fallback"


@pytest.mark.asyncio
async def test_anchor_finding_no_hints(anchorer_node, sample_diff_mappings):
    """Test anchoring when no hints are provided."""
    state = {
        "raw_llm_output": {
            "findings": [
                {
                    "title": "Test finding",
                    "message": "Test message",
                    "severity": "high",
                    "category": "bug",
                    "file_path": "src/utils.py",
                    "suggested_fix": "Fix it",
                    "confidence": 0.8,
                    # No hunk_id or line_hint
                },
            ],
            "summary": "Test",
        },
        "diff_mappings": sample_diff_mappings,
        "context_pack": {},
    }
    
    result = await anchorer_node.execute(state)
    
    assert len(result["anchored_findings"]) == 1
    finding = result["anchored_findings"][0]
    assert finding["anchoring_method"] == "fallback"
    assert finding["hunk_id"] == "hunk_1"  # First hunk


# ============================================================================
# EVIDENCE-BASED ANCHORING TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_anchor_via_evidence(anchorer_node, sample_diff_mappings):
    """Test evidence-based anchoring using context_item_id."""
    state = {
        "raw_llm_output": {
            "findings": [
                {
                    "title": "Test finding",
                    "message": "Test message",
                    "severity": "high",
                    "category": "bug",
                    "file_path": "src/utils.py",
                    "suggested_fix": "Fix it",
                    "confidence": 0.9,
                    "evidence": {
                        "context_item_id": "ctx_1",
                        "snippet_line_range": [1, 3],
                        "quote": "some code",
                    },
                },
            ],
            "summary": "Test",
        },
        "diff_mappings": sample_diff_mappings,
        "context_pack": {
            "context_items": [
                {
                    "item_id": "ctx_1",
                    "file_path": "src/utils.py",
                    "start_line": 10,  # Line 11 should map to hunk_1
                    "end_line": 15,
                },
            ],
        },
    }
    
    result = await anchorer_node.execute(state)
    
    assert len(result["anchored_findings"]) == 1
    finding = result["anchored_findings"][0]
    assert finding["anchoring_method"] == "evidence"
    assert finding["anchoring_confidence"] == 0.9


# ============================================================================
# STATISTICS TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_anchoring_stats(anchorer_node, sample_diff_mappings, sample_raw_llm_output):
    """Test that anchoring stats are correctly computed."""
    state = {
        "raw_llm_output": sample_raw_llm_output,
        "diff_mappings": sample_diff_mappings,
        "context_pack": {},
    }
    
    result = await anchorer_node.execute(state)
    
    stats = result["anchoring_stats"]
    assert stats["total_findings"] == 2
    assert stats["anchored_count"] == 2
    assert stats["unanchored_count"] == 0
    assert stats["anchoring_success_rate"] == 1.0
    assert "anchoring_methods" in stats


@pytest.mark.asyncio
async def test_empty_findings(anchorer_node, sample_diff_mappings):
    """Test handling of empty findings list."""
    state = {
        "raw_llm_output": {"findings": [], "summary": "No issues"},
        "diff_mappings": sample_diff_mappings,
        "context_pack": {},
    }
    
    result = await anchorer_node.execute(state)
    
    assert len(result["anchored_findings"]) == 0
    assert len(result["unanchored_findings"]) == 0
    assert result["anchoring_stats"]["total_findings"] == 0


# ============================================================================
# EDGE CASES
# ============================================================================

@pytest.mark.asyncio
async def test_line_hint_zero_is_valid(anchorer_node, sample_diff_mappings):
    """Test that line_hint=0 is correctly handled (not treated as falsy)."""
    state = {
        "raw_llm_output": {
            "findings": [
                {
                    "title": "Test finding",
                    "message": "Test message",
                    "severity": "high",
                    "category": "bug",
                    "file_path": "src/main.py",
                    "suggested_fix": "Fix it",
                    "confidence": 0.8,
                    "hunk_id": "hunk_3",
                    "line_hint": 0,  # Valid 0-indexed line
                },
            ],
            "summary": "Test",
        },
        "diff_mappings": sample_diff_mappings,
        "context_pack": {},
    }
    
    result = await anchorer_node.execute(state)
    
    assert len(result["anchored_findings"]) == 1
    finding = result["anchored_findings"][0]
    assert finding["line_in_hunk"] == 0
    assert finding["anchoring_method"] == "hint"


@pytest.mark.asyncio
async def test_line_hint_out_of_bounds(anchorer_node, sample_diff_mappings):
    """Test handling of line_hint that's out of hunk bounds."""
    state = {
        "raw_llm_output": {
            "findings": [
                {
                    "title": "Test finding",
                    "message": "Test message",
                    "severity": "high",
                    "category": "bug",
                    "file_path": "src/utils.py",
                    "suggested_fix": "Fix it",
                    "confidence": 0.8,
                    "hunk_id": "hunk_1",
                    "line_hint": 100,  # Out of bounds (hunk has 5 lines)
                },
            ],
            "summary": "Test",
        },
        "diff_mappings": sample_diff_mappings,
        "context_pack": {},
    }
    
    result = await anchorer_node.execute(state)
    
    # Should still anchor but use first added line
    assert len(result["anchored_findings"]) == 1
    finding = result["anchored_findings"][0]
    assert finding["hunk_id"] == "hunk_1"
    assert finding["is_anchored"] is True


@pytest.mark.asyncio
async def test_multiple_findings_different_files(anchorer_node, sample_diff_mappings):
    """Test anchoring findings across multiple files."""
    state = {
        "raw_llm_output": {
            "findings": [
                {
                    "title": "Finding in utils",
                    "message": "Issue in utils",
                    "severity": "high",
                    "category": "bug",
                    "file_path": "src/utils.py",
                    "suggested_fix": "Fix utils",
                    "confidence": 0.8,
                },
                {
                    "title": "Finding in main",
                    "message": "Issue in main",
                    "severity": "medium",
                    "category": "style",
                    "file_path": "src/main.py",
                    "suggested_fix": "Fix main",
                    "confidence": 0.7,
                },
                {
                    "title": "Finding in unknown",
                    "message": "Issue in unknown file",
                    "severity": "low",
                    "category": "style",
                    "file_path": "src/unknown.py",  # Not in diff
                    "suggested_fix": "Fix it",
                    "confidence": 0.6,
                },
            ],
            "summary": "Multiple findings",
        },
        "diff_mappings": sample_diff_mappings,
        "context_pack": {},
    }
    
    result = await anchorer_node.execute(state)
    
    assert len(result["anchored_findings"]) == 2
    assert len(result["unanchored_findings"]) == 1
    
    # Check anchored findings are from correct files
    anchored_files = {f["file_path"] for f in result["anchored_findings"]}
    assert anchored_files == {"src/utils.py", "src/main.py"}


# ============================================================================
# GRACEFUL DEGRADATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_graceful_degradation_on_error(anchorer_node):
    """Test graceful degradation when anchoring fails completely."""
    # Provide malformed state that will cause an error
    state = {
        "raw_llm_output": {
            "findings": [{"title": "Test", "message": "Test", "file_path": "test.py"}],
            "summary": "Test",
        },
        "diff_mappings": None,  # This will cause an error
        "context_pack": {},
    }
    
    # The node should handle errors gracefully
    result = await anchorer_node._attempt_graceful_degradation(
        state, Exception("Test error"), None
    )
    
    assert result is not None
    assert len(result["anchored_findings"]) == 0
    assert len(result["unanchored_findings"]) == 1
    assert "degraded" in result["anchoring_stats"]["anchoring_methods"]
