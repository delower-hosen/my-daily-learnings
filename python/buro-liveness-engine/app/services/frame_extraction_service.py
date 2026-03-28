from typing import List, Dict, Any
import cv2
import numpy as np


class FrameExtractionService:
    def extract_frames(self, video_path: str, every_n_frames: int = 5, max_frames: int = 60) -> List[Dict[str, Any]]:
        capture = cv2.VideoCapture(video_path)

        if not capture.isOpened():
            raise ValueError("Could not open video for frame extraction")

        frames: List[Dict[str, Any]] = []
        frame_index = 0
        kept = 0

        while True:
            success, frame = capture.read()
            if not success:
                break

            if frame_index % every_n_frames == 0:
                frames.append({
                    "frame_index": frame_index,
                    "image": frame
                })
                kept += 1

                if kept >= max_frames:
                    break

            frame_index += 1

        capture.release()
        return frames

    def resize_frame(self, frame: np.ndarray, max_width: int = 720) -> np.ndarray:
        height, width = frame.shape[:2]
        if width <= max_width:
            return frame

        ratio = max_width / float(width)
        new_height = int(height * ratio)
        return cv2.resize(frame, (max_width, new_height))