from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class GithubInstallationBase(BaseModel):
    installation_id: int
    github_account_id: int
    github_account_username: str
    github_account_type: str
    user_id: UUID

class GithubInstallationCreate(GithubInstallationBase):
    pass

class GithubInstallationUpdate(BaseModel):
    github_account_id: Optional[int] = None
    github_account_username: Optional[str] = None
    github_account_type: Optional[str] = None

class GithubInstallationInDBBase(GithubInstallationBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class GithubInstallation(GithubInstallationInDBBase):
    pass
