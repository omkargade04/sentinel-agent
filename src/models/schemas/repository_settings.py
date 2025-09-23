from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any

class RepositorySettingsBase(BaseModel):
    repository_id: UUID
    settings: Dict[str, Any]

class RepositorySettingsCreate(RepositorySettingsBase):
    pass

class RepositorySettingsUpdate(BaseModel):
    settings: Optional[Dict[str, Any]] = None

class RepositorySettingsInDBBase(RepositorySettingsBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class RepositorySettings(RepositorySettingsInDBBase):
    pass
