from sqlalchemy import Column, String, TIMESTAMP, text, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from src.core.database import Base

class JobQueue(Base):
    __tablename__ = 'job_queue'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    job_type = Column(String, nullable=False)
    status = Column(String, default='pending')
    payload = Column(JSONB, nullable=False)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    started_at = Column(TIMESTAMP)
    completed_at = Column(TIMESTAMP)
    error_message = Column(String)
