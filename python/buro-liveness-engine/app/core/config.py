from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: str = "development"
    app_version: str = "1.0.0"
    secret_key: str = "dev-secret-key-CHANGE-ME-IN-PRODUCTION"

    # Database
    database_url: str = "sqlite:///./liveness.db"

    # Storage
    upload_dir: Path = Path("uploads")
    max_upload_bytes: int = 50 * 1024 * 1024  # 50 MB
    allowed_extensions: list[str] = [".mp4", ".webm", ".mov"]

    # Session
    session_ttl_seconds: int = 600  # 10 minutes

    # Challenge
    challenge_length: int = 3
    challenge_pool: list[str] = ["left", "right", "up", "straight"]

    # Engine — anti-spoof
    anti_spoof_pass_threshold: float = 0.75
    anti_spoof_review_threshold: float = 0.55
    anti_spoof_device_id: int = 0

    # Engine — face / frame
    face_presence_min_ratio: float = 0.50
    min_usable_frames: int = 10

    # Engine — quality checks
    blur_laplacian_threshold: float = 40.0   # variance below this = blurry
    dark_brightness_threshold: float = 40.0  # mean brightness below this = too dark
    quality_fail_ratio: float = 0.60         # fraction of bad frames to flag


settings = Settings()
