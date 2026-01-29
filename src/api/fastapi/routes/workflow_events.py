"""
SSE endpoint for streaming workflow progress events.

This endpoint provides real-time updates on workflow execution progress
via Server-Sent Events. The frontend connects using EventSource and receives
events as they are emitted by Temporal activities.

Key features:
- JWT authentication via query parameter (EventSource doesn't support headers)
- Reconnection support via last_event_id
- Heartbeats every 30 seconds
- Auto-closes on workflow completion/failure
- Authorization check ensures users can only access their own workflows
"""

import asyncio
import json
from typing import Optional, AsyncGenerator
from fastapi import APIRouter, Query, HTTPException, Depends
from fastapi.responses import StreamingResponse
from supabase import Client

from src.core.supabase_client import get_supabase_client
from src.services.workflow_events import WorkflowEventService, WorkflowEventType
from src.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflow_events"])


@router.get("/{workflow_id}/events")
async def stream_workflow_events(
    workflow_id: str,
    token: str = Query(..., description="JWT authentication token"),
    last_event_id: Optional[int] = Query(None, description="Last received sequence number for reconnection"),
    supabase: Client = Depends(get_supabase_client),
):
    """
    Stream workflow progress events via Server-Sent Events (SSE).

    This endpoint provides real-time progress updates for a workflow execution.
    The frontend connects using EventSource, which automatically handles
    reconnection and provides the last_event_id for resuming streams.

    Authentication:
    - JWT token passed as query parameter (EventSource doesn't support headers)
    - Token is validated via Supabase auth

    Event Format:
    ```
    event: activity
    id: 5
    data: {"sequence_number": 5, "activity_name": "clone_repo_activity", ...}

    ```

    Reconnection:
    - Client passes last_event_id query parameter
    - Server resumes from that sequence number
    - Handles network interruptions gracefully

    Terminal Events:
    - workflow_completed: Closes stream after successful workflow
    - workflow_failed: Closes stream after workflow error

    Args:
        workflow_id: Temporal workflow ID
        token: JWT token for authentication
        last_event_id: Optional sequence number for reconnection
        supabase: Supabase client for auth validation

    Returns:
        StreamingResponse with text/event-stream content type

    Raises:
        HTTPException 401: Invalid or expired token
        HTTPException 403: User doesn't own this workflow
    """
    # Step 1: Validate JWT token
    try:
        auth_response = supabase.auth.get_user(token)
        supabase_user = auth_response.user

        if not supabase_user:
            logger.warning(f"Invalid token provided for workflow_id={workflow_id}")
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired authentication token"
            )

        user_email = supabase_user.email
        logger.info(f"SSE connection initiated by {user_email} for workflow_id={workflow_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Authentication error for workflow SSE: {e}")
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed: {str(e)}"
        )

    # Step 2: Get user_id from email
    # We need to query local DB for user_id, but for SSE we'll use a simplified approach
    # The WorkflowEventService will check authorization internally
    # For now, we'll trust the token and let the service handle auth
    # In production, you'd want to fetch user_id from local DB here

    # For this implementation, we'll pass user_email as user_id
    # This requires that event_context stores email instead of UUID
    # Or we need to query the User table here
    # Let's query the User table to get the proper user_id

    from src.core.database import SessionLocal
    from src.models.db.users import User

    db = SessionLocal()
    try:
        local_user = db.query(User).filter(User.email == user_email).first()
        if not local_user:
            logger.error(f"User {user_email} not found in local database")
            raise HTTPException(
                status_code=404,
                detail="User not found in database"
            )
        user_id = str(local_user.user_id)
    finally:
        db.close()

    # Step 3: Create event generator
    async def event_generator() -> AsyncGenerator[str, None]:
        """
        Generate SSE events by polling the database.

        Polls every 500ms for new events and streams them to the client.
        Includes heartbeats every 30 seconds to keep connection alive.
        """
        service = WorkflowEventService()
        last_seq = last_event_id or 0
        heartbeat_counter = 0
        poll_interval = 0.5  # 500ms
        heartbeat_interval = 30  # 30 seconds
        polls_per_heartbeat = int(heartbeat_interval / poll_interval)

        # Send connection established event
        yield f"event: connected\ndata: {json.dumps({'workflow_id': workflow_id, 'sequence': last_seq})}\n\n"

        while True:
            try:
                # Fetch new events
                events = await service.get_events_since(
                    workflow_id=workflow_id,
                    user_id=user_id,
                    since_sequence=last_seq,
                    limit=50,  # Fetch up to 50 events per poll
                )

                # Stream events
                for event in events:
                    # Format: event: <type>\nid: <seq>\ndata: <json>\n\n
                    event_data = event.model_dump(mode="json")
                    yield f"event: activity\nid: {event.sequence_number}\ndata: {json.dumps(event_data)}\n\n"

                    last_seq = event.sequence_number

                    # Check for terminal events
                    if event.event_type in [
                        WorkflowEventType.WORKFLOW_COMPLETED.value,
                        WorkflowEventType.WORKFLOW_FAILED.value,
                    ]:
                        logger.info(
                            f"Terminal event received for workflow_id={workflow_id}: {event.event_type}. "
                            f"Closing SSE connection."
                        )
                        # Send final event and close
                        yield f"event: close\ndata: {json.dumps({'reason': event.event_type})}\n\n"
                        return

                # Heartbeat to keep connection alive
                heartbeat_counter += 1
                if heartbeat_counter >= polls_per_heartbeat:
                    yield ": heartbeat\n\n"
                    heartbeat_counter = 0

                # Wait before next poll
                await asyncio.sleep(poll_interval)

            except Exception as e:
                logger.error(f"Error in SSE event generator for workflow_id={workflow_id}: {e}")
                # Send error event and close
                error_data = {"error": str(e), "workflow_id": workflow_id}
                yield f"event: error\ndata: {json.dumps(error_data)}\n\n"
                return

    # Step 4: Return streaming response
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Connection": "keep-alive",
        },
    )
