import json
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from app.services.video_intake_service import VideoIntakeService
from app.services.frame_extraction_service import FrameExtractionService
from app.services.face_detection_service import FaceDetectionService
from app.services.head_pose_service import HeadPoseService
from app.services.anti_spoof_service import AntiSpoofService
from app.services.challenge_validation_service import ChallengeValidationService
from app.services.liveness_engine_service import LivenessEngineService

router = APIRouter()

video_intake_service = VideoIntakeService()
frame_extraction_service = FrameExtractionService()
face_detection_service = FaceDetectionService()
head_pose_service = HeadPoseService()
anti_spoof_service = AntiSpoofService()
challenge_validation_service = ChallengeValidationService()

liveness_engine_service = LivenessEngineService(
    video_intake_service=video_intake_service,
    frame_extraction_service=frame_extraction_service,
    face_detection_service=face_detection_service,
    head_pose_service=head_pose_service,
    anti_spoof_service=anti_spoof_service,
    challenge_validation_service=challenge_validation_service,
)


@router.post("/analyze")
async def analyze_liveness(
    session_id: str = Form(...),
    expected_sequence: str = Form("[]"),
    member_id: str | None = Form(None),
    video: UploadFile = File(...),
):
    try:
        raw_sequence = (expected_sequence or "").strip()
        print("RAW expected_sequence:", repr(raw_sequence))

        if raw_sequence == "":
            parsed_sequence = []
        else:
            try:
                parsed_sequence = json.loads(raw_sequence)
            except json.JSONDecodeError:
                parsed_sequence = [
                    item.strip().lower()
                    for item in raw_sequence.split(",")
                    if item.strip()
                ]

        if not isinstance(parsed_sequence, list):
            raise ValueError("expected_sequence must be a JSON array or comma-separated string")

        parsed_sequence = [
            str(item).strip().lower()
            for item in parsed_sequence
            if str(item).strip()
        ]

        saved_video_path = video_intake_service.save_upload(
            video.file,
            video.filename or "upload.mp4"
        )

        result = liveness_engine_service.analyze_video(
            video_path=str(saved_video_path),
            expected_sequence=parsed_sequence,
            session_id=session_id,
            member_id=member_id,
        )
        return result

    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Unhandled server error: {str(ex)}")