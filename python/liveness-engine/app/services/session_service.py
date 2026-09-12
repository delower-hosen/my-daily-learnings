import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.orm import Session
from app.services.challenge_service import challenge_service

logger = logging.getLogger(__name__)


class SessionService:
    def create(self, db: DBSession, reference_id: Optional[str] = None) -> Session:
        challenge = challenge_service.generate()
        now = datetime.now(timezone.utc)

        session = Session(
            reference_id=reference_id,
            challenge=json.dumps(challenge),
            status="PENDING",
            attempt_count=0,
            created_at=now,
            expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
            updated_at=now,
        )

        db.add(session)
        db.commit()
        db.refresh(session)

        logger.info("Session created: %s (ref=%s)", session.id, reference_id)
        return session

    def get(self, db: DBSession, session_id: str) -> Optional[Session]:
        return db.query(Session).filter(Session.id == session_id).first()

    def get_or_404(self, db: DBSession, session_id: str) -> Session:
        from fastapi import HTTPException
        session = self.get(db, session_id)
        if not session:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "SESSION_NOT_FOUND", "message": f"Session '{session_id}' not found."}},
            )
        return session

    def check_expiry(self, db: DBSession, session: Session) -> Session:
        """Lazily mark expired sessions. Returns the session (possibly now EXPIRED)."""
        from fastapi import HTTPException
        if not session.is_terminal() and session.is_expired():
            self._transition(db, session, "EXPIRED")
            raise HTTPException(
                status_code=410,
                detail={"error": {"code": "SESSION_EXPIRED", "message": "This session has expired."}},
            )
        return session

    def transition(self, db: DBSession, session: Session, new_status: str) -> Session:
        return self._transition(db, session, new_status)

    def _transition(self, db: DBSession, session: Session, new_status: str) -> Session:
        old = session.status
        session.status = new_status
        session.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(session)
        logger.info("Session %s: %s → %s", session.id, old, new_status)
        return session

    def increment_attempt(self, db: DBSession, session: Session) -> Session:
        session.attempt_count += 1
        session.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(session)
        return session


session_service = SessionService()
