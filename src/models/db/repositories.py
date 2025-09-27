from sqlalchemy import Column, String, TIMESTAMP, text, ForeignKey, BigInteger, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.core.database import Base

class Repository(Base):
    __tablename__ = 'repositories'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    installation_id = Column(BigInteger, ForeignKey('github_installations.installation_id'), nullable=False)
    github_repo_id = Column(BigInteger, nullable=False)
    github_repo_name = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    default_branch = Column(String(255), nullable=False)
    private = Column(Boolean, default=False)
    last_synced_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    installation = relationship("GithubInstallation", back_populates="repositories")
    snapshots = relationship("RepoSnapshot", back_populates="repository")
    indexed_files = relationship("IndexedFile", back_populates="repository")
    symbols = relationship("Symbol", back_populates="repository")
    automation_workflows = relationship("AutomationWorkflow", back_populates="repository")
    pull_requests = relationship("PullRequest", back_populates="repository")