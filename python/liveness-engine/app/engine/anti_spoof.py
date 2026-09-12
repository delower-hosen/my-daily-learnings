import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.core.config import settings
from vendor.silent_face.src.anti_spoof_predict import AntiSpoofPredict

logger = logging.getLogger(__name__)


class AntiSpoof:
    def __init__(self) -> None:
        self.predictor = AntiSpoofPredict(device_id=settings.anti_spoof_device_id)

        model_dir = Path("vendor/silent_face/resources/anti_spoof_models")
        self.model_paths = [str(p) for p in model_dir.glob("*.pth")]

        if not self.model_paths:
            raise RuntimeError(f"No anti-spoof model files found in {model_dir}")

        logger.info("AntiSpoof loaded %d model(s)", len(self.model_paths))

    def _crop(self, frame: np.ndarray, bbox: list[int]) -> np.ndarray | None:
        x, y, w, h = bbox
        x, y = max(0, int(x)), max(0, int(y))
        w, h = max(1, int(w)), max(1, int(h))
        x2 = min(frame.shape[1], x + w)
        y2 = min(frame.shape[0], y + h)

        if x >= x2 or y >= y2:
            return None

        crop = frame[y:y2, x:x2]
        return crop if crop.size > 0 else None

    def score_face(self, crop: np.ndarray) -> float:
        if crop is None or crop.size == 0:
            return 0.0
        if len(crop.shape) != 3 or crop.shape[2] != 3:
            return 0.0
        h, w = crop.shape[:2]
        if h < 20 or w < 20:
            return 0.0

        scores: list[float] = []
        for model_path in self.model_paths:
            try:
                resized = cv2.resize(crop, (80, 80))
                prediction = self.predictor.predict(resized, model_path)
                if prediction is None or prediction.shape != (1, 2):
                    continue
                scores.append(float(prediction[0][1]))
            except Exception:
                logger.warning("Silent-Face prediction failed for model %s", model_path, exc_info=True)

        return float(np.mean(scores)) if scores else 0.0

    def score_video(
        self,
        frames: list[dict[str, Any]],
        detections: list[dict[str, Any]],
        sample_step: int = 5,
    ) -> dict[str, Any]:
        if not frames:
            return {"score": 0.0, "evaluated_frames": 0, "frame_scores": []}

        scores: list[float] = []
        for i in range(0, min(len(frames), len(detections)), sample_step):
            det = detections[i]
            if not det.get("face_found") or det.get("bbox") is None:
                continue
            crop = self._crop(frames[i]["image"], det["bbox"])
            if crop is not None:
                scores.append(self.score_face(crop))

        if not scores:
            return {"score": 0.0, "evaluated_frames": 0, "frame_scores": []}

        final = float(np.mean(scores))
        return {
            "score": round(final, 4),
            "evaluated_frames": len(scores),
            "frame_scores": [round(s, 4) for s in scores],
        }
