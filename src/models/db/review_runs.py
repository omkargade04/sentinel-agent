from sqlalchemy import Column, String, TIMESTAMP, text, ForeignKey, BigInteger, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.core.database import Base

class ReviewRun(Base):
    __tablename__ = 'review_runs'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    pr_id = Column(UUID(as_uuid=True), ForeignKey('pull_requests.id'), nullable=True)
    llm_model = Column(String)
    head_sha = Column(String)
    snapshot_id = Column(UUID(as_uuid=True), ForeignKey('repo_snapshots.id'), nullable=True)
    started_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    completed_at = Column(TIMESTAMP)
    status = Column(String, default='pending')
    error_message = Column(String)

    # PR review metadata persistence columns
    temporal_workflow_id = Column(String(255), nullable=True)
    github_review_id = Column(BigInteger, nullable=True)
    published = Column(Boolean, nullable=False, server_default=text('false'))

    pull_request = relationship("PullRequest", back_populates="review_runs")
    snapshot = relationship("RepoSnapshot", back_populates="review_runs")
    findings = relationship("ReviewFinding", back_populates="review_run")
