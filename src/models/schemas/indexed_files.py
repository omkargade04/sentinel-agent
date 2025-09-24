from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class IndexedFileBase(BaseModel):
    repository_id: UUID
    snapshot_id: UUID
    file_path: str
    language: str

class IndexedFileCreate(IndexedFileBase):
    pass

class IndexedFileUpdate(BaseModel):
    file_path: Optional[str] = None
    language: Optional[str] = None

class IndexedFileInDBBase(IndexedFileBase):
    id: UUID
    indexed_at: datetime

    class Config:
        orm_mode = True

class IndexedFile(IndexedFileInDBBase):
    pass
