"""
Service for persisting indexing and PR review metadata to Postgres.
"""

import datetime
import uuid
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from src.core.database import SessionLocal
from src.models.db.repositories import Repository
from src.models.db.repo_snapshots import RepoSnapshot
from src.models.db.pull_requests import PullRequest
from src.models.db.review_runs import ReviewRun
from src.models.db.review_findings import ReviewFinding


def compute_line_number(hunk_data: Dict[str, Any], target_index: int) -> int:
    """
    Compute new-file line number from hunk lines.

    Args:
        hunk_data: Dict containing 'new_start' and 'lines' keys
        target_index: 0-based index within hunk.lines to compute line number for

    Returns:
        Absolute line number in the new file
    """
    new_line = hunk_data.get('new_start', 1)
    lines = hunk_data.get('lines', [])

    for i, line in enumerate(lines[:target_index]):
        if not line.startswith('-'):  # context or addition
            new_line += 1

    return new_line


def normalize_severity(severity: str) -> str:
    """
    Normalize severity values to database-compatible format.

    Maps LLM output severities to standard values:
    - blocker/critical -> CRITICAL
    - high -> HIGH
    - medium -> MEDIUM
    - low -> LOW
    - nit/nitpick -> NIT
    """
    severity_lower = severity.lower().strip()

    severity_map = {
        'blocker': 'CRITICAL',
        'critical': 'CRITICAL',
        'high': 'HIGH',
        'medium': 'MEDIUM',
        'low': 'LOW',
        'nit': 'NIT',
        'nitpick': 'NIT',
    }

    return severity_map.get(severity_lower, severity.upper())

