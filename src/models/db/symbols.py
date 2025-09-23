from sqlalchemy import Column, String, TIMESTAMP, text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.core.database import Base

class Symbol(Base):
    __tablename__ = 'symbols'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    repository_id = Column(UUID(as_uuid=True), ForeignKey('repositories.id'), nullable=True)
    snapshot_id = Column(UUID(as_uuid=True), ForeignKey('repo_snapshots.id'), nullable=True)
    symbol_name = Column(String, nullable=False)
    symbol_kind = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    span_start_line = Column(Integer, nullable=False)
    span_end_line = Column(Integer, nullable=False)
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    repository = relationship("Repository", back_populates="symbols")
    snapshot = relationship("RepoSnapshot", back_populates="symbols")
    source_edges = relationship("SymbolEdge", foreign_keys="[SymbolEdge.source_symbol_id]", back_populates="source_symbol")
    target_edges = relationship("SymbolEdge", foreign_keys="[SymbolEdge.target_symbol_id]", back_populates="target_symbol")
    embeddings = relationship("SymbolEmbedding", back_populates="symbol")