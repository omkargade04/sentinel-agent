"""
Comprehensive Testing Suite for Context Assembly System

Production-grade test suite covering unit, integration, and end-to-end testing
with proper mocking, fixtures, and performance benchmarks.
"""

import pytest
import asyncio
import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, List, Any, Optional

from src.models.schemas.pr_review.seed_set import SeedSetS0, SeedSymbol
from src.models.schemas.pr_review.pr_patch import PRFilePatch
from src.models.schemas.pr_review.context_pack import ContextPackLimits

from src.services.pr_review.context_assembly import (
    ContextAssemblyService,
    AssemblyConfig,
    EnhancedClaudeClient,
    ContextRanker,
    HardLimitsEnforcer,
    CircuitBreaker,
    ContextAssemblyWorkflow,
    ContextAssemblyError,
    CostLimitExceededError,
    CircuitBreakerOpenError
)


class TestFixtures:
    """Test fixtures and mock data for context assembly testing."""

    @staticmethod
    def create_mock_seed_set() -> SeedSetS0:
        """Create mock seed set for testing."""
        return SeedSetS0(
            seed_symbols=[
                SeedSymbol(
                    name="calculate_sum",
                    type="function",
                    file_path="src/utils.py",
                    line_number=15
                ),
                SeedSymbol(
                    name="DataProcessor",
                    type="class",
                    file_path="src/processor.py",
                    line_number=25
                ),
                SeedSymbol(
                    name="CONFIG_TIMEOUT",
                    type="variable",
                    file_path="src/config.py",
                    line_number=10
                )
            ],
            seed_files=[]
        )

    @staticmethod
    def create_mock_patches() -> List[PRFilePatch]:
        """Create mock PR patches for testing."""
        return [
            PRFilePatch(
                file_path="src/utils.py",
                additions=5,
                deletions=2,
                changes=7,
                patch="@@ -15,7 +15,10 @@\n def calculate_sum():\n+    # New logic\n     return a + b",
                status="modified"
            ),
            PRFilePatch(
                file_path="src/processor.py",
                additions=15,
                deletions=3,
                changes=18,
                patch="@@ -25,5 +25,20 @@\n class DataProcessor:\n+    def new_method(self):\n+        pass",
                status="modified"
            )
        ]

    @staticmethod
    def create_mock_kg_candidates() -> Dict[str, Any]:
        """Create mock KG candidates for testing."""
        return {
            "candidates": [
                {
                    "symbol_name": "calculate_sum",
                    "symbol_type": "function",
                    "file_path": "src/utils.py",
                    "start_line": 15,
                    "end_line": 25,
                    "code_snippet": "def calculate_sum(a: int, b: int) -> int:\n    return a + b",
                    "distance_from_seed": 0,
                    "relationship_type": "self",
                    "relationship_strength": 1.0
                },
                {
                    "symbol_name": "validate_input",
                    "symbol_type": "function",
                    "file_path": "src/validation.py",
                    "start_line": 5,
                    "end_line": 15,
                    "code_snippet": "def validate_input(value):\n    return value > 0",
                    "distance_from_seed": 1,
                    "relationship_type": "called_by",
                    "relationship_strength": 0.8
                },
                {
                    "symbol_name": "helper_function",
                    "symbol_type": "function",
                    "file_path": "src/helpers.py",
                    "start_line": 10,
                    "end_line": 20,
                    "code_snippet": "def helper_function():\n    pass",
                    "distance_from_seed": 2,
                    "relationship_type": "calls",
                    "relationship_strength": 0.3
                }
            ],
            "stats": {
                "total_candidates": 3,
                "kg_symbols_found": 2,
                "kg_symbols_missing": 1
            }
        }

    @staticmethod
    def create_mock_limits() -> ContextPackLimits:
        """Create mock context pack limits for testing."""
        return ContextPackLimits(
            max_context_items=10,
            max_total_characters=5000,
            max_lines_per_snippet=50,
            max_chars_per_item=500,
            max_hops=2,
            max_neighbors_per_seed=5
        )


