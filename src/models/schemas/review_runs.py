from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class ReviewRunBase(BaseModel):
    pr_id: UUID
    llm_model: Optional[str] = None
    head_sha: Optional[str] = None
    snapshot_id: Optional[UUID] = None
    status: str = 'pending'
    error_message: Optional[str] = None

class ReviewRunCreate(ReviewRunBase):
    pass

class ReviewRunUpdate(BaseModel):
    llm_model: Optional[str] = None
    head_sha: Optional[str] = None
    snapshot_id: Optional[UUID] = None
    status: Optional[str] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

class ReviewRunInDBBase(ReviewRunBase):
    id: UUID
    started_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class ReviewRun(ReviewRunInDBBase):
    pass
