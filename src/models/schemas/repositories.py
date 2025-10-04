from uuid import UUID
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class RepositoryBase(BaseModel):
    id: int
    name: str
    full_name: str
    private: bool
    owner: dict
    language: Optional[str] = None
    default_branch: str

class RepositoryCreate(BaseModel):
    installation_id: UUID
    github_repo_id: int
    name: str
    full_name: str
    private: bool
    owner: str
    language: Optional[str] = None
    default_branch: str

class RepositoryRead(BaseModel):
    id: UUID
    github_repo_id: int
    full_name: str
    private: bool
    owner: str
    language: Optional[str] = None
    default_branch: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True