class TestEnhancedClaudeClient:
    """Test suite for Enhanced Claude Client."""

    @pytest.fixture
    def mock_anthropic_client(self):
        """Mock Anthropic client for testing."""
        with patch('src.services.pr_review.context_assembly.enhanced_claude_client.AsyncAnthropic') as mock:
            mock_instance = AsyncMock()
            mock.return_value = mock_instance
            yield mock_instance

    @pytest.fixture
    def claude_client(self, mock_anthropic_client):
        """Create Enhanced Claude client for testing."""
        return EnhancedClaudeClient(
            api_key="test-key",
            model="claude-3-5-sonnet-20241022",
            max_cost_usd=0.10,
            timeout=30
        )

    @pytest.mark.asyncio
    async def test_cost_prediction(self, claude_client):
        """Test cost prediction functionality."""
        prompt = "Test prompt for cost prediction"
        system_prompt = "System context"

        prediction = await claude_client.predict_cost(prompt, system_prompt)

        assert prediction.estimated_input_tokens > 0
        assert prediction.estimated_output_tokens > 0
        assert prediction.estimated_cost_usd > 0
        assert 0.0 <= prediction.confidence_level <= 1.0

    @pytest.mark.asyncio
    async def test_budget_enforcement(self, claude_client):
        """Test budget enforcement prevents expensive requests."""
        # Simulate high current cost
        claude_client.cost_tracker.record_usage(50000, 25000)  # ~$0.525

        large_prompt = "x" * 10000  # Large prompt
        prediction = await claude_client.predict_cost(large_prompt)

        with pytest.raises(CostLimitExceededError) as exc_info:
            await claude_client.check_budget(prediction)

        assert "exceed budget" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_successful_completion(self, claude_client, mock_anthropic_client):
        """Test successful completion generation."""
        # Mock response
        mock_response = Mock()
        mock_response.content = [Mock(text="Test response")]
        mock_response.usage = Mock(input_tokens=100, output_tokens=50)
        mock_response.model = "claude-3-5-sonnet"
        mock_response.stop_reason = "end_turn"

        mock_anthropic_client.messages.create.return_value = mock_response

        result = await claude_client.generate_completion("Test prompt")

        assert result["content"] == "Test response"
        assert result["usage"]["input_tokens"] == 100
        assert result["usage"]["output_tokens"] == 50
        assert claude_client.cost_tracker.total_requests == 1

    @pytest.mark.asyncio
    async def test_health_check(self, claude_client, mock_anthropic_client):
        """Test client health check."""
        # Mock successful health check
        mock_response = Mock()
        mock_response.content = [Mock(text="OK")]
        mock_response.usage = Mock(input_tokens=5, output_tokens=2)
        mock_anthropic_client.messages.create.return_value = mock_response

        health = await claude_client.health_check()

        assert health["status"] == "healthy"
        assert health["latency_seconds"] > 0
        assert health["tokens_used"] == 7


