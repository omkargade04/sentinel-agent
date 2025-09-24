from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List

class GithubCredentialBase(BaseModel):
    installation_id: int
    encrypted_token: str
    token_expires_at: datetime
    scope: List[str]
    credential_type: str = 'installation'
    is_active: bool = True

class GithubCredentialCreate(GithubCredentialBase):
    pass

class GithubCredentialUpdate(BaseModel):
    encrypted_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    scope: Optional[List[str]] = None
    is_active: Optional[bool] = None

class GithubCredentialInDBBase(GithubCredentialBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class GithubCredential(GithubCredentialInDBBase):
    pass
    