from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any

class AutomationWorkflowBase(BaseModel):
    repository_id: UUID
    name: Optional[str] = None
    trigger_event: Optional[str] = None
    actions: Optional[Dict[str, Any]] = None
    is_enabled: bool = True

class AutomationWorkflowCreate(AutomationWorkflowBase):
    pass

class AutomationWorkflowUpdate(BaseModel):
    name: Optional[str] = None
    trigger_event: Optional[str] = None
    actions: Optional[Dict[str, Any]] = None
    is_enabled: Optional[bool] = None

class AutomationWorkflowInDBBase(AutomationWorkflowBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class AutomationWorkflow(AutomationWorkflowInDBBase):
    pass
