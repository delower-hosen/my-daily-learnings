import shutil
import uuid
from pathlib import Path
import cv2


class VideoIntakeService:
    def __init__(self, upload_dir: str = "app/uploads"):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def save_upload(self, file_obj, original_name: str) -> Path:
        extension = Path(original_name).suffix or ".mp4"
        file_name = f"{uuid.uuid4()}{extension}"
        file_path = self.upload_dir / file_name

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file_obj, buffer)

        return file_path

    def get_video_metadata(self, video_path: str) -> dict:
        capture = cv2.VideoCapture(video_path)

        if not capture.isOpened():
            raise ValueError("Could not open video")

        fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration_seconds = (frame_count / fps) if fps and fps > 0 else 0.0

        capture.release()

        return {
            "fps": round(float(fps), 2),
            "frame_count": frame_count,
            "width": width,
            "height": height,
            "duration_seconds": round(float(duration_seconds), 2)
        }