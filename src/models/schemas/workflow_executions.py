from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class WorkflowExecutionBase(BaseModel):
    workflow_id: UUID
    status: Optional[str] = None
    error_message: Optional[str] = None

class WorkflowExecutionCreate(WorkflowExecutionBase):
    pass

class WorkflowExecutionUpdate(BaseModel):
    status: Optional[str] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

class WorkflowExecutionInDBBase(WorkflowExecutionBase):
    id: UUID
    started_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class WorkflowExecution(WorkflowExecutionInDBBase):
    pass
