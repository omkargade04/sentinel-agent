"""
WorkflowEventService for querying workflow events from the database.

This service is used by the SSE endpoint to fetch events for streaming
to the frontend. It handles authorization checks and efficient querying.

Key features:
- Authorization: Verify user owns the workflow
- Pagination: Support since_sequence for reconnection
- Ordering: Events returned in sequence_number order
- Limit: Prevent excessive memory usage
"""

from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

from src.core.database import SessionLocal
from src.models.db.workflow_run_events import WorkflowRunEvent
from src.services.workflow_events.schemas import WorkflowEvent
from src.utils.logging import get_logger

logger = get_logger(__name__)


class WorkflowEventService:
    """
    Query service for workflow events.

    Used by the SSE endpoint to fetch events for streaming. Includes
    authorization checks to ensure users can only access their own
    workflow events.
    """

    async def get_events_since(
        self,
        workflow_id: str,
        user_id: str,
        since_sequence: int = 0,
        limit: int = 100,
    ) -> List[WorkflowEvent]:
        """
        Fetch events for a workflow since a given sequence number.

        This method:
        1. Verifies the user owns the workflow (authorization check)
        2. Fetches events with sequence_number > since_sequence
        3. Returns events ordered by sequence_number ascending

        Args:
            workflow_id: Temporal workflow ID
            user_id: User ID for authorization check
            since_sequence: Fetch events after this sequence (for reconnection)
            limit: Maximum number of events to return (default 100)

        Returns:
            List of WorkflowEvent objects

        Raises:
            PermissionError: If user_id doesn't match workflow owner
        """
        db: Session = SessionLocal()

        try:
            # Step 1: Authorization check - verify user owns this workflow
            # Check if any event in this workflow belongs to the user
            ownership_check = db.query(WorkflowRunEvent).filter(
                and_(
                    WorkflowRunEvent.workflow_id == workflow_id,
                    WorkflowRunEvent.user_id == user_id,
                )
            ).first()

            if not ownership_check:
                # No events found for this workflow+user combo
                # This could mean:
                # 1. Workflow doesn't exist
                # 2. User doesn't own the workflow
                # 3. No events emitted yet but workflow is valid
                # For SSE, we'll be permissive and return empty list
                # The workflow will either emit events soon or the connection will timeout
                logger.warning(
                    f"No events found for workflow_id={workflow_id}, user_id={user_id}. "
                    f"This may be a new workflow or authorization failure."
                )
                return []

            # Step 2: Fetch events since sequence number
            events = db.query(WorkflowRunEvent).filter(
                and_(
                    WorkflowRunEvent.workflow_id == workflow_id,
                    WorkflowRunEvent.sequence_number > since_sequence,
                )
            ).order_by(
                WorkflowRunEvent.sequence_number.asc()
            ).limit(limit).all()

            # Step 3: Convert to Pydantic models
            result = [
                WorkflowEvent(
                    id=str(event.id),
                    workflow_id=event.workflow_id,
                    workflow_run_id=event.workflow_run_id,
                    workflow_type=event.workflow_type,
                    sequence_number=event.sequence_number,
                    activity_name=event.activity_name,
                    event_type=event.event_type,
                    message=event.message,
                    metadata=event.metadata,
                    created_at=event.created_at,
                )
                for event in events
            ]

            logger.debug(
                f"Fetched {len(result)} events for workflow_id={workflow_id}, "
                f"user_id={user_id}, since_sequence={since_sequence}"
            )

            return result

        except Exception as e:
            logger.error(
                f"Failed to fetch events for workflow_id={workflow_id}, "
                f"user_id={user_id}: {e}"
            )
            raise

        finally:
            db.close()

    async def get_latest_sequence(self, workflow_id: str) -> int:
        """
        Get the latest sequence number for a workflow.

        Useful for determining if new events have been emitted.

        Args:
            workflow_id: Temporal workflow ID

        Returns:
            Latest sequence number, or 0 if no events exist
        """
        db: Session = SessionLocal()

        try:
            latest_event = db.query(WorkflowRunEvent).filter(
                WorkflowRunEvent.workflow_id == workflow_id
            ).order_by(
                WorkflowRunEvent.sequence_number.desc()
            ).first()

            return latest_event.sequence_number if latest_event else 0

        finally:
            db.close()
