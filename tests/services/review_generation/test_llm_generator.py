"""
Unit Tests for LLMGeneratorNode

Tests JSON extraction, schema normalization, and validation.
"""

import pytest
import json
from unittest.mock import AsyncMock, Mock

from src.services.pr_review.review_generation.llm_generator import LLMGeneratorNode
from src.services.pr_review.review_generation.schema import (
    RawLLMReviewOutput,
    StructuredPrompt,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client."""
    client = Mock()
    client.provider_name = "mock"
    client.model = "mock-model"
    client.generate_completion = AsyncMock()
    return client


@pytest.fixture
def llm_generator_node(mock_llm_client):
    """Create LLMGeneratorNode with mocked client."""
    return LLMGeneratorNode(llm_client=mock_llm_client)


@pytest.fixture
def sample_structured_prompt():
    """Create a sample structured prompt."""
    return StructuredPrompt(
        system_prompt="You are a code reviewer.",
        user_prompt="Review this code.",
        output_schema_json="{}",
        estimated_max_completion_tokens=4000,
    )


@pytest.fixture
def sample_state(sample_structured_prompt):
    """Create sample workflow state."""
    return {
        "structured_prompt": sample_structured_prompt.model_dump(),
        "context_pack": {"context_items": []},
    }


@pytest.fixture
def valid_llm_response():
    """Valid LLM response with findings."""
    return {
        "findings": [
            {
                "title": "Missing null check",
                "message": "The variable may be null",
                "severity": "high",
                "category": "bug",
                "file_path": "src/main.py",
                "hunk_id": "hunk_1_src_main_py",
                "suggested_fix": "Add null check",
                "confidence": 0.85,
                "evidence": {
                    "context_item_id": "ctx_123",
                    "snippet_line_range": [10, 15],
                    "quote": "x = get_value()"
                },
                "related_symbols": ["get_value"]
            }
        ],
        "summary": "Found 1 issue in the code."
    }


# ============================================================================
# JSON EXTRACTION TESTS
# ============================================================================

class TestJSONExtraction:
    """Test JSON extraction strategies."""

    @pytest.mark.asyncio
    async def test_direct_json_response(self, llm_generator_node, mock_llm_client, sample_state, valid_llm_response):
        """Test parsing direct JSON response."""
        mock_llm_client.generate_completion.return_value = {
            "content": json.dumps(valid_llm_response),
            "usage": {"input_tokens": 100, "output_tokens": 200},
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        assert "raw_llm_output" in result.data
        assert len(result.data["raw_llm_output"]["findings"]) == 1

    @pytest.mark.asyncio
    async def test_json_in_code_block(self, llm_generator_node, mock_llm_client, sample_state, valid_llm_response):
        """Test parsing JSON wrapped in code block."""
        content = f"Here is my review:\n\n```json\n{json.dumps(valid_llm_response)}\n```\n\nLet me know if you have questions."
        
        mock_llm_client.generate_completion.return_value = {
            "content": content,
            "usage": {"input_tokens": 100, "output_tokens": 200},
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        assert len(result.data["raw_llm_output"]["findings"]) == 1

    @pytest.mark.asyncio
    async def test_json_with_surrounding_text(self, llm_generator_node, mock_llm_client, sample_state, valid_llm_response):
        """Test parsing JSON with prose before and after."""
        content = f"After reviewing the code, I found:\n\n{json.dumps(valid_llm_response)}\n\nPlease review these findings."
        
        mock_llm_client.generate_completion.return_value = {
            "content": content,
            "usage": {"input_tokens": 100, "output_tokens": 200},
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        assert len(result.data["raw_llm_output"]["findings"]) == 1

    @pytest.mark.asyncio
    async def test_empty_response_triggers_degradation(self, llm_generator_node, mock_llm_client, sample_state):
        """Test that empty response triggers graceful degradation."""
        mock_llm_client.generate_completion.return_value = {
            "content": "",
            "usage": {"input_tokens": 100, "output_tokens": 0},
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        # Should use graceful degradation
        assert "raw_llm_output" in result.data
        assert len(result.data["raw_llm_output"]["findings"]) == 0

    @pytest.mark.asyncio
    async def test_invalid_json_triggers_degradation(self, llm_generator_node, mock_llm_client, sample_state):
        """Test that completely invalid response triggers graceful degradation."""
        mock_llm_client.generate_completion.return_value = {
            "content": "I cannot provide a review because the code is too complex.",
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        # Should use graceful degradation (empty findings)
        assert "raw_llm_output" in result.data

    @pytest.mark.asyncio
    async def test_json_with_trailing_commas(self, llm_generator_node, mock_llm_client, sample_state):
        """Test that trailing commas in JSON are repaired."""
        content = '{"findings": [{"title": "Test", "message": "msg", "severity": "high", "category": "bug", "file_path": "test.py", "suggested_fix": "fix", "confidence": 0.8,}], "summary": "test",}'
        
        mock_llm_client.generate_completion.return_value = {
            "content": content,
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        assert len(result.data["raw_llm_output"]["findings"]) == 1


# ============================================================================
# SCHEMA NORMALIZATION TESTS
# ============================================================================

class TestSchemaNormalization:
    """Test schema normalization (severity/category enums, etc.)."""

    @pytest.mark.asyncio
    async def test_findings_preserved_in_output(self, llm_generator_node, mock_llm_client, sample_state, valid_llm_response):
        """Test that 'findings' is preserved in output."""
        mock_llm_client.generate_completion.return_value = {
            "content": json.dumps(valid_llm_response),
            "usage": {"input_tokens": 100, "output_tokens": 200},
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        output = result.data["raw_llm_output"]
        assert "findings" in output

    @pytest.mark.asyncio
    async def test_hunk_id_preserved_in_finding(self, llm_generator_node, mock_llm_client, sample_state, valid_llm_response):
        """Test that 'hunk_id' is preserved in finding."""
        mock_llm_client.generate_completion.return_value = {
            "content": json.dumps(valid_llm_response),
            "usage": {"input_tokens": 100, "output_tokens": 200},
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        finding = result.data["raw_llm_output"]["findings"][0]
        assert finding.get("hunk_id") == "hunk_1_src_main_py"

    @pytest.mark.asyncio
    async def test_line_in_hunk_zero_handled_correctly(self, llm_generator_node, mock_llm_client, sample_state):
        """Test that line_in_hunk=0 is handled correctly (not treated as falsy)."""
        response = {
            "findings": [
                {
                    "title": "Test",
                    "message": "Test message",
                    "severity": "medium",
                    "category": "bug",
                    "file_path": "test.py",
                    "suggested_fix": "Fix it",
                    "confidence": 0.8,
                    "line_in_hunk": 0  # Should NOT be treated as falsy
                }
            ],
            "summary": "Test summary"
        }
        
        mock_llm_client.generate_completion.return_value = {
            "content": json.dumps(response),
            "usage": {"input_tokens": 100, "output_tokens": 200},
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        finding = result.data["raw_llm_output"]["findings"][0]
        assert finding.get("line_hint") == 0  # Should be 0, not None

    @pytest.mark.asyncio
    async def test_severity_normalization(self, llm_generator_node, mock_llm_client, sample_state):
        """Test severity normalization for non-standard values."""
        response = {
            "findings": [
                {
                    "title": "Test",
                    "message": "Test message",
                    "severity": "critical",  # Should map to "blocker"
                    "category": "bug",
                    "file_path": "test.py",
                    "suggested_fix": "Fix it",
                    "confidence": 0.8
                }
            ],
            "summary": "Test summary"
        }
        
        mock_llm_client.generate_completion.return_value = {
            "content": json.dumps(response),
            "usage": {"input_tokens": 100, "output_tokens": 200},
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        finding = result.data["raw_llm_output"]["findings"][0]
        assert finding["severity"] == "blocker"

    @pytest.mark.asyncio
    async def test_category_normalization(self, llm_generator_node, mock_llm_client, sample_state):
        """Test category normalization for non-standard values."""
        response = {
            "findings": [
                {
                    "title": "Test",
                    "message": "Test message",
                    "severity": "medium",
                    "category": "vulnerability",  # Should map to "security"
                    "file_path": "test.py",
                    "suggested_fix": "Fix it",
                    "confidence": 0.8
                }
            ],
            "summary": "Test summary"
        }
        
        mock_llm_client.generate_completion.return_value = {
            "content": json.dumps(response),
            "usage": {"input_tokens": 100, "output_tokens": 200},
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        finding = result.data["raw_llm_output"]["findings"][0]
        assert finding["category"] == "security"

    @pytest.mark.asyncio
    async def test_confidence_clamping(self, llm_generator_node, mock_llm_client, sample_state):
        """Test confidence is clamped to [0.0, 1.0]."""
        response = {
            "findings": [
                {
                    "title": "Test",
                    "message": "Test message",
                    "severity": "medium",
                    "category": "bug",
                    "file_path": "test.py",
                    "suggested_fix": "Fix it",
                    "confidence": 1.5  # Should be clamped to 1.0
                }
            ],
            "summary": "Test summary"
        }
        
        mock_llm_client.generate_completion.return_value = {
            "content": json.dumps(response),
            "usage": {"input_tokens": 100, "output_tokens": 200},
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        finding = result.data["raw_llm_output"]["findings"][0]
        assert finding["confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_evidence_snippet_range_type_validation(self, llm_generator_node, mock_llm_client, sample_state):
        """Test that non-list snippet_line_range is handled."""
        response = {
            "findings": [
                {
                    "title": "Test",
                    "message": "Test message",
                    "severity": "medium",
                    "category": "bug",
                    "file_path": "test.py",
                    "suggested_fix": "Fix it",
                    "confidence": 0.8,
                    "evidence": {
                        "context_item_id": "ctx_1",
                        "snippet_line_range": "invalid",  # Should be converted to []
                    }
                }
            ],
            "summary": "Test summary"
        }
        
        mock_llm_client.generate_completion.return_value = {
            "content": json.dumps(response),
            "usage": {"input_tokens": 100, "output_tokens": 200},
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        finding = result.data["raw_llm_output"]["findings"][0]
        assert finding["evidence"]["snippet_line_range"] == []


# ============================================================================
# TOKEN TRACKING TESTS
# ============================================================================

class TestTokenTracking:
    """Test token usage tracking."""

    @pytest.mark.asyncio
    async def test_token_usage_tracked(self, llm_generator_node, mock_llm_client, sample_state, valid_llm_response):
        """Test that token usage is tracked in response."""
        mock_llm_client.generate_completion.return_value = {
            "content": json.dumps(valid_llm_response),
            "usage": {"input_tokens": 1500, "output_tokens": 800},
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        assert "llm_token_usage" in result.data
        assert result.data["llm_token_usage"]["input_tokens"] == 1500
        assert result.data["llm_token_usage"]["output_tokens"] == 800
        assert result.data["llm_token_usage"]["total_tokens"] == 2300

    @pytest.mark.asyncio
    async def test_missing_usage_data_handled(self, llm_generator_node, mock_llm_client, sample_state, valid_llm_response):
        """Test that missing usage data is handled gracefully."""
        mock_llm_client.generate_completion.return_value = {
            "content": json.dumps(valid_llm_response),
            # Missing "usage" key
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        assert result.data["llm_token_usage"]["input_tokens"] == 0
        assert result.data["llm_token_usage"]["output_tokens"] == 0


# ============================================================================
# ERROR HANDLING TESTS
# ============================================================================

class TestErrorHandling:
    """Test error handling and graceful degradation."""

    @pytest.mark.asyncio
    async def test_llm_api_error_triggers_retry(self, llm_generator_node, mock_llm_client, sample_state, valid_llm_response):
        """Test that LLM API errors trigger retry logic."""
        # Fail twice, succeed third time
        mock_llm_client.generate_completion.side_effect = [
            Exception("API Error 1"),
            Exception("API Error 2"),
            {
                "content": json.dumps(valid_llm_response),
                "usage": {"input_tokens": 100, "output_tokens": 200},
                "model": "mock-model",
                "stop_reason": "end_turn"
            }
        ]
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        assert result.metrics.retry_count == 2

    @pytest.mark.asyncio
    async def test_partial_output_salvaged(self, llm_generator_node, mock_llm_client, sample_state):
        """Test that partial valid output is salvaged."""
        response = {
            "findings": [
                {
                    "title": "Valid Finding",
                    "message": "Valid message",
                    "severity": "high",
                    "category": "bug",
                    "file_path": "test.py",
                    "suggested_fix": "Fix it",
                    "confidence": 0.9
                },
                {
                    # Invalid finding - missing required fields
                    "title": "Invalid",
                }
            ],
            "summary": "Partial review"
        }
        
        mock_llm_client.generate_completion.return_value = {
            "content": json.dumps(response),
            "usage": {"input_tokens": 100, "output_tokens": 200},
            "model": "mock-model",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        # Should have salvaged the valid finding
        assert len(result.data["raw_llm_output"]["findings"]) == 1
        assert result.data["raw_llm_output"]["findings"][0]["title"] == "Valid Finding"

    @pytest.mark.asyncio
    async def test_missing_structured_prompt_error(self, llm_generator_node, mock_llm_client):
        """Test that missing structured_prompt produces helpful error."""
        state = {"context_pack": {}}  # Missing structured_prompt
        
        result = await llm_generator_node.execute(state)
        
        # Should use graceful degradation
        assert "raw_llm_output" in result.data
        assert "llm_generation_error" in result.data


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests with realistic data."""

    @pytest.mark.asyncio
    async def test_full_workflow_with_realistic_response(self, llm_generator_node, mock_llm_client, sample_state):
        """Test full workflow with a realistic multi-finding response."""
        realistic_response = {
            "findings": [
                {
                    "title": "SQL Injection Vulnerability",
                    "message": "User input is directly concatenated into SQL query without sanitization.",
                    "severity": "blocker",
                    "category": "security",
                    "file_path": "src/db/queries.py",
                    "hunk_id": "hunk_1_src_db_queries_py",
                    "suggested_fix": "Use parameterized queries: cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))",
                    "confidence": 0.95,
                    "evidence": {
                        "context_item_id": "ctx_db_query_builder",
                        "snippet_line_range": [15, 18],
                        "quote": "query = f\"SELECT * FROM {table} WHERE id = {user_id}\""
                    },
                    "related_symbols": ["execute_query", "build_query"]
                },
                {
                    "title": "Missing Error Handling",
                    "message": "API call lacks try/except block, may crash on network errors.",
                    "severity": "high",
                    "category": "bug",
                    "file_path": "src/services/api.py",
                    "hunk_id": "hunk_2_src_services_api_py",
                    "suggested_fix": "Wrap in try/except and handle ConnectionError gracefully.",
                    "confidence": 0.82,
                    "evidence": {
                        "context_item_id": "ctx_api_client",
                        "snippet_line_range": [42, 45]
                    },
                    "related_symbols": ["fetch_data"]
                },
                {
                    "title": "Unused Import",
                    "message": "The 'datetime' module is imported but never used.",
                    "severity": "nit",
                    "category": "style",
                    "file_path": "src/utils.py",
                    "suggested_fix": "Remove unused import: 'from datetime import datetime'",
                    "confidence": 0.99,
                    "evidence": {
                        "context_item_id": "ctx_utils_imports"
                    }
                }
            ],
            "summary": "Found 3 issues: 1 blocker (SQL injection), 1 high (error handling), 1 nit (unused import). The SQL injection should be fixed before merge.",
            "patterns": ["async_await", "type_hints"],
            "recommendations": ["Add comprehensive error handling", "Enable SQL query logging"]
        }
        
        mock_llm_client.generate_completion.return_value = {
            "content": json.dumps(realistic_response),
            "usage": {"input_tokens": 5000, "output_tokens": 1200},
            "model": "claude-3-5-sonnet",
            "stop_reason": "end_turn"
        }
        
        result = await llm_generator_node.execute(sample_state)
        
        assert result.success
        output = result.data["raw_llm_output"]
        
        # Verify all findings were processed
        assert len(output["findings"]) == 3
        
        # Verify first finding
        finding_1 = output["findings"][0]
        assert finding_1["title"] == "SQL Injection Vulnerability"
        assert finding_1["severity"] == "blocker"
        assert finding_1["hunk_id"] == "hunk_1_src_db_queries_py"
        assert finding_1["evidence"]["context_item_id"] == "ctx_db_query_builder"
        
        # Verify optional fields preserved
        assert output["patterns"] == ["async_await", "type_hints"]
        assert len(output["recommendations"]) == 2
        
        # Verify token tracking
        assert result.data["llm_token_usage"]["input_tokens"] == 5000
        assert result.data["llm_token_usage"]["output_tokens"] == 1200
