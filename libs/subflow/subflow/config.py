"""Configuration management using pydantic-settings."""

from pathlib import Path
from typing import Any
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILES = (".env", "../.env", "../../.env")


class ASRConfig(BaseSettings):
    """ASR Provider configuration."""

    model_config = SettingsConfigDict(
        env_prefix="ASR_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: str = "glm_asr"
    base_url: str = "http://localhost:8000/v1"
    api_key: str = "abc123"
    model: str = "glm-asr"
    max_concurrent: int = 20  # 并发请求数
    timeout: float = 300.0  # 单个请求超时（秒）


class LLMConfig(BaseSettings):
    """LLM Provider configuration."""

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: str = "openai"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4"
    max_asr_segments: int | None = None


class AudioConfig(BaseSettings):
    """Audio processing configuration."""

    model_config = SettingsConfigDict(
        env_prefix="AUDIO_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ffmpeg_bin: str = "ffmpeg"
    demucs_bin: str = "demucs"
    demucs_model: str = "htdemucs_ft"
    max_duration_s: float | None = None


class VADConfig(BaseSettings):
    """VAD configuration."""

    model_config = SettingsConfigDict(
        env_prefix="VAD_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    nemo_model_path: str = (
        "./models/modelscope/models/nv-community/Frame_VAD_Multilingual_MarbleNet_v2.0/"
        "frame_vad_multilingual_marblenet_v2.0.nemo"
    )
    nemo_device: str | None = None

    # Base VAD parameters (defaults tuned for shorter ASR-friendly segments)
    min_silence_duration_ms: int = 60
    min_speech_duration_ms: int = 100
    threshold: float = 0.60
    # Split long regions at low-probability valleys (VAD-aware splitting).
    target_max_segment_s: float | None = 4.0
    split_threshold: float | None = 0.45
    split_search_backtrack_ratio: float = 0.7
    split_search_forward_ratio: float = 0.03
    # Optional: when splitting without a clear valley, trim a small gap around the cut.
    # Higher values -> more fragmentation but higher risk of dropping speech phonemes.
    split_gap_s: float = 0.0


class LoggingSettings(BaseSettings):
    """Logging configuration."""

    model_config = SettingsConfigDict(
        env_prefix="LOG_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    level: str = "INFO"
    format: str = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    datefmt: str = "%Y-%m-%d %H:%M:%S"
    console: bool = True
    file: str | None = None
    max_bytes: int = Field(default=10 * 1024 * 1024, ge=0)
    backup_count: int = Field(default=5, ge=0)


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(env_file=_ENV_FILES, env_file_encoding="utf-8", extra="ignore")

    models_dir: str = "./models"
    data_dir: str = "./data"
    log_dir: str = "./logs"

    # Database
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "subflow"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # Redis
    redis_url: str = "redis://localhost:6379"

    # S3/MinIO
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_name: str = "subflow"

    # ASR
    asr: ASRConfig = ASRConfig()

    # LLM
    llm: LLMConfig = LLMConfig()

    # Audio
    audio: AudioConfig = AudioConfig()

    # VAD
    vad: VADConfig = VADConfig()

    # Logging
    logging: LoggingSettings = LoggingSettings()

    def model_post_init(self, __context: Any) -> None:
        root = Path(__file__).resolve().parents[3]

        def _abs_dir(p: str) -> str:
            path = Path(p)
            if path.is_absolute():
                out = path
            else:
                out = (root / path).resolve()
            out.mkdir(parents=True, exist_ok=True)
            return str(out)

        # No fallback: always resolve relative paths under repo root.
        self.models_dir = _abs_dir(self.models_dir)
        self.data_dir = _abs_dir(self.data_dir)
        self.log_dir = _abs_dir(self.log_dir)

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
