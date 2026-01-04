"""
Service for persisting indexing metadata to Postgres.
"""

import datetime
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import and_, update
from src.core.database import SessionLocal
from src.models.db.repositories import Repository
from src.models.db.repo_snapshots import RepoSnapshot

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