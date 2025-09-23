from sqlalchemy import Column, String, TIMESTAMP, text, ForeignKey, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.core.database import Base

class GithubInstallation(Base):
    __tablename__ = 'github_installations'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    installation_id = Column(BigInteger, nullable=False, unique=True)
    github_account_id = Column(BigInteger, nullable=False)
    github_account_type = Column(String(255), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.user_id'), nullable=False)
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    user = relationship("User", back_populates="github_installations")
    github_credentials = relationship("GithubCredential", back_populates="installation")
    repositories = relationship("Repository", back_populates="installation")