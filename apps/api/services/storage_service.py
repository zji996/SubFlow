"""S3 operations (placeholder)."""

from __future__ import annotations

from libs.subflow.config import Settings


class StorageService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def get_presigned_download_url(self, s3_path: str) -> str:
        raise NotImplementedError("StorageService is not implemented yet")

