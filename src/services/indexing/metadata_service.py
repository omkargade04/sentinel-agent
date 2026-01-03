"""
Service for persisting indexing metadata to Postgres.
"""

import datetime
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import update
from src.core.database import SessionLocal
from src.graph.helpers.graph_types import FileNode
from src.models.db.repositories import Repository
from src.models.db.repo_snapshots import RepoSnapshot
from src.models.db.indexed_files import IndexedFile
from src.models.graph.indexing_stats import IndexingStats
from src.models.graph.repo_graph_result import RepoGraphResult

class MetadataService:
    """Persist indexing metadata to Postgres."""
    
    async def persist_indexing_metadata(
        self,
        *,
        repo_id: str,
        commit_sha: str,
        graph_result: RepoGraphResult,
        stats: IndexingStats,
    ) -> str:
        """
        Persist indexing metadata to Postgres.
        
        Writes:
        1. repo_snapshots (new snapshot record)
        2. indexed_files (all files discovered)
        3. repositories (update last_indexed_sha, last_indexed_at)
        
        Args:
            repo_id: Internal repo identifier
            commit_sha: Commit SHA indexed
            graph_result: Parsed graph with nodes/edges
            stats: Indexing statistics
        
        Returns:
            snapshot_id (UUID string)
        """
        db: Session = SessionLocal()
        
        try:
            # Create snapshot record
            snapshot_id = str(uuid.uuid4())
            snapshot = RepoSnapshot(
                id=snapshot_id,
                repository_id=repo_id,
                commit_sha=commit_sha,
                created_at=datetime.datetime.utcnow(),
            )
            db.add(snapshot)
            
            # Upsert indexed_files for all FileNode entries
            file_nodes = [
                node for node in graph_result.nodes if isinstance(node, FileNode)
            ]
            
            for file_node in file_nodes:
                indexed_file = IndexedFile(
                    id=str(uuid.uuid4()),
                    repository_id=repo_id,
                    snapshot_id=snapshot_id,
                    file_path=file_node.relative_path,
                    file_sha=file_node.file_sha or "",
                    language=file_node.language or "unknown",
                    file_size=file_node.size_bytes or 0,
                    line_count=file_node.line_count or 0,
                    last_modified=datetime.utcnow(),
                    index_status="indexed",
                    indexed_at=datetime.utcnow(),
                )
                db.merge(indexed_file)
                
            # Update repository last_indexed metadata
            db.execute(
                update(Repository)
                .where(Repository.id == repo_id)
                .values(
                    last_indexed_sha=commit_sha,
                    last_indexed_at=datetime.utcnow(),
                )
            )
            
            db.commit()
            
            return snapshot_id
        except Exception as e:
            db.rollback()
            raise Exception(f"Failed to persist metadata: {e}") from e
        finally:
            db.close()