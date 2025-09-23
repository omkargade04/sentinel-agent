from sqlalchemy import Column, String, TIMESTAMP, text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.core.database import Base

class IndexedFile(Base):
    __tablename__ = 'indexed_files'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    repository_id = Column(UUID(as_uuid=True), ForeignKey('repositories.id'), nullable=True)
    snapshot_id = Column(UUID(as_uuid=True), ForeignKey('repo_snapshots.id'), nullable=True)
    file_path = Column(String, nullable=False)
    language = Column(String, nullable=False)
    indexed_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    repository = relationship("Repository", back_populates="indexed_files")
    snapshot = relationship("RepoSnapshot", back_populates="indexed_files")
