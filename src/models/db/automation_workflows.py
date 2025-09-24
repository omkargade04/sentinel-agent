from sqlalchemy import Column, String, TIMESTAMP, text, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from src.core.database import Base

class AutomationWorkflow(Base):
    __tablename__ = 'automation_workflows'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    repository_id = Column(UUID(as_uuid=True), ForeignKey('repositories.id'), nullable=True)
    name = Column(String)
    trigger_event = Column(String)
    actions = Column(JSONB)
    is_enabled = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    repository = relationship("Repository", back_populates="automation_workflows")
    executions = relationship("WorkflowExecution", back_populates="workflow")