class MetadataService:
    """Persist indexing metadata to Postgres.
    
    This service creates snapshot records and updates repository timestamps.
    The actual code graph data (files, symbols, edges) is stored in Neo4j.
    """
    
    async def persist_indexing_metadata(
        self,
        *,
        repo_id: str,
        github_repo_id: int,
        commit_sha: str | None = None,
    ) -> str:
        """
        Persist indexing metadata to Postgres.
        
        Creates a snapshot record to track this indexing run and updates
        the repository's last_indexed_at timestamp. This allows linking
        PR reviews to specific indexing snapshots.
        
        Args:
            repo_id: Internal repo identifier
            github_repo_id: GitHub repository ID
            commit_sha: Optional commit SHA indexed. If None, snapshot is branch-based.
        
        Returns:
            snapshot_id (UUID string)
        """
        db: Session = SessionLocal()
        
        try:
            # Create snapshot record (commit_sha can be None for branch-based indexing)
            snapshot_id = str(uuid.uuid4())
            snapshot = RepoSnapshot(
                id=snapshot_id,
                repository_id=repo_id,
                commit_sha=commit_sha,
                created_at=datetime.datetime.utcnow(),
            )
            db.add(snapshot)
            
            # Update repository last_indexed_at timestamp
            db.execute(
                update(Repository)
                .where(and_(Repository.github_repo_id == github_repo_id, Repository.id == repo_id))
                .values(last_indexed_at=datetime.datetime.utcnow())
            )
            
            db.commit()
            
            return snapshot_id
        except Exception as e:
            db.rollback()
            raise Exception(f"Failed to persist metadata: {e}") from e
        finally:
            db.close()
            
    async def get_latest_snapshot_sha(self, repo_id: str) -> str | None:
        """
        Get the commit_sha from the most recent snapshot for a repository.
        
        Used to skip re-indexing when the branch head hasn't changed.
        
        Args:
            repo_id: Internal repository identifier (UUID)
        
        Returns:
            commit_sha string if a snapshot exists, None if no snapshots or sha is NULL
        """
        db: Session = SessionLocal()
        
        try:
            # Query latest snapshot by created_at descending
            latest_snapshot = db.query(RepoSnapshot).filter(
                RepoSnapshot.repository_id == repo_id
            ).order_by(
                RepoSnapshot.created_at.desc()
            ).first()
            
            if latest_snapshot is None:
                return None
            
            # Return commit_sha (may be None if snapshot was branch-based)
            return latest_snapshot.commit_sha

        except Exception as e:
            raise Exception(f"Failed to fetch latest snapshot: {e}") from e
        finally:
            db.close()

    async def persist_review_metadata(
        self,
        *,
        repo_id: str,
        github_repo_id: int,
        github_repo_name: str,
        pr_number: int,
        head_sha: str,
        base_sha: str,
        workflow_id: str,
        review_run_id: str,
        review_output: Dict[str, Any],
        patches: List[Dict[str, Any]],
        llm_model: str,
    ) -> Dict[str, Any]:
        """
        Persist PR review run and findings metadata to Postgres.

        This method is called BEFORE GitHub publish to ensure full audit trail
        regardless of publish success.

        Args:
            repo_id: Internal repository UUID
            github_repo_id: GitHub repository ID
            github_repo_name: Repository name (owner/repo)
            pr_number: Pull request number
            head_sha: PR head commit SHA
            base_sha: PR base commit SHA
            workflow_id: Temporal workflow ID
            review_run_id: Generated review run UUID
            review_output: Dict containing 'findings' list from LLM
            patches: List of PRFilePatch dicts for line number computation
            llm_model: LLM model used for review generation

        Returns:
            Dict with persisted=True, review_run_id, and rows_written counts
        """
        db: Session = SessionLocal()

        try:
            # Build hunk lookup for line number computation
            # Maps hunk_id -> hunk data (with new_start and lines)
            hunk_lookup: Dict[str, Dict[str, Any]] = {}
            for patch in patches:
                for hunk in patch.get('hunks', []):
                    hunk_id = hunk.get('hunk_id')
                    if hunk_id:
                        hunk_lookup[hunk_id] = hunk

            # Step 1: Upsert PullRequest by (repository_id, pr_number) for FK constraint
            # Use INSERT ... ON CONFLICT DO UPDATE to handle race conditions
            pr_stmt = pg_insert(PullRequest).values(
                repository_id=repo_id,
                pr_number=pr_number,
                author_github_id=0,  # Placeholder - we don't have this info here
                title=f"PR #{pr_number}",  # Placeholder title
                head_sha=head_sha,
                base_sha=base_sha,
                state='open',
                created_at=datetime.datetime.utcnow(),
                updated_at=datetime.datetime.utcnow(),
            ).on_conflict_do_update(
                index_elements=['repository_id', 'pr_number'],
                set_={
                    'head_sha': head_sha,
                    'base_sha': base_sha,
                    'updated_at': datetime.datetime.utcnow(),
                }
            ).returning(PullRequest.id)

            result = db.execute(pr_stmt)
            pr_row = result.fetchone()
            pr_id = pr_row[0] if pr_row else None

            # Step 2: Insert ReviewRun with published=false
            review_run = ReviewRun(
                id=review_run_id,
                pr_id=pr_id,
                llm_model=llm_model,
                head_sha=head_sha,
                temporal_workflow_id=workflow_id,
                published=False,
                started_at=datetime.datetime.utcnow(),
                status='pending',
            )
            db.add(review_run)

            # Step 3: Batch insert ReviewFindings
            findings = review_output.get('findings', [])
            findings_written = 0

            for finding in findings:
                # Compute line_number from hunk if available
                hunk_id = finding.get('hunk_id')
                line_in_hunk = finding.get('line_in_hunk')
                line_number = 0  # Default

                if hunk_id and line_in_hunk is not None and hunk_id in hunk_lookup:
                    hunk_data = hunk_lookup[hunk_id]
                    line_number = compute_line_number(hunk_data, line_in_hunk)
                elif 'line_number' in finding:
                    line_number = finding['line_number']

                # Normalize severity
                severity = normalize_severity(finding.get('severity', 'medium'))

                review_finding = ReviewFinding(
                    review_run_id=review_run_id,
                    file_path=finding.get('file_path', ''),
                    line_number=line_number,
                    finding_type=finding.get('category', 'general'),
                    severity=severity,
                    message=finding.get('message', ''),
                    suggestion=finding.get('suggested_fix'),
                    hunk_id=hunk_id,
                    github_comment_id=None,  # Will be updated after GitHub publish
                )
                db.add(review_finding)
                findings_written += 1

            db.commit()

            return {
                "persisted": True,
                "review_run_id": review_run_id,
                "rows_written": {
                    "review_runs": 1,
                    "review_findings": findings_written,
                }
            }

        except Exception as e:
            db.rollback()
            raise Exception(f"Failed to persist review metadata: {e}") from e
        finally:
            db.close()

    async def update_review_run_status(
        self,
        *,
        review_run_id: str,
        published: bool,
        github_review_id: Optional[int] = None,
    ) -> bool:
        """
        Update review run status after GitHub publish.

        Called by anchor_and_publish_activity AFTER successful GitHub publish.

        Args:
            review_run_id: Review run UUID to update
            published: Whether review was successfully published
            github_review_id: GitHub review ID if published

        Returns:
            True if update was successful
        """
        db: Session = SessionLocal()

        try:
            update_values = {
                'published': published,
                'completed_at': datetime.datetime.utcnow(),
                'status': 'completed' if published else 'failed',
            }

            if github_review_id is not None:
                update_values['github_review_id'] = github_review_id

            db.execute(
                update(ReviewRun)
                .where(ReviewRun.id == review_run_id)
                .values(**update_values)
            )

            db.commit()
            return True

        except Exception as e:
            db.rollback()
            raise Exception(f"Failed to update review run status: {e}") from e
        finally:
            db.close()