from sqlalchemy import Column, String, TIMESTAMP, text, ForeignKey, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.core.database import Base

class PullRequest(Base):
    __tablename__ = 'pull_requests'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    repository_id = Column(UUID(as_uuid=True), ForeignKey('repositories.id'), nullable=True)
    pr_number = Column(BigInteger, nullable=False)
    author_github_id = Column(BigInteger, nullable=False)
    title = Column(String, nullable=False)
    body = Column(String)
    base_branch = Column(String)
    head_branch = Column(String)
    base_sha = Column(String)
    head_sha = Column(String)
    state = Column(String, default='open')
    merged_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    repository = relationship("Repository", back_populates="pull_requests")
    file_changes = relationship("PRFileChange", back_populates="pull_request")
    review_runs = relationship("ReviewRun", back_populates="pull_request")