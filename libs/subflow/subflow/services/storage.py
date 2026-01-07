"""MinIO/S3 storage service."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StorageConfig:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str


class StorageService:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self._client: Any | None = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        import boto3

        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        )
        return self._client

    def _object_url(self, remote_key: str) -> str:
        remote_key = remote_key.lstrip("/")
        return f"{self.endpoint}/{self.bucket}/{remote_key}"

    async def upload_file(self, local_path: str, remote_key: str) -> str:
        """上传文件，返回 URL"""
        client = self._ensure_client()
        remote_key = remote_key.lstrip("/")
        await asyncio.to_thread(client.upload_file, local_path, self.bucket, remote_key)
        return self._object_url(remote_key)

    async def download_file(self, remote_key: str, local_path: str) -> str:
        """下载文件"""
        client = self._ensure_client()
        remote_key = remote_key.lstrip("/")
        await asyncio.to_thread(client.download_file, self.bucket, remote_key, local_path)
        return local_path

    async def get_presigned_url(self, remote_key: str, expires_in: int = 3600) -> str:
        """生成预签名下载 URL"""
        client = self._ensure_client()
        remote_key = remote_key.lstrip("/")

        def _gen() -> str:
            return str(
                client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": remote_key},
                    ExpiresIn=expires_in,
                )
            )

        return await asyncio.to_thread(_gen)
