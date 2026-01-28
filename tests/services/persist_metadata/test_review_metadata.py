"""
Unit tests for PR review metadata persistence.

Tests for:
- compute_line_number() - line number computation from hunk data
- normalize_severity() - severity normalization
- MetadataService.persist_review_metadata() - with mocked DB
- MetadataService.update_review_run_status() - with mocked DB
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
import uuid

from src.services.persist_metadata.persist_metadata_service import (
    compute_line_number,
    normalize_severity,
    MetadataService,
)


class TestComputeLineNumber:
    """Tests for compute_line_number helper function."""

    def test_target_index_zero_returns_new_start(self):
        """When target_index is 0, return new_start (no lines counted)."""
        hunk = {'new_start': 10, 'lines': [' context', '+addition', '-deletion']}
        assert compute_line_number(hunk, 0) == 10

    def test_counts_context_lines(self):
        """Context lines (starting with space) increment line count."""
        hunk = {'new_start': 10, 'lines': [' context1', ' context2', '+addition']}
        # target_index=2: count lines 0,1 -> 2 context lines -> 10 + 2 = 12
        assert compute_line_number(hunk, 2) == 12

    def test_counts_addition_lines(self):
        """Addition lines (starting with +) increment line count."""
        hunk = {'new_start': 10, 'lines': ['+add1', '+add2', ' context']}
        # target_index=2: count lines 0,1 -> 2 additions -> 10 + 2 = 12
        assert compute_line_number(hunk, 2) == 12

    def test_skips_deletion_lines(self):
        """Deletion lines (starting with -) do NOT increment line count."""
        hunk = {'new_start': 10, 'lines': [' context', '-deleted', '+added', ' context2']}
        # target_index=3: count lines 0,1,2
        # line 0: ' context' -> count (11)
        # line 1: '-deleted' -> skip (still 11)
        # line 2: '+added' -> count (12)
        # Result: 12
        assert compute_line_number(hunk, 3) == 12

    def test_complex_hunk_scenario(self):
        """Test with a realistic hunk containing mixed line types."""
        hunk = {
            'new_start': 100,
            'lines': [
                ' def foo():',        # 0: context -> 101
                '     """Doc."""',    # 1: context -> 102
                '-    old_code()',    # 2: deletion -> skip
                '+    new_code()',    # 3: addition -> 103
                '+    extra()',       # 4: addition -> 104
                ' ',                  # 5: context -> 105
                ' def bar():',        # 6: context -> 106
            ]
        }
        # target_index=6: count lines 0-5
        # 0: context +1 (101)
        # 1: context +1 (102)
        # 2: deletion skip (102)
        # 3: addition +1 (103)
        # 4: addition +1 (104)
        # 5: context +1 (105)
        # Current position: 105
        assert compute_line_number(hunk, 6) == 105

    def test_empty_lines_list(self):
        """Handle empty lines list gracefully."""
        hunk = {'new_start': 50, 'lines': []}
        assert compute_line_number(hunk, 0) == 50

    def test_missing_new_start_defaults_to_one(self):
        """If new_start missing, default to 1."""
        hunk = {'lines': [' context', '+add']}
        assert compute_line_number(hunk, 1) == 2  # 1 + 1 context line

    def test_target_beyond_lines_length(self):
        """Target index beyond lines length counts all available lines."""
        hunk = {'new_start': 10, 'lines': [' a', ' b']}
        # target_index=5 but only 2 lines exist -> counts both
        assert compute_line_number(hunk, 5) == 12  # 10 + 2


class TestNormalizeSeverity:
    """Tests for normalize_severity helper function."""

    def test_blocker_maps_to_critical(self):
        assert normalize_severity('blocker') == 'CRITICAL'
        assert normalize_severity('BLOCKER') == 'CRITICAL'
        assert normalize_severity('Blocker') == 'CRITICAL'

    def test_critical_maps_to_critical(self):
        assert normalize_severity('critical') == 'CRITICAL'
        assert normalize_severity('CRITICAL') == 'CRITICAL'

    def test_high_maps_to_high(self):
        assert normalize_severity('high') == 'HIGH'
        assert normalize_severity('HIGH') == 'HIGH'
        assert normalize_severity('High') == 'HIGH'

    def test_medium_maps_to_medium(self):
        assert normalize_severity('medium') == 'MEDIUM'
        assert normalize_severity('MEDIUM') == 'MEDIUM'

    def test_low_maps_to_low(self):
        assert normalize_severity('low') == 'LOW'
        assert normalize_severity('LOW') == 'LOW'

    def test_nit_maps_to_nit(self):
        assert normalize_severity('nit') == 'NIT'
        assert normalize_severity('NIT') == 'NIT'

    def test_nitpick_maps_to_nit(self):
        assert normalize_severity('nitpick') == 'NIT'
        assert normalize_severity('NITPICK') == 'NIT'

    def test_unknown_severity_uppercased(self):
        """Unknown severities are uppercased."""
        assert normalize_severity('unknown') == 'UNKNOWN'
        assert normalize_severity('custom') == 'CUSTOM'
        assert normalize_severity('warning') == 'WARNING'

    def test_whitespace_trimmed(self):
        """Whitespace is trimmed before processing."""
        assert normalize_severity('  high  ') == 'HIGH'
        assert normalize_severity('\tblocker\n') == 'CRITICAL'


class TestMetadataServicePersistReviewMetadata:
    """Tests for MetadataService.persist_review_metadata() with mocked DB."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = (uuid.uuid4(),)
        return session

    @pytest.fixture
    def sample_review_output(self):
        """Sample review output with findings."""
        return {
            'findings': [
                {
                    'finding_id': 'finding_1',
                    'file_path': 'src/main.py',
                    'severity': 'high',
                    'category': 'bug',
                    'message': 'Potential null pointer',
                    'suggested_fix': 'Add null check',
                    'hunk_id': 'hunk_1_main',
                    'line_in_hunk': 2,
                },
                {
                    'finding_id': 'finding_2',
                    'file_path': 'src/utils.py',
                    'severity': 'blocker',
                    'category': 'security',
                    'message': 'SQL injection vulnerability',
                    'suggested_fix': 'Use parameterized queries',
                    'hunk_id': None,  # No hunk anchoring
                    'line_number': 50,
                },
            ],
            'summary': 'Review found 2 issues',
            'total_findings': 2,
        }

    @pytest.fixture
    def sample_patches(self):
        """Sample patches with hunks for line computation."""
        return [
            {
                'file_path': 'src/main.py',
                'hunks': [
                    {
                        'hunk_id': 'hunk_1_main',
                        'new_start': 10,
                        'lines': [' def foo():', '     pass', '+    new_line()'],
                    }
                ],
            },
        ]

    @pytest.mark.asyncio
    async def test_persist_creates_review_run_and_findings(
        self, mock_session, sample_review_output, sample_patches
    ):
        """Test that persist_review_metadata creates ReviewRun and ReviewFindings."""
        with patch('src.services.persist_metadata.persist_metadata_service.SessionLocal') as mock_local:
            mock_local.return_value = mock_session

            service = MetadataService()
            review_run_id = str(uuid.uuid4())

            result = await service.persist_review_metadata(
                repo_id=str(uuid.uuid4()),
                github_repo_id=12345,
                github_repo_name='owner/repo',
                pr_number=42,
                head_sha='abc123',
                base_sha='def456',
                workflow_id='workflow-123',
                review_run_id=review_run_id,
                review_output=sample_review_output,
                patches=sample_patches,
                llm_model='gpt-4',
            )

            assert result['persisted'] is True
            assert result['review_run_id'] == review_run_id
            assert result['rows_written']['review_runs'] == 1
            assert result['rows_written']['review_findings'] == 2

            # Verify session methods were called
            mock_session.add.assert_called()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_computes_line_numbers_from_hunks(
        self, mock_session, sample_patches
    ):
        """Test that line numbers are computed from hunk data."""
        review_output = {
            'findings': [
                {
                    'finding_id': 'finding_1',
                    'file_path': 'src/main.py',
                    'severity': 'high',
                    'category': 'bug',
                    'message': 'Issue',
                    'suggested_fix': 'Fix it',
                    'hunk_id': 'hunk_1_main',
                    'line_in_hunk': 2,  # Should compute to line 12
                },
            ],
        }

        with patch('src.services.persist_metadata.persist_metadata_service.SessionLocal') as mock_local:
            mock_local.return_value = mock_session

            service = MetadataService()

            # Capture the ReviewFinding objects added to session
            added_findings = []
            original_add = mock_session.add

            def capture_add(obj):
                if hasattr(obj, 'line_number'):
                    added_findings.append(obj)
                return original_add(obj)

            mock_session.add = capture_add

            await service.persist_review_metadata(
                repo_id=str(uuid.uuid4()),
                github_repo_id=12345,
                github_repo_name='owner/repo',
                pr_number=42,
                head_sha='abc123',
                base_sha='def456',
                workflow_id='workflow-123',
                review_run_id=str(uuid.uuid4()),
                review_output=review_output,
                patches=sample_patches,
                llm_model='gpt-4',
            )

            # Verify line number was computed correctly
            # hunk has new_start=10, lines[0]=' def foo():' (context), lines[1]='     pass' (context)
            # target_index=2 -> count 2 context lines -> 10 + 2 = 12
            assert len(added_findings) == 1
            assert added_findings[0].line_number == 12

    @pytest.mark.asyncio
    async def test_persist_normalizes_severity(self, mock_session, sample_patches):
        """Test that severity values are normalized."""
        review_output = {
            'findings': [
                {
                    'finding_id': 'finding_1',
                    'file_path': 'src/main.py',
                    'severity': 'blocker',  # Should become CRITICAL
                    'category': 'bug',
                    'message': 'Critical issue',
                    'suggested_fix': 'Fix immediately',
                },
            ],
        }

        with patch('src.services.persist_metadata.persist_metadata_service.SessionLocal') as mock_local:
            mock_local.return_value = mock_session

            service = MetadataService()

            added_findings = []
            original_add = mock_session.add

            def capture_add(obj):
                if hasattr(obj, 'severity'):
                    added_findings.append(obj)
                return original_add(obj)

            mock_session.add = capture_add

            await service.persist_review_metadata(
                repo_id=str(uuid.uuid4()),
                github_repo_id=12345,
                github_repo_name='owner/repo',
                pr_number=42,
                head_sha='abc123',
                base_sha='def456',
                workflow_id='workflow-123',
                review_run_id=str(uuid.uuid4()),
                review_output=review_output,
                patches=sample_patches,
                llm_model='gpt-4',
            )

            assert len(added_findings) == 1
            assert added_findings[0].severity == 'CRITICAL'


