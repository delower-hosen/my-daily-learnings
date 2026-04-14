import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session as DBSession

from app.core.database import SessionLocal
from app.models.orm import LivenessResult, Session
from app.services.session_service import session_service

logger = logging.getLogger(__name__)

# One shared executor — limits concurrent video processing jobs
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="liveness-proc")


class ProcessingService:
    def __init__(self) -> None:
        # Lazy-init the engine so models load once at startup, not per request
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from app.engine.liveness_engine import LivenessEngine
            self._engine = LivenessEngine()
        return self._engine

    async def process_async(self, session_id: str, video_path: str) -> None:
        """
        Fire-and-forget: runs sync processing in threadpool.
        Opens its own DB session (safe across threads).
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            _executor,
            self._process_sync,
            session_id,
            video_path,
        )

    def _process_sync(self, session_id: str, video_path: str) -> None:
        """Runs in a worker thread. Opens its own DB session."""
        db: DBSession = SessionLocal()
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if not session:
                logger.error("Processing: session %s not found", session_id)
                return

            session_service._transition(db, session, "PROCESSING")

            engine = self._get_engine()
            raw = engine.analyze(
                video_path=video_path,
                expected_sequence=session.get_challenge(),
            )

            result = LivenessResult(
                session_id=session_id,
                verdict=raw["verdict"],
                confidence=raw["confidence"],
                reason_codes=json.dumps(raw["reason_codes"]),
                expected_sequence=json.dumps(raw["expected_sequence"]),
                detected_sequence=json.dumps(raw["detected_sequence"]),
                frame_count=raw["frame_count"],
                face_detected_frames=raw["face_detected_frames"],
                video_path=video_path,
                video_duration_sec=raw.get("video_duration_sec"),
                processing_error=None,
                processed_at=datetime.now(timezone.utc),
            )
            db.add(result)
            session_service._transition(db, session, "COMPLETED")
            db.commit()

            logger.info(
                "Session %s processed: verdict=%s confidence=%.4f",
                session_id, raw["verdict"], raw["confidence"],
            )

        except Exception as exc:
            logger.exception("Processing failed for session %s: %s", session_id, exc)
            db.rollback()
            try:
                # Write a failed result so the client gets a meaningful response
                session = db.query(Session).filter(Session.id == session_id).first()
                if session:
                    result = LivenessResult(
                        session_id=session_id,
                        verdict="FAIL",
                        confidence=0.0,
                        reason_codes=json.dumps(["PROCESSING_ERROR"]),
                        expected_sequence=session.challenge,
                        detected_sequence=json.dumps([]),
                        frame_count=0,
                        face_detected_frames=0,
                        video_path=video_path,
                        processing_error=str(exc),
                        processed_at=datetime.now(timezone.utc),
                    )
                    db.add(result)
                    session_service._transition(db, session, "FAILED")
                    db.commit()
            except Exception:
                logger.exception("Could not write failure record for session %s", session_id)
        finally:
            db.close()


processing_service = ProcessingService()
