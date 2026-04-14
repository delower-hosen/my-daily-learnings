import logging

import cv2
import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)


def _laplacian_variance(gray: np.ndarray) -> float:
    """Higher = sharper. Low value = blurry frame."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _mean_brightness(gray: np.ndarray) -> float:
    """Mean pixel intensity, 0–255."""
    return float(np.mean(gray))


def check_frame_quality(
    frames: list[dict],
    detections: list[dict],
) -> dict[str, bool | float]:
    """
    Sample frames that have a detected face and evaluate blur + brightness.

    Returns:
        {
            "too_blurry": bool,
            "too_dark": bool,
            "blur_ratio": float,    # fraction of sampled frames that are blurry
            "dark_ratio": float,    # fraction of sampled frames that are too dark
            "sampled": int,
        }
    """
    det_map = {d["frame_index"]: d for d in detections}

    blur_fails = 0
    dark_fails = 0
    sampled = 0

    for frame_item in frames:
        idx = frame_item["frame_index"]
        det = det_map.get(idx)

        if not det or not det["face_found"] or det["bbox"] is None:
            continue

        img = frame_item["image"]
        x, y, w, h = det["bbox"]
        x, y = max(0, x), max(0, y)
        face_crop = img[y: y + h, x: x + w]

        if face_crop.size == 0:
            continue

        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        sampled += 1

        if _laplacian_variance(gray) < settings.blur_laplacian_threshold:
            blur_fails += 1

        if _mean_brightness(gray) < settings.dark_brightness_threshold:
            dark_fails += 1

    if sampled == 0:
        return {
            "too_blurry": False,
            "too_dark": False,
            "blur_ratio": 0.0,
            "dark_ratio": 0.0,
            "sampled": 0,
        }

    blur_ratio = blur_fails / sampled
    dark_ratio = dark_fails / sampled
    fail_ratio = settings.quality_fail_ratio

    logger.debug(
        "Quality check: sampled=%d blur_ratio=%.2f dark_ratio=%.2f",
        sampled, blur_ratio, dark_ratio,
    )

    return {
        "too_blurry": blur_ratio >= fail_ratio,
        "too_dark": dark_ratio >= fail_ratio,
        "blur_ratio": round(blur_ratio, 3),
        "dark_ratio": round(dark_ratio, 3),
        "sampled": sampled,
    }
