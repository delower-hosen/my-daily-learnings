import logging
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile, HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)


class VideoStore:
    def __init__(self) -> None:
        self.upload_dir = settings.upload_dir
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def validate(self, file: UploadFile) -> None:
        """Raise HTTPException if file fails basic validation."""
        ext = Path(file.filename or "").suffix.lower()
        if ext not in settings.allowed_extensions:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": {
                        "code": "INVALID_FILE_TYPE",
                        "message": f"File type '{ext}' not allowed. Accepted: {settings.allowed_extensions}",
                    }
                },
            )

    def save(self, file: UploadFile) -> Path:
        """Save uploaded file to disk. Returns absolute path."""
        ext = Path(file.filename or "upload.mp4").suffix.lower() or ".mp4"
        filename = f"{uuid.uuid4()}{ext}"
        dest = self.upload_dir / filename

        try:
            with open(dest, "wb") as buf:
                shutil.copyfileobj(file.file, buf)
        except Exception as exc:
            logger.exception("Failed to write video to disk: %s", exc)
            raise HTTPException(status_code=500, detail={"error": {"code": "STORAGE_ERROR", "message": "Could not save uploaded file."}})

        # Enforce size limit after write (simpler than streaming check)
        size = dest.stat().st_size
        if size > settings.max_upload_bytes:
            dest.unlink(missing_ok=True)
            raise HTTPException(
                status_code=413,
                detail={
                    "error": {
                        "code": "FILE_TOO_LARGE",
                        "message": f"File size {size} bytes exceeds limit of {settings.max_upload_bytes} bytes.",
                    }
                },
            )

        logger.info("Saved video: %s (%d bytes)", dest, size)
        return dest

    def delete(self, path: str) -> None:
        """Delete a video file. Silent if already gone."""
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            logger.warning("Could not delete video file: %s", path)


video_store = VideoStore()