class TestContextRanker:
    """Test suite for Context Ranker."""

    @pytest.fixture
    def mock_claude_client(self):
        """Mock Enhanced Claude client."""
        client = Mock(spec=EnhancedClaudeClient)
        client.generate_completion = AsyncMock()
        return client

    @pytest.fixture
    def context_ranker(self, mock_claude_client):
        """Create context ranker for testing."""
        return ContextRanker(
            claude_client=mock_claude_client,
            min_relevance_score=0.3,
            max_duplicate_similarity=0.85
        )

    @pytest.mark.asyncio
    async def test_relevance_scoring(self, context_ranker, mock_claude_client):
        """Test relevance scoring with LLM."""
        # Mock LLM response
        mock_claude_client.generate_completion.return_value = {
            "content": "0.9, 0.6, 0.2",
            "usage": {"input_tokens": 100, "output_tokens": 20}
        }

        candidates = TestFixtures.create_mock_kg_candidates()["candidates"]
        seed_set = TestFixtures.create_mock_seed_set()
        patches = TestFixtures.create_mock_patches()

        scored_candidates = await context_ranker.score_relevance(
            candidates=candidates,
            seed_set=seed_set,
            patches=patches
        )

        assert len(scored_candidates) == 3
        assert all("relevance_score" in candidate for candidate in scored_candidates)
        assert scored_candidates[0]["relevance_score"] > 0.5  # High relevance

    @pytest.mark.asyncio
    async def test_duplicate_removal(self, context_ranker):
        """Test duplicate removal functionality."""
        # Create candidates with duplicates
        candidates = [
            {
                "symbol_name": "test_func",
                "code_snippet": "def test_func(): return 1",
                "relevance_score": 0.9
            },
            {
                "symbol_name": "test_func_copy",
                "code_snippet": "def test_func(): return 1",  # Exact duplicate
                "relevance_score": 0.7
            },
            {
                "symbol_name": "different_func",
                "code_snippet": "def different_func(): return 2",
                "relevance_score": 0.8
            }
        ]

        deduplicated = await context_ranker.remove_duplicates(
            candidates, similarity_threshold=0.9
        )

        # Should remove the duplicate, keeping higher scored one
        assert len(deduplicated) == 2
        assert any(c["symbol_name"] == "test_func" for c in deduplicated)
        assert any(c["symbol_name"] == "different_func" for c in deduplicated)

    def test_rule_based_scoring_fallback(self, context_ranker):
        """Test fallback to rule-based scoring."""
        candidates = TestFixtures.create_mock_kg_candidates()["candidates"]
        seed_set = TestFixtures.create_mock_seed_set()
        patches = TestFixtures.create_mock_patches()

        # Apply rule-based scoring directly
        for candidate in candidates:
            enhanced = context_ranker._extract_features(candidate, seed_set, patches)
            scored = context_ranker._apply_rule_based_scoring(enhanced)
            assert "rule_based_score" in scored
            assert 0.0 <= scored["rule_based_score"] <= 1.0


class TestHardLimitsEnforcer:
    """Test suite for Hard Limits Enforcer."""

    @pytest.fixture
    def limits_enforcer(self):
        """Create hard limits enforcer for testing."""
        return HardLimitsEnforcer()

    def test_item_limit_enforcement(self, limits_enforcer):
        """Test enforcement of item count limits."""
        candidates = [
            {"symbol_name": f"func_{i}", "code_snippet": f"def func_{i}(): pass"}
            for i in range(20)  # More than limit
        ]

        limits = ContextPackLimits(max_context_items=5, max_total_characters=10000)

        bounded_candidates = limits_enforcer.apply_limits(candidates, limits)

        assert len(bounded_candidates) <= limits.max_context_items

    def test_character_limit_enforcement(self, limits_enforcer):
        """Test enforcement of character limits."""
        # Create candidates that exceed character limit
        candidates = [
            {
                "symbol_name": "large_func",
                "code_snippet": "x" * 1000  # Large snippet
            }
        ]

        limits = ContextPackLimits(
            max_context_items=10,
            max_total_characters=500,  # Smaller than snippet
            max_chars_per_item=300
        )

        bounded_candidates = limits_enforcer.apply_limits(candidates, limits)

        total_chars = sum(len(c.get("code_snippet", "")) for c in bounded_candidates)
        assert total_chars <= limits.max_total_characters

        # Check individual item was truncated
        if bounded_candidates:
            assert bounded_candidates[0].get("truncated", False)

    def test_line_limit_enforcement(self, limits_enforcer):
        """Test enforcement of line count limits."""
        multi_line_snippet = "\n".join([f"line {i}" for i in range(100)])  # 100 lines

        result = limits_enforcer._apply_line_limit(multi_line_snippet, max_lines=10)

        result_lines = result.split('\n')
        assert len(result_lines) <= 10
        assert "truncated" in result

    def test_resource_allocation_tracking(self, limits_enforcer):
        """Test resource allocation tracking."""
        candidates = TestFixtures.create_mock_kg_candidates()["candidates"]
        limits = TestFixtures.create_mock_limits()

        estimation = limits_enforcer.estimate_resource_usage(candidates, limits)

        assert estimation["candidates_total"] == len(candidates)
        assert estimation["estimated_items_selected"] <= limits.max_context_items
        assert estimation["raw_characters"] > 0
        assert "fits_within_limits" in estimation


