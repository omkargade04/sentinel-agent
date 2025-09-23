from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class PullRequestBase(BaseModel):
    repository_id: UUID
    pr_number: int
    author_github_id: int
    title: str
    body: Optional[str] = None
    base_branch: Optional[str] = None
    head_branch: Optional[str] = None
    base_sha: Optional[str] = None
    head_sha: Optional[str] = None
    state: str = 'open'
    merged_at: Optional[datetime] = None

class PullRequestCreate(PullRequestBase):
    pass

class PullRequestUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    base_branch: Optional[str] = None
    head_branch: Optional[str] = None
    base_sha: Optional[str] = None
    head_sha: Optional[str] = None
    state: Optional[str] = None
    merged_at: Optional[datetime] = None

class PullRequestInDBBase(PullRequestBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class PullRequest(PullRequestInDBBase):
    pass
