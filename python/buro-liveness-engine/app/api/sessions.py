import json
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session as DBSession

from app.core.database import get_db
from app.models.orm import LivenessResult
from app.models.schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    LivenessResultSchema,
    SessionResultResponse,
    VideoUploadResponse,
)
from app.services.processing_service import processing_service
from app.services.session_service import session_service
from app.storage.video_store import video_store

router = APIRouter(prefix="/sessions", tags=["Sessions"])
logger = logging.getLogger(__name__)


@router.post("", response_model=CreateSessionResponse, status_code=201)
def create_session(
    body: CreateSessionRequest,
    db: DBSession = Depends(get_db),
) -> CreateSessionResponse:
    session = session_service.create(db, reference_id=body.reference_id)
    return CreateSessionResponse(
        session_id=session.id,
        challenge=session.get_challenge(),
        expires_at=session.expires_at,
        status=session.status,
    )


@router.post("/{session_id}/video", response_model=VideoUploadResponse, status_code=202)
async def upload_video(
    session_id: str,
    video: UploadFile = File(...),
    db: DBSession = Depends(get_db),
) -> VideoUploadResponse:
    session = session_service.get_or_404(db, session_id)
    session_service.check_expiry(db, session)

    if session.status != "PENDING":
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "SESSION_NOT_PENDING",
                    "message": f"Session is in state '{session.status}'. Only PENDING sessions accept uploads.",
                }
            },
        )

    video_store.validate(video)
    video_path = video_store.save(video)

    session_service.increment_attempt(db, session)
    session_service.transition(db, session, "UPLOADED")

    # Fire-and-forget: runs in threadpool, does not block response
    await processing_service.process_async(session_id, str(video_path))

    return VideoUploadResponse(session_id=session_id, status="PROCESSING")


@router.get("/{session_id}/result", response_model=SessionResultResponse)
def get_result(
    session_id: str,
    db: DBSession = Depends(get_db),
) -> SessionResultResponse:
    session = session_service.get_or_404(db, session_id)
    session_service.check_expiry(db, session)

    if session.status not in {"COMPLETED", "FAILED"}:
        return SessionResultResponse(
            session_id=session_id,
            status=session.status,
            result=None,
        )

    row: LivenessResult | None = (
        db.query(LivenessResult)
        .filter(LivenessResult.session_id == session_id)
        .order_by(LivenessResult.processed_at.desc())
        .first()
    )

    if not row:
        return SessionResultResponse(
            session_id=session_id,
            status=session.status,
            result=None,
        )

    return SessionResultResponse(
        session_id=session_id,
        status=session.status,
        result=LivenessResultSchema(
            verdict=row.verdict,
            confidence=row.confidence,
            reason_codes=row.get_reason_codes(),
            expected_sequence=json.loads(row.expected_sequence),
            detected_sequence=json.loads(row.detected_sequence),
            frame_count=row.frame_count,
            face_detected_frames=row.face_detected_frames,
            video_duration_sec=row.video_duration_sec,
            processed_at=row.processed_at,
        ),
    )
