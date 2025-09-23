from sqlalchemy import Column, String, TIMESTAMP, text, ForeignKey, BigInteger, Boolean
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from src.core.database import Base

class GithubCredential(Base):
    __tablename__ = 'github_credentials'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    installation_id = Column(BigInteger, ForeignKey('github_installations.installation_id'), nullable=False)
    credential_type = Column(String, default='installation')
    encrypted_token = Column(String, nullable=False)
    token_expires_at = Column(TIMESTAMP, nullable=False)
    scope = Column(ARRAY(String))
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    installation = relationship("GithubInstallation", back_populates="github_credentials")