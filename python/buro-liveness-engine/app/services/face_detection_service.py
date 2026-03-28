from typing import List, Dict, Any
import cv2
import os


class FaceDetectionService:
    def __init__(self):
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if not os.path.exists(cascade_path):
            raise FileNotFoundError("OpenCV Haar cascade file not found")

        self.face_cascade = cv2.CascadeClassifier(cascade_path)

    def detect_face(self, frame) -> Dict[str, Any] | None:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(60, 60)
        )

        if len(faces) == 0:
            return None

        x, y, w, h = max(faces, key=lambda item: item[2] * item[3])
        return {
            "bbox": [int(x), int(y), int(x + w), int(y + h)],
            "confidence": 1.0,
            "area": int(w * h)
        }

    def detect_faces(self, frames: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        for item in frames:
            frame = item["image"]
            frame_index = item["frame_index"]
            detection = self.detect_face(frame)

            results.append({
                "frame_index": frame_index,
                "face_found": detection is not None,
                "detection": detection
            })

        return results

    def validate_face_presence(self, detections: List[Dict[str, Any]], minimum_ratio: float = 0.5) -> bool:
        if not detections:
            return False

        face_count = sum(1 for item in detections if item["face_found"])
        ratio = face_count / len(detections)
        return ratio >= minimum_ratio