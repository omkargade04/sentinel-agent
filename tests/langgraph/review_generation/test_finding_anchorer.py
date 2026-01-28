"""
Unit tests for FindingAnchorerNode - Simplified Content Matching Approach.

Tests the simplified anchoring that:
1. Extracts code patterns from backticks in message/suggested_fix
2. Searches for patterns in hunk lines
3. Falls back to first added line
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from collections import defaultdict

from src.langgraph.review_generation.finding_anchorer import FindingAnchorerNode
from src.langgraph.review_generation.schema import (
    DiffMappings,
    FileDiffMapping,
    HunkMapping,
)


class TestSimplifiedAnchoring:
    """Tests for the simplified content-matching approach."""

    @pytest.fixture
    def anchorer(self):
        """Create a FindingAnchorerNode instance."""
        return FindingAnchorerNode()

    @pytest.fixture
    def sample_hunk(self):
        """Create a sample hunk matching the PR review scenario."""
        return HunkMapping(
            hunk_id="hunk_test123",
            file_path="server/controllers/post.controller.ts",
            old_start=100,
            old_count=5,
            new_start=100,
            new_count=30,
            lines=[
                " };",                                                      # 0
                "",                                                         # 1
                " const searchPosts = async (req: ReqMid, res: any) => {", # 2
                "+  const query = req.query.q as string;",                  # 3
                "",                                                         # 4
                "+  try {",                                                 # 5
                "+    const posts = await prisma.post.findMany({",          # 6
                "+      where: {",                                          # 7
                "+        OR: [",                                           # 8
                "+          { title: { contains: query } },",               # 9
                "+        ],",                                              # 10
                "+      },",                                                # 11
                "+      include: {",                                        # 12
                "+        author: {",                                       # 13
                "+          select: {",                                     # 14
                "+            name: true",                                  # 15
                "+            email: true,",                                # 16
                "+          },",                                            # 17
                "+        },",                                              # 18
                "+      },",                                                # 19
                "+    });",                                                 # 20
                "+    console.log(posts);",                                 # 21
                "+    res.status(200).json({ status: true, posts });",      # 22
                "+  } catch (error) {",                                     # 23
                "+    console.log(error);",                                 # 24
                "+    res.status(500).json({ status: false, error });",     # 25
                "+  } finally {",                                           # 26
                "+    prisma.disconnect;",                                  # 27
                "+  }",                                                     # 28
                " };",                                                      # 29
            ],
            line_count=30,
            added_line_indexes=[3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28],
            removed_line_indexes=[]
        )

    @pytest.fixture
    def sample_diff_mappings(self, sample_hunk):
        """Create sample diff mappings."""
        file_mapping = FileDiffMapping(
            file_path="server/controllers/post.controller.ts",
            hunks=[sample_hunk],
            hunk_ids=["hunk_test123"],
            total_additions=25,
            total_deletions=0
        )

        return DiffMappings(
            file_mappings={"server/controllers/post.controller.ts": file_mapping},
            all_file_paths=["server/controllers/post.controller.ts"],
            all_hunk_ids=["hunk_test123"],
            allowed_anchors=[("server/controllers/post.controller.ts", "hunk_test123")],
            line_to_hunk_lookup={},
            total_files=1,
            total_hunks=1,
            total_changed_lines=25
        )

    def test_extract_backtick_code_inline(self, anchorer):
        """Test extraction of inline backtick code."""
        text = "The code uses `console.log` to output the `posts` array."
        patterns = anchorer._extract_backtick_code(text)

        assert "console.log" in patterns
        assert "posts" in patterns

    def test_extract_backtick_code_block(self, anchorer):
        """Test extraction of code block."""
        text = """Add a comma:
