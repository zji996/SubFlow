"""Artifact storage backends."""

from subflow.config import Settings
from subflow.storage.artifact_store import ArtifactStore, LocalArtifactStore
from subflow.storage.s3_store import S3ArtifactStore


def get_artifact_store(settings: Settings) -> ArtifactStore:
    backend = str(getattr(settings, "artifact_store_backend", "local") or "local").strip().lower()
    if backend == "s3":
        return S3ArtifactStore(
            endpoint=settings.s3_endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket_name,
        )
    return LocalArtifactStore(settings.data_dir)


__all__ = ["ArtifactStore", "LocalArtifactStore", "S3ArtifactStore", "get_artifact_store"]
