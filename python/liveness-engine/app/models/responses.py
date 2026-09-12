from typing import List, Optional
from pydantic import BaseModel


class ReasonItem(BaseModel):
    code: str
    message: str


class LivenessAnalyzeResponse(BaseModel):
    success: bool
    session_id: str
    member_id: Optional[str] = None
    is_live: bool
    confidence: float
    decision: str
    expected_sequence: List[str]
    detected_sequence: List[str]
    frame_count: int
    face_detected_frames: int
    reasons: List[ReasonItem]
    metadata: dict