from typing import List, Dict, Any


class HeadPoseService:
    def classify_direction(self, frame_shape, bbox) -> str:
        height, width = frame_shape[:2]
        x1, y1, x2, y2 = bbox

        face_center_x = (x1 + x2) / 2.0
        face_center_y = (y1 + y2) / 2.0

        x_ratio = face_center_x / max(width, 1)
        y_ratio = face_center_y / max(height, 1)

        # Simple heuristics for starter version.
        # Replace later with landmarks / real head pose estimation.
        if x_ratio < 0.38:
            return "left"
        if x_ratio > 0.62:
            return "right"
        if y_ratio < 0.38:
            return "up"
        if y_ratio > 0.62:
            return "down"
        return "straight"

    def analyze_sequence(self, frames: List[Dict[str, Any]], detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        detection_map = {item["frame_index"]: item for item in detections}

        for frame_item in frames:
            frame_index = frame_item["frame_index"]
            frame = frame_item["image"]
            detection_item = detection_map.get(frame_index)

            if not detection_item or not detection_item["face_found"]:
                results.append({
                    "frame_index": frame_index,
                    "direction": None
                })
                continue

            bbox = detection_item["detection"]["bbox"]
            direction = self.classify_direction(frame.shape, bbox)

            results.append({
                "frame_index": frame_index,
                "direction": direction
            })

        return results

    def compress_directions(self, directions: List[str]) -> List[str]:
        compressed: List[str] = []
        previous = None

        for item in directions:
            if not item:
                continue
            if item != previous:
                compressed.append(item)
                previous = item

        return compressed