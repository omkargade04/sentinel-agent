from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class SymbolEdgeBase(BaseModel):
    snapshot_id: UUID
    source_symbol_id: UUID
    target_symbol_id: UUID
    edge_type: str

class SymbolEdgeCreate(SymbolEdgeBase):
    pass

class SymbolEdgeUpdate(BaseModel):
    edge_type: Optional[str] = None

class SymbolEdgeInDBBase(SymbolEdgeBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class SymbolEdge(SymbolEdgeInDBBase):
    pass