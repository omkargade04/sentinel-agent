from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class RepoSnapshotBase(BaseModel):
    repository_id: UUID
    commit_sha: str

class RepoSnapshotCreate(RepoSnapshotBase):
    pass

class RepoSnapshotUpdate(BaseModel):
    commit_sha: Optional[str] = None

class RepoSnapshotInDBBase(RepoSnapshotBase):
    id: UUID
    created_at: datetime

    class Config:
        orm_mode = True

class RepoSnapshot(RepoSnapshotInDBBase):
    pass
