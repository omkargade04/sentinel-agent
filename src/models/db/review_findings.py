from sqlalchemy import Column, String, TIMESTAMP, text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.core.database import Base

class ReviewFinding(Base):
    __tablename__ = 'review_findings'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    review_run_id = Column(UUID(as_uuid=True), ForeignKey('review_runs.id'), nullable=True)
    file_path = Column(String, nullable=False)
    line_number = Column(Integer, nullable=False)
    finding_type = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    message = Column(String, nullable=False)
    suggestion = Column(String)
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    review_run = relationship("ReviewRun", back_populates="findings")
