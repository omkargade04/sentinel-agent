from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class ReviewFindingBase(BaseModel):
    review_run_id: UUID
    file_path: str
    line_number: int
    finding_type: str
    severity: str
    message: str
    suggestion: Optional[str] = None

class ReviewFindingCreate(ReviewFindingBase):
    pass

class ReviewFindingUpdate(BaseModel):
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    finding_type: Optional[str] = None
    severity: Optional[str] = None
    message: Optional[str] = None
    suggestion: Optional[str] = None

class ReviewFindingInDBBase(ReviewFindingBase):
    id: UUID
    created_at: datetime

    class Config:
        orm_mode = True

class ReviewFinding(ReviewFindingInDBBase):
    pass
