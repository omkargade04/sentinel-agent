from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List

class SymbolEmbeddingBase(BaseModel):
    snapshot_id: UUID
    symbol_id: UUID
    embedding: List[float]

class SymbolEmbeddingCreate(SymbolEmbeddingBase):
    pass

class SymbolEmbeddingUpdate(BaseModel):
    embedding: Optional[List[float]] = None

class SymbolEmbeddingInDBBase(SymbolEmbeddingBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class SymbolEmbedding(SymbolEmbeddingInDBBase):
    pass