class TestMetadataServiceUpdateReviewRunStatus:
    """Tests for MetadataService.update_review_run_status()."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_update_sets_published_true(self, mock_session):
        """Test updating review_run with published=True."""
        with patch('src.services.persist_metadata.persist_metadata_service.SessionLocal') as mock_local:
            mock_local.return_value = mock_session

            service = MetadataService()
            review_run_id = str(uuid.uuid4())

            result = await service.update_review_run_status(
                review_run_id=review_run_id,
                published=True,
                github_review_id=12345,
            )

            assert result is True
            mock_session.execute.assert_called_once()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_sets_published_false_on_failure(self, mock_session):
        """Test updating review_run with published=False on failure."""
        with patch('src.services.persist_metadata.persist_metadata_service.SessionLocal') as mock_local:
            mock_local.return_value = mock_session

            service = MetadataService()
            review_run_id = str(uuid.uuid4())

            result = await service.update_review_run_status(
                review_run_id=review_run_id,
                published=False,
            )

            assert result is True
            mock_session.execute.assert_called_once()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_rolls_back_on_error(self, mock_session):
        """Test that errors trigger rollback."""
        mock_session.execute.side_effect = Exception('DB error')

        with patch('src.services.persist_metadata.persist_metadata_service.SessionLocal') as mock_local:
            mock_local.return_value = mock_session

            service = MetadataService()

            with pytest.raises(Exception, match='Failed to update review run status'):
                await service.update_review_run_status(
                    review_run_id=str(uuid.uuid4()),
                    published=True,
                )

            mock_session.rollback.assert_called_once()
