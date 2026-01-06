"""Configuration management using pydantic-settings."""

from pydantic_settings import BaseSettings


class ASRConfig(BaseSettings):
    """ASR Provider configuration."""

    provider: str = "glm_asr"
    base_url: str = "http://localhost:8000/v1"
    api_key: str | None = None
    model: str = "glm-asr-nano-2512"

    class Config:
        env_prefix = "ASR_"


class LLMConfig(BaseSettings):
    """LLM Provider configuration."""

    provider: str = "openai"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4"

    class Config:
        env_prefix = "LLM_"


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

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
