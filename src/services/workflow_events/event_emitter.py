"""
WorkflowEventEmitter service for emitting workflow progress events from activities.

This service is used by Temporal activities to persist progress events to the
workflow_run_events table. Activities cannot use FastAPI's Depends(get_db),
so this service creates its own database sessions following the pattern in
MetadataService.

Key features:
- Thread-safe sequence number generation (query max + 1)
- Automatic DB session management (try/finally)
- Non-blocking: errors don't fail the activity
- Activity-specific convenience methods (emit_started, emit_progress, etc.)
"""

import datetime
import uuid
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from src.core.database import SessionLocal
from src.models.db.workflow_run_events import WorkflowRunEvent
from src.services.workflow_events.schemas import WorkflowEventType
from src.utils.logging import get_logger

logger = get_logger(__name__)


class WorkflowEventEmitter:
    """
    Emit workflow progress events from Temporal activities.

    Activities use this class to record progress events that are streamed
    to the frontend via SSE. Each event is persisted to the database with
    a monotonically increasing sequence number.

    Example usage in activity:
        emitter = WorkflowEventEmitter(**event_context)
        await emitter.emit_started("clone_repo_activity", "Cloning repository...")
        # ... do work ...
        await emitter.emit_completed("clone_repo_activity", "Cloned successfully",
                                     metadata={"commit_sha": "abc123"})
    """

    def __init__(
        self,
        workflow_id: str,
        workflow_run_id: str,
        workflow_type: str,
        user_id: Optional[str] = None,
        repo_id: Optional[str] = None,
        installation_id: Optional[int] = None,
    ):
        """
        Initialize event emitter with workflow context.

        Args:
            workflow_id: Temporal workflow ID
            workflow_run_id: Temporal run ID
            workflow_type: Type of workflow (e.g., 'repo_indexing', 'pr_review')
            user_id: User who triggered the workflow (for authorization)
            repo_id: Repository ID (if applicable)
            installation_id: GitHub installation ID (if applicable)
        """
        self.workflow_id = workflow_id
        self.workflow_run_id = workflow_run_id
        self.workflow_type = workflow_type
        self.user_id = user_id
        self.repo_id = repo_id
        self.installation_id = installation_id

    async def emit_started(
        self, activity_name: str, message: str, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Emit activity started event.

        Args:
            activity_name: Name of the activity (e.g., 'clone_repo_activity')
            message: Human-readable message (e.g., 'Cloning repository...')
            metadata: Optional activity-specific data
        """
        await self._emit(
            activity_name=activity_name,
            event_type=WorkflowEventType.STARTED,
            message=message,
            metadata=metadata or {},
        )

    async def emit_progress(
        self, activity_name: str, message: str, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Emit intermediate progress update.

        Use for long-running operations to provide granular feedback.
        Example: 'Parsed 50/150 files...'

        Args:
            activity_name: Name of the activity
            message: Progress message
            metadata: Optional progress data (e.g., file_count, percentage)
        """
        await self._emit(
            activity_name=activity_name,
            event_type=WorkflowEventType.PROGRESS,
            message=message,
            metadata=metadata or {},
        )

    async def emit_completed(
        self, activity_name: str, message: str, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Emit activity completed event.

        Args:
            activity_name: Name of the activity
            message: Completion message (e.g., 'Cloned to /tmp/repo')
            metadata: Optional result data (e.g., commit_sha, stats)
        """
        await self._emit(
            activity_name=activity_name,
            event_type=WorkflowEventType.COMPLETED,
            message=message,
            metadata=metadata or {},
        )

    async def emit_failed(
        self, activity_name: str, message: str, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Emit activity failed event.

        Args:
            activity_name: Name of the activity
            message: Error message (e.g., 'Clone failed: 404 Not Found')
            metadata: Optional error details
        """
        await self._emit(
            activity_name=activity_name,
            event_type=WorkflowEventType.FAILED,
            message=message,
            metadata=metadata or {},
        )

    async def emit_workflow_event(
        self, event_type: WorkflowEventType, message: str, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Emit workflow-level event (started, completed, failed).

        Used for workflow lifecycle events rather than activity-specific events.

        Args:
            event_type: WorkflowEventType (WORKFLOW_STARTED, WORKFLOW_COMPLETED, etc.)
            message: Workflow-level message
            metadata: Optional workflow data
        """
        await self._emit(
            activity_name=None,
            event_type=event_type,
            message=message,
            metadata=metadata or {},
        )

    async def _emit(
        self,
        activity_name: Optional[str],
        event_type: WorkflowEventType,
        message: str,
        metadata: Dict[str, Any],
    ) -> None:
        """
        Internal method to persist event to database.

        Creates its own DB session (activities can't use FastAPI Depends).
        Errors are logged but don't fail the activity.

        Args:
            activity_name: Name of activity (None for workflow-level events)
            event_type: Type of event
            message: Human-readable message
            metadata: Activity-specific data
        """
        db: Session = SessionLocal()

        try:
            # Step 1: Get next sequence number (max + 1)
            # This query is thread-safe due to transaction isolation
            max_seq = db.execute(
                select(func.max(WorkflowRunEvent.sequence_number)).where(
                    WorkflowRunEvent.workflow_id == self.workflow_id
                )
            ).scalar()

            next_seq = (max_seq or 0) + 1

            # Step 2: Insert event
            event = WorkflowRunEvent(
                id=uuid.uuid4(),
                workflow_id=self.workflow_id,
                workflow_run_id=self.workflow_run_id,
                workflow_type=self.workflow_type,
                user_id=self.user_id,
                installation_id=self.installation_id,
                repo_id=self.repo_id,
                sequence_number=next_seq,
                activity_name=activity_name,
                event_type=event_type.value,
                message=message,
                metadata=metadata,
                created_at=datetime.datetime.utcnow(),
            )

            db.add(event)
            db.commit()

            logger.debug(
                f"Emitted event: workflow_id={self.workflow_id}, "
                f"seq={next_seq}, type={event_type.value}, "
                f"activity={activity_name}, message={message}"
            )

        except Exception as e:
            db.rollback()
            # Log error but don't fail the activity
            # Event emission is best-effort; activity logic is primary
            logger.warning(
                f"Failed to emit workflow event (workflow_id={self.workflow_id}, "
                f"activity={activity_name}, type={event_type.value}): {e}"
            )

        finally:
            db.close()
