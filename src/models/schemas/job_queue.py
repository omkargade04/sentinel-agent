from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any

class JobQueueBase(BaseModel):
    job_type: str
    status: str = 'pending'
    payload: Dict[str, Any]
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None

class JobQueueCreate(JobQueueBase):
    pass

class JobQueueUpdate(BaseModel):
    status: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    retry_count: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

class JobQueueInDBBase(JobQueueBase):
    id: UUID
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class JobQueue(JobQueueInDBBase):
    pass
