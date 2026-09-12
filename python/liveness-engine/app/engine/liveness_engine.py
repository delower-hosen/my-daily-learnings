import logging
from typing import Any

from app.core.config import settings
from app.engine.anti_spoof import AntiSpoof
from app.engine.challenge_validator import ChallengeValidator
from app.engine.face_detector import FaceDetector
from app.engine.frame_extractor import FrameExtractor
from app.engine.head_pose import HeadPose
from app.engine.quality_checks import check_frame_quality

logger = logging.getLogger(__name__)

_HARD_FAIL = {
    "NO_FRAMES",
    "VIDEO_TOO_SHORT",
    "FACE_MISSING",
    "MULTIPLE_FACES",
    "ANTI_SPOOF_FAILED",
    "SEQUENCE_MISMATCH",
    "CHALLENGE_MISSING",
}


class LivenessEngine:
    """
    Orchestrates the full liveness pipeline.
    Knows nothing about sessions, DB, or HTTP — pure CV/ML logic.
    Returns a plain dict that ProcessingService persists.
    """

    def __init__(self) -> None:
        self.extractor = FrameExtractor()
        self.detector = FaceDetector()
        self.pose = HeadPose()
        self.spoof = AntiSpoof()
        self.validator = ChallengeValidator()

    def analyze(
        self,
        video_path: str,
        expected_sequence: list[str],
    ) -> dict[str, Any]:
        reason_codes: list[str] = []

        # ── 1. Challenge guard ────────────────────────────────────────────────
        if not expected_sequence:
            reason_codes.append("CHALLENGE_MISSING")
            return self._result(
                verdict="FAIL",
                confidence=0.0,
                reason_codes=reason_codes,
                expected_sequence=[],
                detected_sequence=[],
                frame_count=0,
                face_detected_frames=0,
                video_duration_sec=None,
            )

        # ── 2. Metadata + frame extraction ───────────────────────────────────
        meta = self.extractor.get_metadata(video_path)
        frames = self.extractor.extract(video_path)

        if not frames:
            reason_codes.append("NO_FRAMES")
            return self._result(
                verdict="FAIL",
                confidence=0.0,
                reason_codes=reason_codes,
                expected_sequence=expected_sequence,
                detected_sequence=[],
                frame_count=0,
                face_detected_frames=0,
                video_duration_sec=meta.get("duration_seconds"),
            )

        if len(frames) < settings.min_usable_frames:
            reason_codes.append("VIDEO_TOO_SHORT")

        # ── 3. Face detection ────────────────────────────────────────────────
        detections = self.detector.detect(frames)
        face_detected_frames = sum(1 for d in detections if d["face_found"])
        presence_ratio = self.detector.face_presence_ratio(detections)

        if presence_ratio < settings.face_presence_min_ratio:
            reason_codes.append("FACE_MISSING")

        if self.detector.multiple_faces_detected(detections):
            reason_codes.append("MULTIPLE_FACES")

        # ── 4. Head pose / challenge sequence ────────────────────────────────
        pose_results = self.pose.analyze(frames, detections)
        raw_dirs = [r["direction"] for r in pose_results if r["direction"]]
        detected_sequence = self.pose.compress(raw_dirs)

        seq_result = self.validator.validate(expected_sequence, detected_sequence)
        if not seq_result["matched"]:
            reason_codes.append("SEQUENCE_MISMATCH")

        # ── 5. Frame quality checks ───────────────────────────────────────────
        quality = check_frame_quality(frames, detections)
        if quality["too_blurry"]:
            reason_codes.append("BLURRY_FRAMES")
        if quality["too_dark"]:
            reason_codes.append("POOR_LIGHTING")

        # ── 6. Anti-spoof scoring ─────────────────────────────────────────────
        spoof = self.spoof.score_video(frames, detections)
        confidence = spoof["score"]

        if confidence < settings.anti_spoof_review_threshold:
            reason_codes.append("ANTI_SPOOF_FAILED")

        # ── 7. Verdict ───────────────────────────────────────────────────────
        verdict = self._decide(reason_codes, confidence)

        logger.info(
            "Engine result: verdict=%s confidence=%.4f reasons=%s",
            verdict, confidence, reason_codes,
        )

        return self._result(
            verdict=verdict,
            confidence=confidence,
            reason_codes=reason_codes,
            expected_sequence=expected_sequence,
            detected_sequence=detected_sequence,
            frame_count=len(frames),
            face_detected_frames=face_detected_frames,
            video_duration_sec=meta.get("duration_seconds"),
        )

    def _decide(self, reason_codes: list[str], confidence: float) -> str:
        codes = set(reason_codes)

        # Hard failures always lose
        if codes & _HARD_FAIL:
            return "FAIL"

        # Quality issues downgrade a clean PASS to REVIEW
        soft_quality = {"BLURRY_FRAMES", "POOR_LIGHTING"}
        has_quality_issue = bool(codes & soft_quality)

        if confidence >= settings.anti_spoof_pass_threshold:
            return "REVIEW" if has_quality_issue else "PASS"

        if confidence >= settings.anti_spoof_review_threshold:
            return "REVIEW"

        return "FAIL"

    def _result(
        self,
        verdict: str,
        confidence: float,
        reason_codes: list[str],
        expected_sequence: list[str],
        detected_sequence: list[str],
        frame_count: int,
        face_detected_frames: int,
        video_duration_sec: float | None,
    ) -> dict[str, Any]:
        return {
            "verdict": verdict,
            "confidence": round(confidence, 4),
            "reason_codes": reason_codes,
            "expected_sequence": expected_sequence,
            "detected_sequence": detected_sequence,
            "frame_count": frame_count,
            "face_detected_frames": face_detected_frames,
            "video_duration_sec": video_duration_sec,
        }
