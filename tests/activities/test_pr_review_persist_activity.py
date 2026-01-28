"""
Unit tests for persist_pr_review_metadata_activity.

Tests for:
- Activity input/output contract validation
- Service integration
- Error handling
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
import uuid


class TestPersistPRReviewMetadataActivity:
    """Tests for persist_pr_review_metadata_activity."""

    @pytest.fixture
    def sample_input(self):
        """Sample activity input data."""
        return {
            'repo_id': str(uuid.uuid4()),
            'github_repo_id': 12345,
            'github_repo_name': 'owner/repo',
            'pr_number': 42,
            'head_sha': 'abc123def456',
            'base_sha': 'xyz789',
            'workflow_id': 'pr-review:repo-123:42',
            'review_run_id': str(uuid.uuid4()),
            'review_output': {
                'findings': [
                    {
                        'finding_id': 'finding_1',
                        'file_path': 'src/main.py',
                        'severity': 'high',
                        'category': 'bug',
                        'message': 'Test finding',
                        'suggested_fix': 'Fix it',
                        'hunk_id': 'hunk_1',
                        'line_in_hunk': 5,
                    }
                ],
                'summary': 'Test review',
                'total_findings': 1,
            },
            'patches': [
                {
                    'file_path': 'src/main.py',
                    'hunks': [
                        {
                            'hunk_id': 'hunk_1',
                            'new_start': 10,
                            'lines': [' ctx', ' ctx', '+add'],
                        }
                    ],
                }
            ],
            'llm_model': 'gpt-4',
        }

    @pytest.mark.asyncio
    async def test_activity_returns_success_result(self, sample_input):
        """Test activity returns correct success structure."""
        mock_service_result = {
            'persisted': True,
            'review_run_id': sample_input['review_run_id'],
            'rows_written': {'review_runs': 1, 'review_findings': 1},
        }

        with patch('src.activities.pr_review_activities.MetadataService') as MockService:
            mock_instance = MockService.return_value
            mock_instance.persist_review_metadata = AsyncMock(return_value=mock_service_result)

            from src.activities.pr_review_activities import persist_pr_review_metadata_activity

            result = await persist_pr_review_metadata_activity(sample_input)

            assert result['persisted'] is True
            assert result['review_run_id'] == sample_input['review_run_id']
            assert result['rows_written']['review_runs'] == 1
            assert result['rows_written']['review_findings'] == 1

    @pytest.mark.asyncio
    async def test_activity_calls_service_with_correct_params(self, sample_input):
        """Test activity passes correct parameters to service."""
        with patch('src.activities.pr_review_activities.MetadataService') as MockService:
            mock_instance = MockService.return_value
            mock_instance.persist_review_metadata = AsyncMock(return_value={
                'persisted': True,
                'review_run_id': sample_input['review_run_id'],
                'rows_written': {'review_runs': 1, 'review_findings': 1},
            })

            from src.activities.pr_review_activities import persist_pr_review_metadata_activity

            await persist_pr_review_metadata_activity(sample_input)

            mock_instance.persist_review_metadata.assert_called_once_with(
                repo_id=sample_input['repo_id'],
                github_repo_id=sample_input['github_repo_id'],
                github_repo_name=sample_input['github_repo_name'],
                pr_number=sample_input['pr_number'],
                head_sha=sample_input['head_sha'],
                base_sha=sample_input['base_sha'],
                workflow_id=sample_input['workflow_id'],
                review_run_id=sample_input['review_run_id'],
                review_output=sample_input['review_output'],
                patches=sample_input['patches'],
                llm_model=sample_input['llm_model'],
            )

    @pytest.mark.asyncio
    async def test_activity_returns_failure_on_exception(self, sample_input):
        """Test activity returns failure result on exception."""
        with patch('src.activities.pr_review_activities.MetadataService') as MockService:
            mock_instance = MockService.return_value
            mock_instance.persist_review_metadata = AsyncMock(
                side_effect=Exception('Database connection failed')
            )

            from src.activities.pr_review_activities import persist_pr_review_metadata_activity

            result = await persist_pr_review_metadata_activity(sample_input)

            assert result['persisted'] is False
            assert result['review_run_id'] == sample_input['review_run_id']
            assert result['rows_written']['review_runs'] == 0
            assert result['rows_written']['review_findings'] == 0
            assert 'error' in result
            assert 'Database connection failed' in result['error']

    @pytest.mark.asyncio
    async def test_activity_defaults_llm_model_to_unknown(self):
        """Test activity uses 'unknown' as default llm_model."""
        input_data = {
            'repo_id': str(uuid.uuid4()),
            'github_repo_id': 12345,
            'github_repo_name': 'owner/repo',
            'pr_number': 42,
            'head_sha': 'abc123',
            'base_sha': 'def456',
            'workflow_id': 'workflow-123',
            'review_run_id': str(uuid.uuid4()),
            'review_output': {'findings': []},
            'patches': [],
            # llm_model NOT provided
        }

        with patch('src.activities.pr_review_activities.MetadataService') as MockService:
            mock_instance = MockService.return_value
            mock_instance.persist_review_metadata = AsyncMock(return_value={
                'persisted': True,
                'review_run_id': input_data['review_run_id'],
                'rows_written': {'review_runs': 1, 'review_findings': 0},
            })

            from src.activities.pr_review_activities import persist_pr_review_metadata_activity

            await persist_pr_review_metadata_activity(input_data)

            call_kwargs = mock_instance.persist_review_metadata.call_args.kwargs
            assert call_kwargs['llm_model'] == 'unknown'


class TestAnchorAndPublishActivityDbUpdate:
    """Tests for anchor_and_publish_activity's DB update behavior."""

    @pytest.fixture
    def sample_input_with_review_run_id(self):
        """Sample activity input with review_run_id."""
        return {
            'review_output': {
                'findings': [],
                'summary': 'Test review',
                'total_findings': 0,
            },
            'patches': [],
            'github_repo_name': 'owner/repo',
            'pr_number': 42,
            'head_sha': 'abc123',
            'installation_id': 12345,
            'review_run_id': str(uuid.uuid4()),
        }

    @pytest.mark.asyncio
    async def test_updates_review_run_on_successful_publish(self, sample_input_with_review_run_id):
        """Test that review_run is updated after successful GitHub publish."""
        mock_publish_result = Mock()
        mock_publish_result.published = True
        mock_publish_result.github_review_id = 98765
        mock_publish_result.anchored_comments = 0
        mock_publish_result.unanchored_findings = 0
        mock_publish_result.fallback_used = False
        mock_publish_result.publish_stats = Mock(
            github_api_calls=1,
            rate_limit_delays=0,
            retry_attempts=0,
            publish_duration_ms=100,
            position_calculations=0,
            position_failures=0,
            position_adjustments=0,
        )

        with patch('src.activities.pr_review_activities.PRApiClient'), \
             patch('src.activities.pr_review_activities.DiffPositionCalculator'), \
             patch('src.activities.pr_review_activities.ReviewPublisher') as MockPublisher, \
             patch('src.activities.pr_review_activities.MetadataService') as MockMetadataService:

            mock_publisher_instance = MockPublisher.return_value
            mock_publisher_instance.publish_review = AsyncMock(return_value=mock_publish_result)

            mock_metadata_instance = MockMetadataService.return_value
            mock_metadata_instance.update_review_run_status = AsyncMock(return_value=True)

            from src.activities.pr_review_activities import anchor_and_publish_activity

            result = await anchor_and_publish_activity(sample_input_with_review_run_id)

            # Verify publish succeeded
            assert result['published'] is True
            assert result['github_review_id'] == 98765

            # Verify update_review_run_status was called
            mock_metadata_instance.update_review_run_status.assert_called_once_with(
                review_run_id=sample_input_with_review_run_id['review_run_id'],
                published=True,
                github_review_id=98765,
            )

    @pytest.mark.asyncio
    async def test_does_not_update_when_no_review_run_id(self):
        """Test that DB update is skipped when review_run_id not provided."""
        input_without_review_run_id = {
            'review_output': {
                'findings': [],
                'summary': 'Test review',
                'total_findings': 0,
            },
            'patches': [],
            'github_repo_name': 'owner/repo',
            'pr_number': 42,
            'head_sha': 'abc123',
            'installation_id': 12345,
            # No review_run_id
        }

        mock_publish_result = Mock()
        mock_publish_result.published = True
        mock_publish_result.github_review_id = 98765
        mock_publish_result.anchored_comments = 0
        mock_publish_result.unanchored_findings = 0
        mock_publish_result.fallback_used = False
        mock_publish_result.publish_stats = Mock(
            github_api_calls=1,
            rate_limit_delays=0,
            retry_attempts=0,
            publish_duration_ms=100,
            position_calculations=0,
            position_failures=0,
            position_adjustments=0,
        )

        with patch('src.activities.pr_review_activities.PRApiClient'), \
             patch('src.activities.pr_review_activities.DiffPositionCalculator'), \
             patch('src.activities.pr_review_activities.ReviewPublisher') as MockPublisher, \
             patch('src.activities.pr_review_activities.MetadataService') as MockMetadataService:

            mock_publisher_instance = MockPublisher.return_value
            mock_publisher_instance.publish_review = AsyncMock(return_value=mock_publish_result)

            mock_metadata_instance = MockMetadataService.return_value
            mock_metadata_instance.update_review_run_status = AsyncMock(return_value=True)

            from src.activities.pr_review_activities import anchor_and_publish_activity

            result = await anchor_and_publish_activity(input_without_review_run_id)

            # Verify publish succeeded but DB update was NOT called
            assert result['published'] is True
            mock_metadata_instance.update_review_run_status.assert_not_called()
