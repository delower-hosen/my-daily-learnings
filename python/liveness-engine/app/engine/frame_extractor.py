import logging
from typing import Any

import cv2

logger = logging.getLogger(__name__)


class FrameExtractor:
    def extract(
        self,
        video_path: str,
        every_n_frames: int = 5,
        max_frames: int = 60,
    ) -> list[dict[str, Any]]:
        capture = cv2.VideoCapture(video_path)
        if not capture.isOpened():
            raise ValueError(f"Could not open video: {video_path}")

        frames: list[dict[str, Any]] = []
        frame_index = 0
        kept = 0

        while True:
            success, frame = capture.read()
            if not success:
                break
            if frame_index % every_n_frames == 0:
                frames.append({"frame_index": frame_index, "image": frame})
                kept += 1
                if kept >= max_frames:
                    break
            frame_index += 1

        capture.release()
        logger.debug("Extracted %d frames from %s", len(frames), video_path)
        return frames

    def get_metadata(self, video_path: str) -> dict[str, Any]:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video for metadata: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = (total_frames / fps) if fps > 0 else 0.0
        cap.release()

        return {
            "fps": round(float(fps), 2),
            "frame_count": total_frames,
            "width": width,
            "height": height,
            "duration_seconds": round(float(duration), 2),
        }
