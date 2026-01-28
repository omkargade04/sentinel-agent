"""
Unit tests for KGCandidateRetriever.

Tests the fix for the candidates list serialization bug where
import_neighbors and other structured data was not being included
in a flat 'candidates' list for downstream consumers.
"""

import pytest
from src.services.kg.kg_candidate_retriever import (
    KGCandidateResult,
    KGCandidateStats,
)


class TestKGCandidateResultToDict:
    """Tests for KGCandidateResult.to_dict() serialization."""

    def test_to_dict_includes_candidates_key(self):
        """
        Regression test: to_dict() must include a 'candidates' key.

        Bug: ContextAssemblyService looked for kg_candidates.get('candidates', [])
        but KGCandidateResult.to_dict() only returned structured keys like
        'import_neighbors', 'neighbors', etc. This caused all KG context to be
        silently dropped.
        """
        result = KGCandidateResult()
        output = result.to_dict()

        assert "candidates" in output, (
            "to_dict() must include 'candidates' key for downstream consumers"
        )

    def test_to_dict_flattens_import_neighbors_into_candidates(self):
        """
        Test that import_neighbors are included in the flat candidates list.

        This reproduces the exact scenario from the error log where:
        - 5 import neighbors were retrieved from KG
        - stats.total_candidates showed 5
        - But context assembly received 0 candidates
        """
        # Simulate KG retrieval result with import neighbors (like the log showed)
        result = KGCandidateResult(
            import_neighbors=[
                {
                    "relationship": "imports",
                    "source_file": "server/routes/post.routes.ts",
                    "node": {"node_id": "node_1", "file_path": "server/controllers/post.controller.ts"},
                },
                {
                    "relationship": "imports",
                    "source_file": "server/routes/post.routes.ts",
                    "node": {"node_id": "node_2", "file_path": "server/middleware/auth.ts"},
                },
                {
                    "relationship": "imported_by",
                    "source_file": "server/routes/post.routes.ts",
                    "node": {"node_id": "node_3", "file_path": "server/index.ts"},
                },
                {
                    "relationship": "imports",
                    "source_file": "server/controllers/post.controller.ts",
                    "node": {"node_id": "node_4", "file_path": "server/models/post.model.ts"},
                },
                {
                    "relationship": "imports",
                    "source_file": "server/controllers/post.controller.ts",
                    "node": {"node_id": "node_5", "file_path": "server/utils/prisma.ts"},
                },
            ],
            stats=KGCandidateStats(
                import_neighbors_retrieved=5,
                total_candidates=5,
            ),
        )

        output = result.to_dict()

        # Verify candidates list is populated
        assert len(output["candidates"]) == 5, (
            f"Expected 5 candidates, got {len(output['candidates'])}. "
            "import_neighbors should be flattened into candidates list."
        )

        # Verify stats matches candidates count
        assert output["stats"]["total_candidates"] == len(output["candidates"]), (
            "stats.total_candidates should match len(candidates)"
        )

        # Verify each candidate has the type annotation
        for candidate in output["candidates"]:
            assert candidate["candidate_type"] == "import_neighbor"

    def test_to_dict_flattens_all_candidate_types(self):
        """Test that all candidate types are flattened into candidates list."""
        result = KGCandidateResult(
            symbol_matches=[
                {"seed_symbol": {"name": "foo"}, "kg_symbol": {"node_id": "sym_1"}},
            ],
            neighbors=[
                {"relationship": "caller", "node": {"node_id": "neighbor_1"}},
                {"relationship": "callee", "node": {"node_id": "neighbor_2"}},
            ],
            import_neighbors=[
                {"relationship": "imports", "node": {"node_id": "import_1"}},
            ],
            docs=[
                {"path_prefix": "README", "node": {"node_id": "doc_1"}},
            ],
            stats=KGCandidateStats(
                kg_symbols_found=1,
                callers_retrieved=1,
                callees_retrieved=1,
                import_neighbors_retrieved=1,
                docs_retrieved=1,
                total_candidates=5,
            ),
        )

        output = result.to_dict()

        # Verify total count
        assert len(output["candidates"]) == 5

        # Verify candidate types are preserved
        candidate_types = [c["candidate_type"] for c in output["candidates"]]
        assert candidate_types.count("symbol_match") == 1
        assert candidate_types.count("neighbor") == 2
        assert candidate_types.count("import_neighbor") == 1
        assert candidate_types.count("doc") == 1

    def test_to_dict_preserves_structured_data_for_debugging(self):
        """Test that structured keys are still available for debugging."""
        result = KGCandidateResult(
            import_neighbors=[
                {"relationship": "imports", "node": {"node_id": "node_1"}},
            ],
        )

        output = result.to_dict()

        # Candidates list should exist
        assert "candidates" in output
        assert len(output["candidates"]) == 1

        # Structured data should also exist
        assert "import_neighbors" in output
        assert len(output["import_neighbors"]) == 1
        assert "symbol_matches" in output
        assert "neighbors" in output
        assert "docs" in output

    def test_to_dict_empty_result(self):
        """Test that empty result returns empty candidates list."""
        result = KGCandidateResult()
        output = result.to_dict()

        assert output["candidates"] == []
        assert output["stats"]["total_candidates"] == 0

    def test_context_assembly_service_can_read_candidates(self):
        """
        Integration-style test: verify the exact code path that was failing.

        ContextAssemblyService does: kg_candidates.get('candidates', [])
        This test ensures that call now returns the actual candidates.
        """
        result = KGCandidateResult(
            import_neighbors=[
                {"relationship": "imports", "node": {"node_id": "node_1"}},
                {"relationship": "imports", "node": {"node_id": "node_2"}},
            ],
            stats=KGCandidateStats(
                import_neighbors_retrieved=2,
                total_candidates=2,
            ),
        )

        # Simulate what the activity does
        kg_candidates = result.to_dict()

        # This is the EXACT line from ContextAssemblyService that was failing
        candidates_list = kg_candidates.get('candidates', [])

        # Before fix: candidates_list would be []
        # After fix: candidates_list should have 2 items
        assert len(candidates_list) == 2, (
            f"ContextAssemblyService received {len(candidates_list)} candidates, expected 2. "
            "This was the root cause of context being dropped."
        )


class TestKGCandidateResultDataclassDefaults:
    """Tests for KGCandidateResult dataclass defaults."""

    def test_default_values(self):
        """Test that KGCandidateResult has sensible defaults."""
        result = KGCandidateResult()

        assert result.kg_commit_sha is None
        assert result.symbol_matches == []
        assert result.neighbors == []
        assert result.import_neighbors == []
        assert result.docs == []
        assert result.warnings == []
        assert isinstance(result.stats, KGCandidateStats)

    def test_stats_default_values(self):
        """Test that KGCandidateStats has zero defaults."""
        stats = KGCandidateStats()

        assert stats.seed_symbols_processed == 0
        assert stats.seed_files_processed == 0
        assert stats.kg_symbols_found == 0
        assert stats.kg_symbols_missing == 0
        assert stats.callers_retrieved == 0
        assert stats.callees_retrieved == 0
        assert stats.contains_retrieved == 0
        assert stats.import_neighbors_retrieved == 0
        assert stats.docs_retrieved == 0
        assert stats.total_candidates == 0
        assert stats.retrieval_duration_ms == 0
