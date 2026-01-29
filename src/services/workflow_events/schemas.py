"""
Pydantic schemas for workflow event data structures.

These schemas define the event types and data formats used throughout
the SSE workflow events system.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum


class WorkflowEventType(str, Enum):
    """
    Event types that can be emitted during workflow execution.

    - started: Activity has begun execution
    - progress: Intermediate progress update during long operations
    - completed: Activity finished successfully
    - failed: Activity encountered an error
    - workflow_started: Workflow has begun
    - workflow_completed: Workflow finished successfully
    - workflow_failed: Workflow encountered an error
    """
    STARTED = "started"
    PROGRESS = "progress"
    COMPLETED = "completed"
    FAILED = "failed"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"


class ActivityStatus(str, Enum):
    """
    Activity execution status for frontend rendering.

    Maps to UI states: pending → in_progress → completed/failed
    """
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowEventMetadata(BaseModel):
    """
    Activity-specific metadata that can be included in events.

    Examples:
    - commit_sha: str
    - file_count: int
    - symbol_count: int
    - nodes_created: int
    - error_details: str
    """
    pass  # Base class, activities can extend with specific fields


class WorkflowEvent(BaseModel):
    """
    Pydantic model representing a workflow event for serialization.

    Used for:
    - SSE endpoint response serialization
    - Activity event emission validation
    - Frontend consumption
    """
    id: str = Field(..., description="Event UUID")
    workflow_id: str = Field(..., description="Temporal workflow ID")
    workflow_run_id: str = Field(..., description="Temporal run ID")
    workflow_type: str = Field(..., description="Workflow type (repo_indexing, pr_review)")

    sequence_number: int = Field(..., description="Monotonic sequence for ordering and reconnection")

    activity_name: Optional[str] = Field(None, description="Activity that emitted the event")
    event_type: WorkflowEventType = Field(..., description="Event type")
    message: str = Field(..., description="Human-readable message")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Activity-specific data")

    created_at: datetime = Field(..., description="Event timestamp")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class EventContext(BaseModel):
    """
    Context information passed from workflow to activities for event emission.

    This is embedded in activity input dicts and used to construct
    WorkflowEventEmitter instances.
    """
    workflow_id: str
    workflow_run_id: str
    workflow_type: str
    user_id: Optional[str] = None
    repo_id: Optional[str] = None
    installation_id: Optional[int] = None

    class Config:
        # Allow construction from dict for activity deserialization
        extra = "forbid"