class TestCircuitBreaker:
    """Test suite for Circuit Breaker."""

    @pytest.fixture
    def circuit_breaker(self):
        """Create circuit breaker for testing."""
        return CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=10,
            name="test_breaker"
        )

    @pytest.mark.asyncio
    async def test_closed_state_allows_requests(self, circuit_breaker):
        """Test circuit breaker allows requests in closed state."""
        async def successful_operation():
            return "success"

        result = await circuit_breaker.call(successful_operation)
        assert result == "success"
        assert circuit_breaker.state.value == "closed"

    @pytest.mark.asyncio
    async def test_failure_threshold_opens_breaker(self, circuit_breaker):
        """Test circuit breaker opens after failure threshold."""
        async def failing_operation():
            raise Exception("Test failure")

        # Execute failures up to threshold
        for i in range(3):
            try:
                await circuit_breaker.call(failing_operation)
            except Exception:
                pass

        # Circuit should now be open
        assert circuit_breaker.state.value == "open"

        # Further calls should be blocked
        with pytest.raises(CircuitBreakerOpenError):
            await circuit_breaker.call(failing_operation)

    @pytest.mark.asyncio
    async def test_recovery_after_timeout(self, circuit_breaker):
        """Test circuit breaker recovery after timeout."""
        # Force circuit breaker open
        circuit_breaker.force_open()
        assert circuit_breaker.state.value == "open"

        # Simulate timeout passage
        circuit_breaker.metrics.last_failure_time = datetime.utcnow() - timedelta(seconds=20)

        async def successful_operation():
            return "success"

        # Should transition to half-open and then closed
        result = await circuit_breaker.call(successful_operation)
        assert result == "success"

    def test_health_check(self, circuit_breaker):
        """Test circuit breaker health check."""
        health = circuit_breaker.health_check()

        assert health["status"] in ["healthy", "degraded", "unhealthy"]
        assert "state" in health
        assert "consecutive_failures" in health


class TestContextAssemblyWorkflow:
    """Test suite for LangGraph Context Assembly Workflow."""

    @pytest.fixture
    def mock_claude_client(self):
        """Mock Enhanced Claude client for workflow testing."""
        client = Mock(spec=EnhancedClaudeClient)
        client.generate_completion = AsyncMock()
        client.health_check = AsyncMock(return_value={"status": "healthy"})
        return client

    @pytest.fixture
    def mock_circuit_breaker(self):
        """Mock circuit breaker for testing."""
        breaker = Mock(spec=CircuitBreaker)
        breaker.can_execute.return_value = True
        breaker.__aenter__ = AsyncMock(return_value=breaker)
        breaker.__aexit__ = AsyncMock(return_value=False)
        return breaker

    @pytest.fixture
    def workflow(self, mock_claude_client, mock_circuit_breaker):
        """Create context assembly workflow for testing."""
        return ContextAssemblyWorkflow(
            claude_client=mock_claude_client,
            circuit_breaker=mock_circuit_breaker,
            timeout_seconds=60
        )

    @pytest.mark.asyncio
    async def test_successful_workflow_execution(self, workflow, mock_claude_client):
        """Test successful end-to-end workflow execution."""
        # Mock Claude responses for relevance scoring
        mock_claude_client.generate_completion.return_value = {
            "content": "0.9, 0.7, 0.5",
            "usage": {"input_tokens": 150, "output_tokens": 30}
        }

        seed_set = TestFixtures.create_mock_seed_set()
        kg_candidates = TestFixtures.create_mock_kg_candidates()
        patches = TestFixtures.create_mock_patches()
        limits = TestFixtures.create_mock_limits()

        result = await workflow.execute(
            seed_set=seed_set,
            kg_candidates=kg_candidates,
            patches=patches,
            limits=limits
        )

        # Verify workflow completion
        assert "final_context_items" in result
        assert "workflow_metadata" in result
        assert result["workflow_metadata"]["workflow_id"]
        assert result["workflow_metadata"]["execution_time_seconds"] > 0

    @pytest.mark.asyncio
    async def test_workflow_timeout_handling(self, workflow):
        """Test workflow timeout handling."""
        # Create workflow with very short timeout
        workflow.timeout_seconds = 0.001  # 1ms - will timeout

        seed_set = TestFixtures.create_mock_seed_set()
        kg_candidates = TestFixtures.create_mock_kg_candidates()
        patches = TestFixtures.create_mock_patches()
        limits = TestFixtures.create_mock_limits()

        from src.services.pr_review.context_assembly.exceptions import WorkflowTimeoutError

        with pytest.raises(WorkflowTimeoutError) as exc_info:
            await workflow.execute(
                seed_set=seed_set,
                kg_candidates=kg_candidates,
                patches=patches,
                limits=limits
            )

        assert "timed out" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_node_failure_recovery(self, workflow, mock_claude_client):
        """Test workflow recovery from node failures."""
        # Make Claude client fail to test fallback
        mock_claude_client.generate_completion.side_effect = Exception("Claude API error")

        seed_set = TestFixtures.create_mock_seed_set()
        kg_candidates = TestFixtures.create_mock_kg_candidates()
        patches = TestFixtures.create_mock_patches()
        limits = TestFixtures.create_mock_limits()

        # Should still complete with fallbacks
        result = await workflow.execute(
            seed_set=seed_set,
            kg_candidates=kg_candidates,
            patches=patches,
            limits=limits
        )

        assert "final_context_items" in result
        assert len(result.get("warnings", [])) > 0  # Should have warnings about fallbacks


