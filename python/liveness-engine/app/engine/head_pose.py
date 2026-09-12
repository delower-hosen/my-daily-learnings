import logging
from typing import Any

logger = logging.getLogger(__name__)


class HeadPose:
    """
    Heuristic head-pose estimator based on face bounding-box position.

    bbox format: [x, y, w, h]  (OpenCV convention — top-left origin, width/height)

    Logic: compute the face centre as a fraction of frame dimensions.
    Thresholds are intentionally conservative to reduce false positives.

    Limitation: this is positional heuristic, not true 3-D pose estimation.
    Replace with MediaPipe FaceMesh or dlib 68-point landmarks when accuracy
    becomes a priority.
    """

    def classify(self, frame_shape: tuple, bbox: list[int]) -> str:
        frame_h, frame_w = frame_shape[:2]
        x, y, w, h = bbox  # unpack as x, y, width, height

        face_cx = x + w / 2.0   # horizontal centre of face
        face_cy = y + h / 2.0   # vertical centre of face

        x_ratio = face_cx / max(frame_w, 1)
        y_ratio = face_cy / max(frame_h, 1)

        if x_ratio < 0.38:
            return "left"
        if x_ratio > 0.62:
            return "right"
        if y_ratio < 0.38:
            return "up"
        if y_ratio > 0.62:
            return "down"
        return "straight"

    def analyze(
        self,
        frames: list[dict[str, Any]],
        detections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        detection_map = {d["frame_index"]: d for d in detections}
        results = []

        for frame_item in frames:
            idx = frame_item["frame_index"]
            det = detection_map.get(idx)

            if not det or not det["face_found"] or det["bbox"] is None:
                results.append({"frame_index": idx, "direction": None})
                continue

            direction = self.classify(frame_item["image"].shape, det["bbox"])
            results.append({"frame_index": idx, "direction": direction})

        return results

    def compress(self, directions: list[str | None]) -> list[str]:
        """Collapse consecutive duplicate directions into one."""
        compressed: list[str] = []
        prev = None
        for d in directions:
            if d and d != prev:
                compressed.append(d)
                prev = d
        return compressed
