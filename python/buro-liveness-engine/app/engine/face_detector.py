import logging
import os
from typing import Any

import cv2

from app.core.config import settings

logger = logging.getLogger(__name__)

_HARD_FAIL_CODES = {
    "NO_FRAMES",
    "FACE_MISSING",
    "MULTIPLE_FACES",
    "ANTI_SPOOF_FAILED",
    "SEQUENCE_MISMATCH",
    "VIDEO_TOO_SHORT",
    "CHALLENGE_MISSING",
}


class FaceDetector:
    def __init__(self) -> None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if not os.path.exists(cascade_path):
            raise FileNotFoundError(f"Haar cascade not found at: {cascade_path}")
        self.cascade = cv2.CascadeClassifier(cascade_path)

    def detect(self, frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Detect faces in each frame. Returns one result dict per frame."""
        results = []
        for item in frames:
            frame = item["image"]
            frame_index = item["frame_index"]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            faces = self.cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(60, 60),
            )

            if len(faces) == 0:
                results.append({
                    "frame_index": frame_index,
                    "face_found": False,
                    "face_count": 0,
                    "bbox": None,
                    "area": 0,
                })
            else:
                # Pick the largest face as primary
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                results.append({
                    "frame_index": frame_index,
                    "face_found": True,
                    "face_count": len(faces),
                    # bbox stored as [x, y, w, h] — OpenCV convention
                    "bbox": [int(x), int(y), int(w), int(h)],
                    "area": int(w * h),
                })

        return results

    def face_presence_ratio(self, detections: list[dict[str, Any]]) -> float:
        if not detections:
            return 0.0
        found = sum(1 for d in detections if d["face_found"])
        return found / len(detections)

    def multiple_faces_detected(self, detections: list[dict[str, Any]]) -> bool:
        """True if more than one face appeared in any frame."""
        return any(d.get("face_count", 0) > 1 for d in detections)
