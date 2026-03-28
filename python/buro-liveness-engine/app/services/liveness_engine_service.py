from typing import List, Optional
from app.models.responses import ReasonItem


class LivenessEngineService:
    def __init__(
        self,
        video_intake_service,
        frame_extraction_service,
        face_detection_service,
        head_pose_service,
        anti_spoof_service,
        challenge_validation_service,
    ):
        self.video_intake_service = video_intake_service
        self.frame_extraction_service = frame_extraction_service
        self.face_detection_service = face_detection_service
        self.head_pose_service = head_pose_service
        self.anti_spoof_service = anti_spoof_service
        self.challenge_validation_service = challenge_validation_service

    def analyze_video(
        self,
        video_path: str,
        expected_sequence: List[str],
        session_id: str,
        member_id: Optional[str] = None,
    ) -> dict:
        reasons: List[ReasonItem] = []

        normalized_expected_sequence = self._normalize_sequence(expected_sequence)
        metadata = self.video_intake_service.get_video_metadata(video_path)
        frames = self.frame_extraction_service.extract_frames(video_path)

        if not frames:
            reasons.append(
                ReasonItem(
                    code="NO_FRAMES",
                    message="No frames could be extracted from uploaded video.",
                )
            )
            return self._build_response(
                success=False,
                session_id=session_id,
                member_id=member_id,
                is_live=False,
                confidence=0.0,
                decision="fail",
                expected_sequence=normalized_expected_sequence,
                detected_sequence=[],
                frame_count=0,
                face_detected_frames=0,
                reasons=reasons,
                metadata=metadata,
            )

        if not normalized_expected_sequence:
            reasons.append(
                ReasonItem(
                    code="CHALLENGE_REQUIRED",
                    message="Expected challenge sequence is required for liveness validation.",
                )
            )

        detections = self.face_detection_service.detect_faces(frames)
        face_detected_frames = sum(1 for item in detections if item.get("face_found"))
        face_ok = self.face_detection_service.validate_face_presence(detections)

        if not face_ok:
            reasons.append(
                ReasonItem(
                    code="FACE_MISSING",
                    message="Face was not detected in enough frames.",
                )
            )

        pose_results = self.head_pose_service.analyze_sequence(frames, detections)
        raw_detected_sequence = [
            item.get("direction")
            for item in pose_results
            if item.get("direction")
        ]
        detected_sequence = self.head_pose_service.compress_directions(raw_detected_sequence)

        spoof_result = self.anti_spoof_service.score_video(frames, detections)
        is_live = bool(spoof_result.get("is_live", False))
        confidence = float(spoof_result.get("score", 0.0))

        if not is_live:
            reasons.append(
                ReasonItem(
                    code="ANTI_SPOOF_FAILED",
                    message="Anti-spoof validation failed.",
                )
            )

        if normalized_expected_sequence:
            sequence_result = self.challenge_validation_service.validate_sequence(
                normalized_expected_sequence,
                detected_sequence,
            )

            if not sequence_result.get("matched", False):
                missing_steps = sequence_result.get("missing_steps", [])
                missing_text = ", ".join(missing_steps) if missing_steps else "unknown"
                reasons.append(
                    ReasonItem(
                        code="SEQUENCE_MISMATCH",
                        message=f"Expected sequence not completed. Missing: {missing_text}.",
                    )
                )

        decision = self._decide_result(
            reasons=reasons,
            confidence=confidence,
            frame_count=len(frames),
            face_detected_frames=face_detected_frames,
        )

        return self._build_response(
            success=True,
            session_id=session_id,
            member_id=member_id,
            is_live=is_live,
            confidence=confidence,
            decision=decision,
            expected_sequence=normalized_expected_sequence,
            detected_sequence=detected_sequence,
            frame_count=len(frames),
            face_detected_frames=face_detected_frames,
            reasons=reasons,
            metadata=metadata,
        )

    def _normalize_sequence(self, sequence: List[str]) -> List[str]:
        return [
            str(item).strip().lower()
            for item in (sequence or [])
            if str(item).strip()
        ]

    def _decide_result(
        self,
        reasons: List[ReasonItem],
        confidence: float,
        frame_count: int,
        face_detected_frames: int,
    ) -> str:
        if not reasons:
            return "pass"

        hard_fail_codes = {
            "NO_FRAMES",
            "CHALLENGE_REQUIRED",
            "FACE_MISSING",
            "ANTI_SPOOF_FAILED",
            "SEQUENCE_MISMATCH",
        }

        reason_codes = {reason.code for reason in reasons}

        if reason_codes & hard_fail_codes:
            return "fail"

        face_ratio = face_detected_frames / frame_count if frame_count > 0 else 0.0

        if confidence >= 0.55 and face_ratio >= 0.5:
            return "review"

        return "fail"

    def _build_response(
        self,
        success: bool,
        session_id: str,
        member_id: Optional[str],
        is_live: bool,
        confidence: float,
        decision: str,
        expected_sequence: List[str],
        detected_sequence: List[str],
        frame_count: int,
        face_detected_frames: int,
        reasons: List[ReasonItem],
        metadata: dict,
    ) -> dict:
        return {
            "success": success,
            "session_id": session_id,
            "member_id": member_id,
            "is_live": is_live,
            "confidence": round(confidence, 4),
            "decision": decision,
            "expected_sequence": expected_sequence,
            "detected_sequence": detected_sequence,
            "frame_count": frame_count,
            "face_detected_frames": face_detected_frames,
            "reasons": [reason.model_dump() for reason in reasons],
            "metadata": metadata,
        }