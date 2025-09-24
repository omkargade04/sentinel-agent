from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class CredentialsBase(BaseModel):
    user_id: UUID
    access_token: str
    refresh_token: str
    token_expires_at: datetime

class CredentialsCreate(CredentialsBase):
    pass

class CredentialsUpdate(BaseModel):
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None

class CredentialsInDBBase(CredentialsBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class Credentials(CredentialsInDBBase):
    pass
