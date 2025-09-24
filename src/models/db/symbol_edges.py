from sqlalchemy import Column, String, TIMESTAMP, text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.core.database import Base

class SymbolEdge(Base):
    __tablename__ = 'symbol_edges'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    snapshot_id = Column(UUID(as_uuid=True), ForeignKey('repo_snapshots.id'), nullable=True)
    source_symbol_id = Column(UUID(as_uuid=True), ForeignKey('symbols.id'), nullable=True)
    target_symbol_id = Column(UUID(as_uuid=True), ForeignKey('symbols.id'), nullable=True)
    edge_type = Column(String, nullable=False)
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    snapshot = relationship("RepoSnapshot", back_populates="symbol_edges")
    source_symbol = relationship("Symbol", foreign_keys=[source_symbol_id], back_populates="source_edges")
    target_symbol = relationship("Symbol", foreign_keys=[target_symbol_id], back_populates="target_edges")