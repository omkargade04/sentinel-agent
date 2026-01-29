from sqlalchemy import Column, String, TIMESTAMP, text, ForeignKey, BigInteger, Integer, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from src.core.database import Base


class WorkflowRunEvent(Base):
    """
    Stores workflow progress events emitted by Temporal activities.

    This table serves as an event store for SSE streaming and audit trail.
    Activities emit events during execution, and the SSE endpoint polls this
    table to stream real-time updates to the frontend.

    Key design decisions:
    - sequence_number provides ordering and reconnection support
    - metadata JSONB allows activity-specific data (file counts, SHAs, etc.)
    - user_id enables authorization checks in SSE endpoint
    - workflow_type supports future expansion (pr_review, etc.)
    """
    __tablename__ = 'workflow_run_events'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))

    # Workflow identification
    workflow_id = Column(String(255), nullable=False, index=True)
    workflow_run_id = Column(String(255), nullable=False)
    workflow_type = Column(String(100), nullable=False)

    # Security/ownership context
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.user_id'), nullable=True)
    installation_id = Column(BigInteger, nullable=True)
    repo_id = Column(UUID(as_uuid=True), ForeignKey('repositories.id'), nullable=True)

    # Event ordering (monotonic counter per workflow)
    sequence_number = Column(Integer, nullable=False)

    # Event content
    activity_name = Column(String(100), nullable=True)
    event_type = Column(String(50), nullable=False)
    message = Column(String, nullable=False)
    metadata = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    # Timestamp
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    # Relationships
    user = relationship("User", back_populates="workflow_events")
    repository = relationship("Repository", back_populates="workflow_events")

    # Constraints and indexes
    __table_args__ = (
        # Unique constraint ensures no duplicate sequence numbers per workflow
        Index('unique_workflow_sequence', 'workflow_id', 'sequence_number', unique=True),
        # Composite index for efficient SSE queries
        Index('idx_workflow_events_workflow', 'workflow_id', 'sequence_number'),
        # Index for user queries (audit trail, user dashboards)
        Index('idx_workflow_events_user', 'user_id', 'created_at'),
    )