```typescript
select: {
  name: true,
  email: true,
}
```"""
        patterns = anchorer._extract_backtick_code(text)

        assert any("select" in p for p in patterns)
        assert any("name" in p for p in patterns)

    def test_search_pattern_finds_exact_match(self, anchorer, sample_hunk):
        """Test that pattern search finds exact match."""
        idx = anchorer._search_pattern_in_hunk("prisma.disconnect", sample_hunk)
        assert idx == 27, f"Expected line 27, got {idx}"

    def test_search_pattern_prefers_added_lines(self, anchorer, sample_hunk):
        """Test that pattern search prefers added lines."""
        # "const query" appears in added line 3
        idx = anchorer._search_pattern_in_hunk("const query", sample_hunk)
        assert idx == 3, f"Expected line 3, got {idx}"

    def test_search_identifier_with_word_boundary(self, anchorer, sample_hunk):
        """Test that identifier search uses word boundaries."""
        # "email" should match line 16, not partial matches
        idx = anchorer._search_identifier_in_hunk("email", sample_hunk)
        assert idx == 16, f"Expected line 16, got {idx}"

    def test_find_line_by_content_match_backticks(self, anchorer, sample_hunk):
        """Test content matching with backtick patterns."""
        finding = {
            "message": "Remove `console.log(posts)` from the code.",
            "suggested_fix": "Delete the console.log statement.",
            "title": "Console log in production"
        }

        idx = anchorer._find_line_by_content_match(finding, sample_hunk)
        assert idx == 21, f"Expected line 21 (console.log), got {idx}"

    def test_find_line_by_content_match_prisma_disconnect(self, anchorer, sample_hunk):
        """Test finding prisma.disconnect line."""
        finding = {
            "message": "The `prisma.disconnect` property is accessed without calling it.",
            "suggested_fix": "Use `await prisma.$disconnect();` instead.",
            "title": "Incorrect Prisma disconnect"
        }

        idx = anchorer._find_line_by_content_match(finding, sample_hunk)
        assert idx == 27, f"Expected line 27 (prisma.disconnect), got {idx}"

    def test_find_line_by_content_match_query_validation(self, anchorer, sample_hunk):
        """Test finding query validation line."""
        finding = {
            "message": "The `query` variable from `req.query.q` is not validated.",
            "suggested_fix": "Add validation before using query.",
            "title": "Missing validation"
        }

        idx = anchorer._find_line_by_content_match(finding, sample_hunk)
        assert idx == 3, f"Expected line 3 (req.query.q), got {idx}"

    @pytest.mark.asyncio
    async def test_multiple_findings_get_different_lines(
        self, anchorer, sample_diff_mappings
    ):
        """
        Test that multiple findings anchor to different, correct lines.

        This is the main regression test.
        """
        findings = [
            {
                "title": "Syntax error in select",
                "message": "Missing comma between `name` and `email` in the select block.",
                "suggested_fix": "Add comma: `name: true,`",
                "file_path": "server/controllers/post.controller.ts",
                "hunk_id": "hunk_test123",
                "severity": "blocker",
                "category": "bug",
                "confidence": 1.0,
            },
            {
                "title": "Incorrect disconnect",
                "message": "The `prisma.disconnect` is not called as a function.",
                "suggested_fix": "Use `await prisma.$disconnect();`",
                "file_path": "server/controllers/post.controller.ts",
                "hunk_id": "hunk_test123",
                "severity": "high",
                "category": "bug",
                "confidence": 0.95,
            },
            {
                "title": "Query not validated",
                "message": "The `query` variable from `req.query.q` is used without validation.",
                "suggested_fix": "Check if query exists before using it.",
                "file_path": "server/controllers/post.controller.ts",
                "hunk_id": "hunk_test123",
                "severity": "medium",
                "category": "bug",
                "confidence": 0.9,
            },
            {
                "title": "Console log in production",
                "message": "Remove `console.log(posts)` from production code.",
                "suggested_fix": "Delete the console.log statement.",
                "file_path": "server/controllers/post.controller.ts",
                "hunk_id": "hunk_test123",
                "severity": "nit",
                "category": "observability",
                "confidence": 0.8,
            },
        ]

        state = {
            "raw_llm_output": {"findings": findings},
            "diff_mappings": sample_diff_mappings.model_dump(),
        }

        result = await anchorer._execute_node_logic(state)

        anchored = result["anchored_findings"]
        assert len(anchored) == 4, f"Expected 4 anchored findings, got {len(anchored)}"

        lines = [f["line_in_hunk"] for f in anchored]

        # KEY ASSERTION: lines should NOT all be the same or sequential
        unique_lines = set(lines)
        assert len(unique_lines) >= 3, (
            f"REGRESSION: Findings not properly distributed! "
            f"lines={lines}. Expected at least 3 unique lines."
        )

        # Check that content_match was used (not fallback)
        methods = result["anchoring_stats"]["anchoring_methods"]
        assert methods.get("content_match", 0) >= 3, (
            f"Expected at least 3 content_match anchors, got {methods}"
        )

        print(f"Lines: {lines}")
        print(f"Methods: {methods}")

    @pytest.mark.asyncio
    async def test_fallback_when_no_match(self, anchorer, sample_diff_mappings):
        """Test that fallback is used when no content match found."""
        finding = {
            "title": "Generic issue",
            "message": "This is a generic issue with no specific code reference.",
            "suggested_fix": "Fix it somehow.",
            "file_path": "server/controllers/post.controller.ts",
            "hunk_id": "hunk_test123",
            "severity": "low",
            "category": "style",
            "confidence": 0.5,
        }

        state = {
            "raw_llm_output": {"findings": [finding]},
            "diff_mappings": sample_diff_mappings.model_dump(),
        }

        result = await anchorer._execute_node_logic(state)

        anchored = result["anchored_findings"]
        assert len(anchored) == 1

        # Should use fallback
        methods = result["anchoring_stats"]["anchoring_methods"]
        assert methods.get("fallback", 0) == 1


class TestBacktickExtraction:
    """Tests for backtick code extraction."""

    @pytest.fixture
    def anchorer(self):
        return FindingAnchorerNode()

    def test_extract_multiple_inline_codes(self, anchorer):
        """Test extracting multiple inline codes."""
        text = "Check `foo`, `bar`, and `baz` values."
        patterns = anchorer._extract_backtick_code(text)

        assert len(patterns) == 3
        assert "foo" in patterns
        assert "bar" in patterns
        assert "baz" in patterns

    def test_extract_code_block_lines(self, anchorer):
        """Test extracting lines from code block."""
        text = """Example:
