from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── Requests ──────────────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    reference_id: Optional[str] = Field(None, min_length=1, max_length=128)


# ── Responses ─────────────────────────────────────────────────────────────────

class CreateSessionResponse(BaseModel):
    session_id: str
    challenge: list[str]
    expires_at: datetime
    status: str


class VideoUploadResponse(BaseModel):
    session_id: str
    status: str


class LivenessResultSchema(BaseModel):
    verdict: str
    confidence: float
    reason_codes: list[str]
    expected_sequence: list[str]
    detected_sequence: list[str]
    frame_count: int
    face_detected_frames: int
    video_duration_sec: Optional[float]
    processed_at: datetime


class SessionResultResponse(BaseModel):
    session_id: str
    status: str
    result: Optional[LivenessResultSchema] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


# ── Error envelope ────────────────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
