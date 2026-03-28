from pathlib import Path
from typing import List, Dict, Any

import cv2
import numpy as np

from vendor.silent_face.src.anti_spoof_predict import AntiSpoofPredict


class AntiSpoofService:
    def __init__(self, device_id: int = 0):
        self.predictor = AntiSpoofPredict(device_id=device_id)

        self.model_dir = Path("vendor/silent_face/resources/anti_spoof_models")
        self.model_paths = [str(p) for p in self.model_dir.glob("*.pth")]

        if not self.model_paths:
            raise RuntimeError(f"No anti-spoof model files found in {self.model_dir}")

    def _safe_crop(self, frame: np.ndarray, bbox: List[int]) -> np.ndarray | None:
        if frame is None or bbox is None:
            return None

        x, y, w, h = bbox
        x = max(0, int(x))
        y = max(0, int(y))
        w = max(1, int(w))
        h = max(1, int(h))

        x2 = min(frame.shape[1], x + w)
        y2 = min(frame.shape[0], y + h)

        if x >= x2 or y >= y2:
            return None

        crop = frame[y:y2, x:x2]
        return crop if crop.size > 0 else None

    def score_face(self, face_crop_bgr: np.ndarray) -> float:
        if face_crop_bgr is None or face_crop_bgr.size == 0:
            return 0.0

        if len(face_crop_bgr.shape) != 3 or face_crop_bgr.shape[2] != 3:
            return 0.0

        h, w = face_crop_bgr.shape[:2]
        if h < 20 or w < 20:
            return 0.0

        scores: List[float] = []

        for model_path in self.model_paths:
            try:
                resized = cv2.resize(face_crop_bgr, (80, 80))
                prediction = self.predictor.predict(resized, model_path)

                if prediction is None or len(prediction.shape) != 2 or prediction.shape[1] < 2:
                    continue

                live_score = float(prediction[0][1])
                scores.append(live_score)

            except Exception as ex:
                print(f"Silent-Face failed for model {model_path}: {ex}")
                continue

        if not scores:
            return 0.0

        return float(np.mean(scores))

    def score_video(
        self,
        frames: List[np.ndarray],
        detections: List[Dict[str, Any]],
        sample_step: int = 5,
        decision_threshold: float = 0.75,
    ) -> Dict[str, Any]:
        if not frames:
            return {
                "is_live": False,
                "score": 0.0,
                "label": "no_frames",
                "frame_scores": [],
            }

        sampled_scores: List[float] = []
        evaluated_frames = 0

        for i in range(0, min(len(frames), len(detections)), sample_step):
            frame = frames[i]["image"]
            detection = detections[i]

            if not detection.get("face_found"):
                continue

            bbox = detection.get("bbox")
            face_crop = self._safe_crop(frame, bbox)

            if face_crop is None:
                continue

            score = self.score_face(face_crop)
            sampled_scores.append(score)
            evaluated_frames += 1

        if not sampled_scores:
            return {
                "is_live": False,
                "score": 0.0,
                "label": "no_face_crops",
                "frame_scores": [],
            }

        final_score = float(np.mean(sampled_scores))
        is_live = final_score >= decision_threshold

        return {
            "is_live": is_live,
            "score": round(final_score, 4),
            "label": "likely_live" if is_live else "likely_spoof",
            "frame_scores": [round(s, 4) for s in sampled_scores],
            "evaluated_frames": evaluated_frames,
        }