class TestContextAssemblyService:
    """Integration tests for the main Context Assembly Service."""

    @pytest.fixture
    def mock_claude_client(self):
        """Mock Enhanced Claude client."""
        client = Mock(spec=EnhancedClaudeClient)
        client.generate_completion = AsyncMock()
        client.health_check = AsyncMock(return_value={"status": "healthy"})
        client.get_performance_metrics.return_value = {
            "total_requests": 5,
            "total_errors": 0,
            "error_rate_percent": 0.0
        }
        return client

    @pytest.fixture
    def assembly_service(self, mock_claude_client):
        """Create context assembly service for testing."""
        config = AssemblyConfig(
            max_cost_usd=0.10,
            max_requests_per_minute=10,
            failure_threshold=3,
            recovery_timeout=30
        )
        return ContextAssemblyService(mock_claude_client, config)

    @pytest.mark.asyncio
    async def test_end_to_end_context_assembly(self, assembly_service, mock_claude_client):
        """Test complete end-to-end context assembly process."""
        # Mock successful Claude responses
        mock_claude_client.generate_completion.return_value = {
            "content": "0.9, 0.7, 0.5",
            "usage": {"input_tokens": 100, "output_tokens": 50}
        }

        # Test data
        repo_id = uuid.uuid4()
        seed_set = TestFixtures.create_mock_seed_set()
        patches = TestFixtures.create_mock_patches()
        kg_candidates = TestFixtures.create_mock_kg_candidates()
        limits = TestFixtures.create_mock_limits()

        # Execute assembly
        context_pack = await assembly_service.assemble_context(
            repo_id=repo_id,
            github_repo_name="test/repo",
            pr_number=123,
            head_sha="a" * 40,
            base_sha="b" * 40,
            seed_set=seed_set,
            patches=patches,
            kg_candidates=kg_candidates,
            limits=limits
        )

        # Verify result
        assert context_pack.repo_id == repo_id
        assert context_pack.pr_number == 123
        assert len(context_pack.context_items) > 0
        assert context_pack.stats.total_items > 0
        assert context_pack.stats.total_characters > 0

    @pytest.mark.asyncio
    async def test_cost_budget_enforcement(self, assembly_service):
        """Test cost budget enforcement in service."""
        # Simulate high existing cost
        assembly_service.cost_tracker.record_usage(30000, 15000)  # High cost

        repo_id = uuid.uuid4()
        seed_set = TestFixtures.create_mock_seed_set()
        patches = TestFixtures.create_mock_patches()
        kg_candidates = TestFixtures.create_mock_kg_candidates()
        limits = TestFixtures.create_mock_limits()

        with pytest.raises(CostLimitExceededError):
            await assembly_service.assemble_context(
                repo_id=repo_id,
                github_repo_name="test/repo",
                pr_number=123,
                head_sha="a" * 40,
                base_sha="b" * 40,
                seed_set=seed_set,
                patches=patches,
                kg_candidates=kg_candidates,
                limits=limits
            )

    def test_service_metrics_collection(self, assembly_service):
        """Test service metrics collection."""
        metrics = assembly_service.get_metrics()

        assert "cost_tracker" in metrics
        assert "circuit_breaker" in metrics
        assert "rate_limiting" in metrics
        assert "config" in metrics


