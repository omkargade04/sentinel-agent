from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class RepositoryBase(BaseModel):
    installation_id: int
    github_repo_id: int
    github_repo_name: str
    full_name: str
    default_branch: str
    private: bool = False

class RepoRequest(RepositoryBase):
    pass

class RepositoryCreate(RepositoryBase):
    pass

class RepositoryUpdate(BaseModel):
    github_repo_name: Optional[str] = None
    full_name: Optional[str] = None
    default_branch: Optional[str] = None
    private: Optional[bool] = None
    last_synced_at: Optional[datetime] = None

class RepositoryInDBBase(RepositoryBase):
    id: UUID
    last_synced_at: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class Repository(RepositoryInDBBase):
    pass