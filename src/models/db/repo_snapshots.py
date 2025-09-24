from sqlalchemy import Column, String, TIMESTAMP, text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.core.database import Base

class RepoSnapshot(Base):
    __tablename__ = 'repo_snapshots'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    repository_id = Column(UUID(as_uuid=True), ForeignKey('repositories.id'), nullable=True)
    commit_sha = Column(String, nullable=False)
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    repository = relationship("Repository", back_populates="snapshots")
    indexed_files = relationship("IndexedFile", back_populates="snapshot")
    symbols = relationship("Symbol", back_populates="snapshot")
    symbol_edges = relationship("SymbolEdge", back_populates="snapshot")
    symbol_embeddings = relationship("SymbolEmbedding", back_populates="snapshot")
    review_runs = relationship("ReviewRun", back_populates="snapshot")