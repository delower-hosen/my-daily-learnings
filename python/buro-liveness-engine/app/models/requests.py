from typing import List, Optional
from pydantic import BaseModel, Field


class LivenessAnalyzeRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    expected_sequence: List[str] = Field(default_factory=list)
    member_id: Optional[str] = None