class TestPerformanceBenchmarks:
    """Performance benchmarks for context assembly system."""

    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_assembly_performance_small_context(self, benchmark):
        """Benchmark performance with small context."""
        # Mock setup for benchmark
        mock_client = Mock(spec=EnhancedClaudeClient)
        mock_client.generate_completion = AsyncMock(return_value={
            "content": "0.9, 0.8, 0.7",
            "usage": {"input_tokens": 100, "output_tokens": 30}
        })

        service = ContextAssemblyService(mock_client, AssemblyConfig())

        # Small test data
        repo_id = uuid.uuid4()
        seed_set = SeedSetS0(seed_symbols=[
            SeedSymbol(name="test_func", type="function", file_path="test.py", line_number=1)
        ], seed_files=[])
        patches = [PRFilePatch(
            file_path="test.py", additions=1, deletions=0, changes=1,
            patch="+ test", status="modified"
        )]
        kg_candidates = {"candidates": [
            {"symbol_name": "test_func", "code_snippet": "def test(): pass"}
        ]}
        limits = ContextPackLimits(max_context_items=5, max_total_characters=1000)

        # Benchmark the assembly
        result = benchmark(
            lambda: asyncio.run(service.assemble_context(
                repo_id, "test/repo", 1, "a" * 40, "b" * 40,
                seed_set, patches, kg_candidates, limits
            ))
        )

        # Performance assertions
        assert result is not None

    @pytest.mark.asyncio
    async def test_memory_usage_large_context(self):
        """Test memory usage with large context data."""
        import psutil
        import os

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        # Create large test data
        large_candidates = {
            "candidates": [
                {
                    "symbol_name": f"func_{i}",
                    "code_snippet": "x" * 1000,  # 1KB per snippet
                    "file_path": f"file_{i}.py"
                }
                for i in range(100)  # 100KB total
            ]
        }

        # Mock client
        mock_client = Mock(spec=EnhancedClaudeClient)
        mock_client.generate_completion = AsyncMock(return_value={
            "content": ", ".join(["0.5"] * 100),  # Scores for all candidates
            "usage": {"input_tokens": 1000, "output_tokens": 100}
        })

        service = ContextAssemblyService(mock_client, AssemblyConfig())

        # Process large context
        repo_id = uuid.uuid4()
        seed_set = TestFixtures.create_mock_seed_set()
        patches = TestFixtures.create_mock_patches()
        limits = ContextPackLimits(max_context_items=50, max_total_characters=50000)

        await service.assemble_context(
            repo_id, "test/repo", 1, "a" * 40, "b" * 40,
            seed_set, patches, large_candidates, limits
        )

        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory

        # Memory increase should be reasonable (< 50MB for this test)
        assert memory_increase < 50 * 1024 * 1024, f"Memory increased by {memory_increase / 1024 / 1024:.1f}MB"


# Test configuration and runners
if __name__ == "__main__":
    pytest.main([
        __file__,
        "-v",
        "--tb=short",
        "-x",  # Stop on first failure
        "--cov=src.services.pr_review.context_assembly",
        "--cov-report=html",
        "--benchmark-only",  # Run only benchmark tests
        "--benchmark-sort=mean"
    ])