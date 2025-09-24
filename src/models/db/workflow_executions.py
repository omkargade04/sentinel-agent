from sqlalchemy import Column, String, TIMESTAMP, text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.core.database import Base

class WorkflowExecution(Base):
    __tablename__ = 'workflow_executions'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    workflow_id = Column(UUID(as_uuid=True), ForeignKey('automation_workflows.id'), nullable=True)
    status = Column(String)
    error_message = Column(String)
    started_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    completed_at = Column(TIMESTAMP)

    workflow = relationship("AutomationWorkflow", back_populates="executions")
