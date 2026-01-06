"""Configuration management using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class ASRConfig(BaseSettings):
    """ASR Provider configuration."""

    model_config = SettingsConfigDict(env_prefix="ASR_")

    provider: str = "glm_asr"
    base_url: str = "http://localhost:8000/v1"
    api_key: str = "abc123"
    model: str = "glm-asr"
    max_concurrent: int = 20  # 并发请求数
    timeout: float = 300.0  # 单个请求超时（秒）


class LLMConfig(BaseSettings):
    """LLM Provider configuration."""

    model_config = SettingsConfigDict(env_prefix="LLM_")

    provider: str = "openai"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4"


class AudioConfig(BaseSettings):
    """Audio processing configuration."""

    model_config = SettingsConfigDict(env_prefix="AUDIO_")

    ffmpeg_bin: str = "ffmpeg"
    demucs_bin: str = "demucs"
    demucs_model: str = "htdemucs_ft"


class VADConfig(BaseSettings):
    """VAD configuration."""

    model_config = SettingsConfigDict(env_prefix="VAD_")

    min_silence_duration_ms: int = 300
    min_speech_duration_ms: int = 250


class Settings(BaseSettings):
    """Application settings."""

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

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