```javascript
const x = 1;
const y = 2;
return x + y;
```"""
        patterns = anchorer._extract_backtick_code(text)

        # Should get first 3 lines from block
        assert any("const x" in p for p in patterns)

    def test_filter_short_patterns(self, anchorer):
        """Test that very short patterns are filtered."""
        text = "Use `a` or `b` or `something_longer`."
        patterns = anchorer._extract_backtick_code(text)

        # 'a' and 'b' should be filtered (too short)
        assert "a" not in patterns
        assert "b" not in patterns
        assert "something_longer" in patterns

    def test_sort_by_length(self, anchorer):
        """Test that patterns are sorted by length (longer first)."""
        text = "Use `abc` or `abcdefghij` for this."
        patterns = anchorer._extract_backtick_code(text)

        # Longer pattern should come first
        assert patterns[0] == "abcdefghij"


class TestIdentifierExtraction:
    """Tests for identifier extraction."""

    @pytest.fixture
    def anchorer(self):
        return FindingAnchorerNode()

    def test_extract_camelcase(self, anchorer):
        """Test extraction of camelCase identifiers."""
        text = "The searchPosts function should validate userData."
        identifiers = anchorer._extract_key_identifiers(text)

        assert "searchPosts" in identifiers
        assert "userData" in identifiers

    def test_extract_snake_case(self, anchorer):
        """Test extraction of snake_case identifiers."""
        text = "Update the user_data and post_count variables."
        identifiers = anchorer._extract_key_identifiers(text)

        assert "user_data" in identifiers
        assert "post_count" in identifiers

    def test_filter_keywords(self, anchorer):
        """Test that common keywords are filtered."""
        text = "The function should return true if the value is valid."
        identifiers = anchorer._extract_key_identifiers(text)

        # Common words should be filtered
        assert "function" not in identifiers
        assert "return" not in identifiers
        assert "true" not in identifiers
        assert "valid" not in identifiers  # filtered as review word

    def test_prioritize_specific_identifiers(self, anchorer):
        """Test that specific identifiers are prioritized."""
        text = "Check prisma.disconnect and also check foo."
        identifiers = anchorer._extract_key_identifiers(text)

        # camelCase/specific identifiers should come before generic ones
        prisma_idx = identifiers.index("prisma") if "prisma" in identifiers else 999
        disconnect_idx = identifiers.index("disconnect") if "disconnect" in identifiers else 999

        # Both should be found
        assert "prisma" in identifiers
        assert "disconnect" in identifiers


class TestEdgeCases:
    """Edge case tests."""

    @pytest.fixture
    def anchorer(self):
        return FindingAnchorerNode()

    @pytest.mark.asyncio
    async def test_empty_findings(self, anchorer):
        """Test handling of empty findings list."""
        state = {
            "raw_llm_output": {"findings": []},
            "diff_mappings": {
                "file_mappings": {},
                "all_file_paths": [],
                "all_hunk_ids": [],
                "allowed_anchors": [],
                "line_to_hunk_lookup": {},
                "total_files": 0,
                "total_hunks": 0,
                "total_changed_lines": 0
            },
        }

        result = await anchorer._execute_node_logic(state)

        assert result["anchored_findings"] == []
        assert result["unanchored_findings"] == []
        assert result["anchoring_stats"]["total_findings"] == 0

    @pytest.mark.asyncio
    async def test_file_not_in_diff(self, anchorer):
        """Test handling when file is not in diff."""
        state = {
            "raw_llm_output": {
                "findings": [
                    {
                        "title": "Test",
                        "message": "Test message",
                        "file_path": "nonexistent.ts",
                        "severity": "low",
                        "category": "style",
                    }
                ]
            },
            "diff_mappings": {
                "file_mappings": {},
                "all_file_paths": ["other_file.ts"],
                "all_hunk_ids": [],
                "allowed_anchors": [],
                "line_to_hunk_lookup": {},
                "total_files": 1,
                "total_hunks": 0,
                "total_changed_lines": 0
            },
        }

        result = await anchorer._execute_node_logic(state)

        # Should go to unanchored since file is not in diff
        assert len(result["unanchored_findings"]) == 1
        assert len(result["anchored_findings"]) == 0
