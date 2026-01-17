"""
Tests for QualityValidatorNode

Tests the quality validation, filtering, and final output generation.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.pr_review.review_generation.quality_validator import QualityValidatorNode


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def validator_node():
    """Create a QualityValidatorNode instance."""
    return QualityValidatorNode()


@pytest.fixture
def sample_anchored_findings():
    """Create sample anchored findings."""
    return [
        {
            "title": "Critical bug",
            "message": "Null pointer dereference",
            "severity": "blocker",
            "category": "bug",
            "file_path": "src/main.py",
            "suggested_fix": "Add null check",
            "confidence": 0.95,
            "hunk_id": "hunk_1",
            "line_in_hunk": 5,
            "is_anchored": True,
            "related_symbols": ["process"],
            "code_examples": ["def process(): pass"],
        },
        {
            "title": "Security issue",
            "message": "SQL injection vulnerability",
            "severity": "high",
            "category": "security",
            "file_path": "src/db.py",
            "suggested_fix": "Use parameterized queries",
            "confidence": 0.9,
            "hunk_id": "hunk_2",
            "line_in_hunk": 10,
            "is_anchored": True,
            "related_symbols": [],
            "code_examples": [],
        },
        {
            "title": "Style issue",
            "message": "Line too long",
            "severity": "nit",
            "category": "style",
            "file_path": "src/utils.py",
            "suggested_fix": "Break into multiple lines",
            "confidence": 0.7,
            "hunk_id": "hunk_3",
            "line_in_hunk": 2,
            "is_anchored": True,
            "related_symbols": [],
            "code_examples": [],
        },
    ]


@pytest.fixture
def sample_unanchored_findings():
    """Create sample unanchored findings."""
    return [
        {
            "title": "Documentation missing",
            "message": "Module lacks docstring",
            "severity": "low",
            "category": "docs",
            "file_path": "src/helpers.py",
            "suggested_fix": "Add module docstring",
            "confidence": 0.6,
            "related_symbols": [],
            "code_examples": [],
        },
    ]


@pytest.fixture
def sample_raw_llm_output():
    """Create sample raw LLM output."""
    return {
        "summary": "This PR introduces critical changes with some issues to address.",
        "patterns": ["Missing null checks", "Inconsistent error handling"],
        "recommendations": ["Add comprehensive input validation"],
        "findings": [],  # Not used directly by validator
    }


# ============================================================================
# BASIC VALIDATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_basic_validation(
    validator_node, sample_anchored_findings, sample_unanchored_findings, sample_raw_llm_output
):
    """Test basic validation produces valid output."""
    state = {
        "anchored_findings": sample_anchored_findings,
        "unanchored_findings": sample_unanchored_findings,
        "raw_llm_output": sample_raw_llm_output,
        "llm_token_usage": {"input_tokens": 1000, "output_tokens": 500, "model": "claude-3"},
    }
    
    result = await validator_node.execute(state)
    
    final_output = result["final_review_output"]
    
    # Basic structure checks
    assert "findings" in final_output
    assert "summary" in final_output
    assert "total_findings" in final_output
    assert "review_timestamp" in final_output
    
    # Findings should have IDs
    for i, finding in enumerate(final_output["findings"], start=1):
        assert finding["finding_id"] == f"finding_{i}"


@pytest.mark.asyncio
async def test_findings_sorted_by_severity(
    validator_node, sample_anchored_findings, sample_raw_llm_output
):
    """Test that findings are sorted by severity (blocker first)."""
    # Reverse order to verify sorting works
    reversed_findings = list(reversed(sample_anchored_findings))
    
    state = {
        "anchored_findings": reversed_findings,
        "unanchored_findings": [],
        "raw_llm_output": sample_raw_llm_output,
        "llm_token_usage": {},
    }
    
    result = await validator_node.execute(state)
    
    findings = result["final_review_output"]["findings"]
    severities = [f["severity"] for f in findings]
    
    # Blocker should come first, then high, then nit
    assert severities == ["blocker", "high", "nit"]


# ============================================================================
# FILTERING TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_confidence_filtering(validator_node, sample_raw_llm_output):
    """Test that low confidence findings are filtered out."""
    findings = [
        {
            "title": "High confidence",
            "message": "Clear issue",
            "severity": "high",
            "category": "bug",
            "file_path": "test.py",
            "suggested_fix": "Fix it",
            "confidence": 0.8,
            "hunk_id": "hunk_1",
            "line_in_hunk": 0,
        },
        {
            "title": "Low confidence",
            "message": "Unclear issue",
            "severity": "medium",
            "category": "style",
            "file_path": "test.py",
            "suggested_fix": "Maybe fix",
            "confidence": 0.3,  # Below threshold (0.5)
            "hunk_id": "hunk_2",
            "line_in_hunk": 0,
        },
    ]
    
    state = {
        "anchored_findings": findings,
        "unanchored_findings": [],
        "raw_llm_output": sample_raw_llm_output,
        "llm_token_usage": {},
    }
    
    result = await validator_node.execute(state)
    
    assert len(result["final_review_output"]["findings"]) == 1
    assert result["final_review_output"]["findings"][0]["title"] == "High confidence"
    
    # Check stats
    stats = result["final_review_output"]["validation_stats"]
    assert stats["confidence_filtered"] == 1


@pytest.mark.asyncio
async def test_deduplication(validator_node, sample_raw_llm_output):
    """Test that duplicate findings are removed."""
    findings = [
        {
            "title": "Duplicate issue",
            "message": "First occurrence",
            "severity": "high",
            "category": "bug",
            "file_path": "test.py",
            "suggested_fix": "Fix it",
            "confidence": 0.7,
            "hunk_id": "hunk_1",
            "line_in_hunk": 0,
        },
        {
            "title": "Duplicate issue",  # Same title
            "message": "Second occurrence with lower confidence",
            "severity": "high",
            "category": "bug",
            "file_path": "test.py",  # Same file
            "suggested_fix": "Fix it again",
            "confidence": 0.6,  # Lower confidence
            "hunk_id": "hunk_2",
            "line_in_hunk": 5,
        },
    ]
    
    state = {
        "anchored_findings": findings,
        "unanchored_findings": [],
        "raw_llm_output": sample_raw_llm_output,
        "llm_token_usage": {},
    }
    
    result = await validator_node.execute(state)
    
    # Only one finding should remain (the one with higher confidence)
    assert len(result["final_review_output"]["findings"]) == 1
    assert result["final_review_output"]["findings"][0]["confidence"] == 0.7


@pytest.mark.asyncio
async def test_max_findings_limit(validator_node, sample_raw_llm_output):
    """Test that findings are limited to max count (20)."""
    # Create 25 findings
    findings = [
        {
            "title": f"Finding {i}",
            "message": f"Issue {i}",
            "severity": "medium",
            "category": "style",
            "file_path": f"file_{i}.py",
            "suggested_fix": f"Fix {i}",
            "confidence": 0.8,
            "hunk_id": f"hunk_{i}",
            "line_in_hunk": i,
        }
        for i in range(25)
    ]
    
    state = {
        "anchored_findings": findings,
        "unanchored_findings": [],
        "raw_llm_output": sample_raw_llm_output,
        "llm_token_usage": {},
    }
    
    result = await validator_node.execute(state)
    
    # Should be limited to 20
    assert len(result["final_review_output"]["findings"]) == 20
    assert result["final_review_output"]["validation_stats"]["truncated_count"] == 5


# ============================================================================
# FINDING ID ASSIGNMENT TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_finding_ids_sequential(
    validator_node, sample_anchored_findings, sample_raw_llm_output
):
    """Test that finding IDs are sequential (finding_1, finding_2, etc.)."""
    state = {
        "anchored_findings": sample_anchored_findings,
        "unanchored_findings": [],
        "raw_llm_output": sample_raw_llm_output,
        "llm_token_usage": {},
    }
    
    result = await validator_node.execute(state)
    
    findings = result["final_review_output"]["findings"]
    expected_ids = [f"finding_{i}" for i in range(1, len(findings) + 1)]
    actual_ids = [f["finding_id"] for f in findings]
    
    assert actual_ids == expected_ids


# ============================================================================
# SEVERITY COUNTS TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_severity_counts(
    validator_node, sample_anchored_findings, sample_raw_llm_output
):
    """Test that severity counts are correctly computed."""
    state = {
        "anchored_findings": sample_anchored_findings,
        "unanchored_findings": [],
        "raw_llm_output": sample_raw_llm_output,
        "llm_token_usage": {},
    }
    
    result = await validator_node.execute(state)
    
    final_output = result["final_review_output"]
    
    assert final_output["blocker_count"] == 1
    assert final_output["high_count"] == 1
    assert final_output["medium_count"] == 0
    assert final_output["low_count"] == 0
    assert final_output["nit_count"] == 1


# ============================================================================
# SUMMARY BUILDING TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_summary_includes_unanchored(
    validator_node, sample_anchored_findings, sample_unanchored_findings, sample_raw_llm_output
):
    """Test that summary includes unanchored findings."""
    state = {
        "anchored_findings": sample_anchored_findings,
        "unanchored_findings": sample_unanchored_findings,
        "raw_llm_output": sample_raw_llm_output,
        "llm_token_usage": {},
    }
    
    result = await validator_node.execute(state)
    
    summary = result["final_review_output"]["summary"]
    
    # Should contain original summary
    assert "critical changes" in summary
    
    # Should mention unanchored findings
    assert "Additional Issues" in summary or "not anchored" in summary


@pytest.mark.asyncio
async def test_summary_no_unanchored(
    validator_node, sample_anchored_findings, sample_raw_llm_output
):
    """Test summary when all findings are anchored."""
    state = {
        "anchored_findings": sample_anchored_findings,
        "unanchored_findings": [],
        "raw_llm_output": sample_raw_llm_output,
        "llm_token_usage": {},
    }
    
    result = await validator_node.execute(state)
    
    summary = result["final_review_output"]["summary"]
    
    # Should just be original summary
    assert "Additional Issues" not in summary


# ============================================================================
# TOKEN USAGE TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_token_usage_included(
    validator_node, sample_anchored_findings, sample_raw_llm_output
):
    """Test that token usage is included in stats."""
    state = {
        "anchored_findings": sample_anchored_findings,
        "unanchored_findings": [],
        "raw_llm_output": sample_raw_llm_output,
        "llm_token_usage": {
            "input_tokens": 5000,
            "output_tokens": 1000,
            "total_tokens": 6000,
            "model": "claude-3-opus",
        },
    }
    
    result = await validator_node.execute(state)
    
    stats = result["final_review_output"]["stats"]
    
    assert stats["token_usage"]["prompt_tokens"] == 5000
    assert stats["token_usage"]["completion_tokens"] == 1000
    assert stats["token_usage"]["total_tokens"] == 6000
    assert stats["model_used"] == "claude-3-opus"


@pytest.mark.asyncio
async def test_missing_token_usage(
    validator_node, sample_anchored_findings, sample_raw_llm_output
):
    """Test handling of missing token usage data."""
    state = {
        "anchored_findings": sample_anchored_findings,
        "unanchored_findings": [],
        "raw_llm_output": sample_raw_llm_output,
        "llm_token_usage": {},  # Empty
    }
    
    result = await validator_node.execute(state)
    
    # Should still work
    assert result["final_review_output"]["model_used"] == "unknown"


# ============================================================================
# ANCHORED VS UNANCHORED PRIORITY TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_anchored_prioritized_over_unanchored(validator_node, sample_raw_llm_output):
    """Test that anchored findings are prioritized when limit is applied."""
    # Create findings that exceed limit
    anchored = [
        {
            "title": f"Anchored {i}",
            "message": f"Anchored issue {i}",
            "severity": "medium",
            "category": "style",
            "file_path": f"file_{i}.py",
            "suggested_fix": "Fix",
            "confidence": 0.8,
            "hunk_id": f"hunk_{i}",
            "line_in_hunk": 0,
        }
        for i in range(15)
    ]
    
    unanchored = [
        {
            "title": f"Unanchored {i}",
            "message": f"Unanchored issue {i}",
            "severity": "high",  # Higher severity but unanchored
            "category": "bug",
            "file_path": f"other_{i}.py",
            "suggested_fix": "Fix",
            "confidence": 0.9,
        }
        for i in range(10)
    ]
    
    # Use custom limit of 18
    validator = QualityValidatorNode(max_findings=18)
    
    state = {
        "anchored_findings": anchored,
        "unanchored_findings": unanchored,
        "raw_llm_output": sample_raw_llm_output,
        "llm_token_usage": {},
    }
    
    result = await validator.execute(state)
    
    findings = result["final_review_output"]["findings"]
    
    # All 15 anchored should be included, plus 3 unanchored
    assert len(findings) == 18
    
    # First 15 should be anchored
    anchored_count = sum(1 for f in findings if f.get("hunk_id"))
    assert anchored_count >= 15


# ============================================================================
# EDGE CASES
# ============================================================================

@pytest.mark.asyncio
async def test_empty_findings(validator_node, sample_raw_llm_output):
    """Test handling of empty findings."""
    state = {
        "anchored_findings": [],
        "unanchored_findings": [],
        "raw_llm_output": sample_raw_llm_output,
        "llm_token_usage": {},
    }
    
    result = await validator_node.execute(state)
    
    final_output = result["final_review_output"]
    
    assert final_output["total_findings"] == 0
    assert len(final_output["findings"]) == 0
    assert final_output["summary"] == sample_raw_llm_output["summary"]


@pytest.mark.asyncio
async def test_patterns_and_recommendations_preserved(
    validator_node, sample_anchored_findings, sample_raw_llm_output
):
    """Test that patterns and recommendations are preserved."""
    state = {
        "anchored_findings": sample_anchored_findings,
        "unanchored_findings": [],
        "raw_llm_output": sample_raw_llm_output,
        "llm_token_usage": {},
    }
    
    result = await validator_node.execute(state)
    
    final_output = result["final_review_output"]
    
    assert final_output["patterns"] == sample_raw_llm_output["patterns"]
    assert final_output["recommendations"] == sample_raw_llm_output["recommendations"]


@pytest.mark.asyncio
async def test_high_confidence_count(validator_node, sample_raw_llm_output):
    """Test high confidence findings count."""
    findings = [
        {
            "title": "High conf 1",
            "message": "Issue",
            "severity": "high",
            "category": "bug",
            "file_path": "test.py",
            "suggested_fix": "Fix",
            "confidence": 0.9,  # High confidence (>= 0.7)
            "hunk_id": "hunk_1",
            "line_in_hunk": 0,
        },
        {
            "title": "High conf 2",
            "message": "Issue",
            "severity": "medium",
            "category": "style",
            "file_path": "test2.py",
            "suggested_fix": "Fix",
            "confidence": 0.75,  # High confidence
            "hunk_id": "hunk_2",
            "line_in_hunk": 0,
        },
        {
            "title": "Low conf",
            "message": "Issue",
            "severity": "low",
            "category": "docs",
            "file_path": "test3.py",
            "suggested_fix": "Fix",
            "confidence": 0.55,  # Not high confidence
            "hunk_id": "hunk_3",
            "line_in_hunk": 0,
        },
    ]
    
    state = {
        "anchored_findings": findings,
        "unanchored_findings": [],
        "raw_llm_output": sample_raw_llm_output,
        "llm_token_usage": {},
    }
    
    result = await validator_node.execute(state)
    
    assert result["final_review_output"]["high_confidence_findings"] == 2


# ============================================================================
# GRACEFUL DEGRADATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_graceful_degradation(validator_node):
    """Test graceful degradation on error."""
    state = {
        "anchored_findings": [],
        "unanchored_findings": [],
        "raw_llm_output": {"summary": "Original summary"},
        "llm_token_usage": {},
    }
    
    result = await validator_node._attempt_graceful_degradation(
        state, Exception("Test error"), None
    )
    
    assert result is not None
    assert "final_review_output" in result
    assert result["final_review_output"]["total_findings"] == 0
    assert "validation_error" in result["final_review_output"]
