from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class GitHubAccount(BaseModel):
    id: int
    login: str
    type: str

class GitHubRepository(BaseModel):
    id: int
    name: str
    full_name: str
    private: bool
    owner: GitHubAccount
    language: Optional[str] = None
    default_branch: str

class GitHubInstallation(BaseModel):
    id: int
    account: GitHubAccount
    repository_selection: str
    
class InstallationEvent(BaseModel):
    action: str
    installation: GitHubInstallation
    repositories: Optional[List[GitHubRepository]] = None
    repositories_added: Optional[List[GitHubRepository]] = None
    repositories_removed: Optional[List[GitHubRepository]] = None

# Schema for database representation
class Installation(BaseModel):
    id: UUID
    user_id: Optional[UUID] = None
    installation_id: int
    github_account_id: int
    github_account_type: str
    github_account_username: str
    is_active: bool

    class Config:
        orm_mode = True
        from_attributes = True
