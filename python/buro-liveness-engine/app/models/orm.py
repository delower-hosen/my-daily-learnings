import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Float, DateTime, Text, ForeignKey
from sqlalchemy.orm import DeclarativeBase


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    id            = Column(String, primary_key=True, default=_uuid)
    reference_id  = Column(String, nullable=True)
    challenge     = Column(Text, nullable=False)           # JSON array string
    status        = Column(String, nullable=False, default="PENDING")
    attempt_count = Column(Integer, nullable=False, default=0)
    created_at    = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at    = Column(DateTime(timezone=True), nullable=False)
    updated_at    = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    def get_challenge(self) -> list[str]:
        return json.loads(self.challenge)

    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        exp = self.expires_at
        # SQLite returns naive datetimes; treat them as UTC
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return now >= exp

    def is_terminal(self) -> bool:
        return self.status in {"COMPLETED", "EXPIRED", "FAILED"}


class LivenessResult(Base):
    __tablename__ = "liveness_results"

    id                   = Column(String, primary_key=True, default=_uuid)
    session_id           = Column(String, ForeignKey("sessions.id"), nullable=False)
    verdict              = Column(String, nullable=False)   # PASS | FAIL | REVIEW
    confidence           = Column(Float, nullable=False)
    reason_codes         = Column(Text, nullable=False)     # JSON array string
    expected_sequence    = Column(Text, nullable=False)     # JSON array string
    detected_sequence    = Column(Text, nullable=False)     # JSON array string
    frame_count          = Column(Integer, nullable=False)
    face_detected_frames = Column(Integer, nullable=False)
    video_path           = Column(String, nullable=True)
    video_duration_sec   = Column(Float, nullable=True)
    processing_error     = Column(Text, nullable=True)
    processed_at         = Column(DateTime(timezone=True), nullable=False, default=_now)

    def get_reason_codes(self) -> list[str]:
        return json.loads(self.reason_codes)
