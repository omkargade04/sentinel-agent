from uuid import UUID
from pydantic import BaseModel, Field
from typing import Optional

class PRFileChangeBase(BaseModel):
    pr_id: UUID
    file_path: str
    change_type: str
    additions: int
    deletions: int
    diff: Optional[str] = None

class PRFileChangeCreate(PRFileChangeBase):
    pass

class PRFileChangeUpdate(BaseModel):
    file_path: Optional[str] = None
    change_type: Optional[str] = None
    additions: Optional[int] = None
    deletions: Optional[int] = None
    diff: Optional[str] = None

class PRFileChangeInDBBase(PRFileChangeBase):
    id: UUID

    class Config:
        orm_mode = True

class PRFileChange(PRFileChangeInDBBase):
    pass
