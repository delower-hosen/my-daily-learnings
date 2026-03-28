from typing import List, Dict, Any

class AntiSpoofService:
    def score_video(self, frames: List[Dict[str, Any]], detections: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Starter heuristic only.
        # Replace with real anti-spoof model later.
        total_frames = len(frames)
        face_frames = sum(1 for item in detections if item["face_found"])

        if total_frames == 0:
            return {
                "is_live": False,
                "score": 0.0,
                "label": "no_frames"
            }

        ratio = face_frames / total_frames

        if ratio < 0.4:
            return {
                "is_live": False,
                "score": 0.2,
                "label": "insufficient_face_presence"
            }

        if ratio < 0.6:
            return {
                "is_live": True,
                "score": 0.6,
                "label": "borderline_live"
            }

        return {
            "is_live": True,
            "score": 0.82,
            "label": "likely_live"
        }