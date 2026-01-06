"""S3 operations (placeholder)."""

from __future__ import annotations

from subflow.config import Settings
from subflow.services import StorageService as CoreStorageService


class StorageService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._storage = CoreStorageService(
            endpoint=settings.s3_endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket_name,
        )

    async def get_presigned_download_url(self, s3_path: str) -> str:
        return await self._storage.get_presigned_url(s3_path)
