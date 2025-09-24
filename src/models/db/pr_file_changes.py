from sqlalchemy import Column, String, Integer, text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.core.database import Base

class PRFileChange(Base):
    __tablename__ = 'pr_file_changes'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    pr_id = Column(UUID(as_uuid=True), ForeignKey('pull_requests.id'), nullable=True)
    file_path = Column(String, nullable=False)
    change_type = Column(String, nullable=False)
    additions = Column(Integer, nullable=False)
    deletions = Column(Integer, nullable=False)
    diff = Column(String)

    pull_request = relationship("PullRequest", back_populates="file_changes")
