"""Configuration management using pydantic-settings."""

from pathlib import Path
from typing import Any
from pydantic import Field, model_validator
from pydantic.aliases import AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

from subflow.exceptions import ConfigurationError

_ENV_FILES = (".env", "../.env", "../../.env")

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_repo_path(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return raw
    p = Path(raw)
    if p.is_absolute():
        return str(p)
    return str((_REPO_ROOT / p).resolve())


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
    api_key: str = ""
    model: str = "glm-asr"
    timeout: float = 300.0  # 单个请求超时（秒）
    ffmpeg_concurrency: int = Field(default=10, ge=1)
    max_chunk_s: float = Field(default=15.0, gt=0)


class LLMProfileConfig(BaseSettings):
    """Optional LLM profile override (used for fast/power)."""

    provider: str = "openai"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4"


class LLMLimitsConfig(BaseSettings):
    """LLM limits (not tied to any provider/profile)."""

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    max_asr_segments: int | None = None


class LLMFastConfig(LLMProfileConfig):
    model_config = SettingsConfigDict(
        env_prefix="LLM_FAST_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )


class LLMPowerConfig(LLMProfileConfig):
    model_config = SettingsConfigDict(
        env_prefix="LLM_POWER_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )


class LLMStageRouting(BaseSettings):
    """Select which LLM profile each stage uses (fast/power)."""

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    asr_correction: str = "fast"
    global_understanding: str = "fast"
    semantic_translation: str = "power"


class ConcurrencyConfig(BaseSettings):
    """Global concurrency limits by service type."""

    model_config = SettingsConfigDict(
        env_prefix="CONCURRENCY_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    asr: int = Field(default=10, ge=1)
    llm_fast: int = Field(
        default=10,
        ge=1,
        validation_alias=AliasChoices("llm_fast", "CONCURRENCY_LLM_FAST"),
    )
    llm_power: int = Field(default=4, ge=1)


class ParallelConfig(BaseSettings):
    """Region-gap based parallel processing config."""

    model_config = SettingsConfigDict(
        env_prefix="PARALLEL_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = True
    min_gap_seconds: float = Field(default=1.0, ge=0.1)


class AudioConfig(BaseSettings):
    """Audio processing configuration."""

    model_config = SettingsConfigDict(
        env_prefix="AUDIO_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: str = "ffmpeg_demucs"
    ffmpeg_bin: str = "ffmpeg"
    demucs_bin: str = "demucs"
    demucs_model: str = "htdemucs_ft"
    max_duration_s: float | None = None

    normalize: bool = True
    normalize_target_db: float = -1.0


class VADConfig(BaseSettings):
    """VAD configuration."""

    model_config = SettingsConfigDict(
        env_prefix="VAD_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: str = "nemo"
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

    @model_validator(mode="after")
    def _resolve_paths(self) -> "VADConfig":
        self.nemo_model_path = _resolve_repo_path(self.nemo_model_path)
        return self


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
    upload_max_bytes: int = Field(default=10 * 1024 * 1024 * 1024, ge=1)

    # Database
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "subflow"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_project_ttl_days: int = Field(default=30, ge=1)

    # Artifacts
    artifact_store_backend: str = "s3"  # "local" | "s3"

    # S3/MinIO
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_name: str = "subflow"
    s3_presign_expires_hours: int = Field(default=24, ge=1)

    # ASR
    asr: ASRConfig = ASRConfig()

    # LLM
    llm_limits: LLMLimitsConfig = LLMLimitsConfig()
    llm_fast: LLMFastConfig = LLMFastConfig()
    llm_power: LLMPowerConfig = LLMPowerConfig()
    llm_stage: LLMStageRouting = LLMStageRouting()

    # Concurrency (service-level)
    concurrency: ConcurrencyConfig = ConcurrencyConfig()

    # Region-gap based parallel processing (Stage 4 + Stage 5)
    parallel: ParallelConfig = ParallelConfig()

    @model_validator(mode="after")
    def _resolve_paths(self) -> "Settings":
        # Running apps with `uv run --directory apps/*` changes CWD; keep paths stable.
        self.models_dir = _resolve_repo_path(self.models_dir)
        self.data_dir = _resolve_repo_path(self.data_dir)
        self.log_dir = _resolve_repo_path(self.log_dir)
        return self

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
    def concurrency_asr(self) -> int:
        return int(self.concurrency.asr)

    @property
    def concurrency_llm_correction(self) -> int:
        # Deprecated alias: Stage 4 used to rely on this name.
        return int(self.concurrency.llm_fast)

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    def llm_config_for(self, profile: str) -> dict[str, Any]:
        """Return an LLM config dict for provider registry."""
        name = str(profile or "").strip().lower()
        if name in {"", "fast"}:
            cfg = self.llm_fast.model_dump()
        elif name == "power":
            cfg = self.llm_power.model_dump()
        else:
            raise ConfigurationError(f"Unknown LLM profile: {profile!r} (expected: fast/power)")

        provider = str(cfg.get("provider") or "").strip()
        base_url = str(cfg.get("base_url") or "").strip()
        if not provider or not base_url:
            raise ConfigurationError(
                f"LLM profile {name!r} is not configured (need provider/base_url; got provider={provider!r} base_url={base_url!r})"
            )
        return cfg
