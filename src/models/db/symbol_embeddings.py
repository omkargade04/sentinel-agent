from sqlalchemy import Column, TIMESTAMP, text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from src.core.database import Base

class SymbolEmbedding(Base):
    __tablename__ = 'symbol_embeddings'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    snapshot_id = Column(UUID(as_uuid=True), ForeignKey('repo_snapshots.id'), nullable=True)
    symbol_id = Column(UUID(as_uuid=True), ForeignKey('symbols.id'), nullable=True)
    embedding = Column(Vector(1536))
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    snapshot = relationship("RepoSnapshot", back_populates="symbol_embeddings")
    symbol = relationship("Symbol", back_populates="embeddings")