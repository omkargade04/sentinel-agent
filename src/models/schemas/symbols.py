from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class SymbolBase(BaseModel):
    repository_id: UUID
    snapshot_id: UUID
    symbol_name: str
    symbol_kind: str
    file_path: str
    span_start_line: int
    span_end_line: int

class SymbolCreate(SymbolBase):
    pass

class SymbolUpdate(BaseModel):
    symbol_name: Optional[str] = None
    symbol_kind: Optional[str] = None
    file_path: Optional[str] = None
    span_start_line: Optional[int] = None
    span_end_line: Optional[int] = None

class SymbolInDBBase(SymbolBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class Symbol(SymbolInDBBase):
    pass