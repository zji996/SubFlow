"""S3/MinIO artifact store implementation."""

from __future__ import annotations

import asyncio
import builtins
import logging
from typing import Any

from botocore.config import Config
from botocore.exceptions import ClientError

from subflow.storage.artifact_store import ArtifactStore
from subflow.storage.s3_pagination import iter_list_objects_v2

logger = logging.getLogger(__name__)


class S3ArtifactStore(ArtifactStore):
    """S3/MinIO artifact store for production."""

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket

        self._client: Any | None = None
        self._bucket_ready: bool = False
        self._bucket_lock = asyncio.Lock()

    def _key(self, project_id: str, stage: str, name: str) -> str:
        safe_stage = str(stage or "").strip().replace("/", "_")
        safe_name = str(name or "").strip().replace("/", "_")
        return f"projects/{project_id}/{safe_stage}/{safe_name}"

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client

        import boto3

        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=Config(s3={"addressing_style": "path"}),
        )
        return self._client

    async def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return

        async with self._bucket_lock:
            if self._bucket_ready:
                return

            client = self._ensure_client()

            def _head_or_create() -> None:
                try:
                    client.head_bucket(Bucket=self.bucket)
                    return
                except ClientError as exc:
                    code = str(exc.response.get("Error", {}).get("Code", "") or "")
                    if code not in {"404", "NoSuchBucket", "NotFound"}:
                        raise

                client.create_bucket(Bucket=self.bucket)

            try:
                await asyncio.to_thread(_head_or_create)
            except ClientError as exc:
                raise RuntimeError(f"Failed to ensure S3 bucket {self.bucket!r}: {exc}") from exc

            self._bucket_ready = True

    async def save(self, project_id: str, stage: str, name: str, data: bytes) -> str:
        client = self._ensure_client()
        await self._ensure_bucket()
        key = self._key(project_id, stage, name)

        def _put() -> None:
            client.put_object(Bucket=self.bucket, Key=key, Body=data)

        await asyncio.to_thread(_put)
        return f"s3://{self.bucket}/{key}"

    async def load(self, project_id: str, stage: str, name: str) -> bytes:
        client = self._ensure_client()
        await self._ensure_bucket()
        key = self._key(project_id, stage, name)

        def _get() -> bytes:
            resp = client.get_object(Bucket=self.bucket, Key=key)
            return bytes(resp["Body"].read())

        try:
            return await asyncio.to_thread(_get)
        except ClientError as exc:
            raise FileNotFoundError(f"S3 artifact not found: {key}") from exc

    async def list(self, project_id: str, stage: str | None = None) -> builtins.list[str]:
        client = self._ensure_client()
        await self._ensure_bucket()

        prefix = f"projects/{project_id}/"
        if stage:
            safe_stage = str(stage or "").strip().replace("/", "_")
            prefix = f"{prefix}{safe_stage}/"

        def _list() -> builtins.list[str]:
            out: list[str] = []
            for resp in iter_list_objects_v2(client, bucket=self.bucket, Prefix=prefix):
                for obj in resp.get("Contents") or []:
                    key = str(obj.get("Key") or "")
                    if key:
                        out.append(f"s3://{self.bucket}/{key}")
            return out

        try:
            return await asyncio.to_thread(_list)
        except ClientError as exc:
            raise RuntimeError(f"Failed to list S3 artifacts (prefix={prefix!r}): {exc}") from exc

    async def get_presigned_url(
        self,
        project_id: str,
        stage: str,
        name: str,
        *,
        expires_in: int,
    ) -> str:
        client = self._ensure_client()
        await self._ensure_bucket()
        key = self._key(project_id, stage, name)

        def _gen() -> str:
            return str(
                client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=max(1, int(expires_in)),
                )
            )

        return await asyncio.to_thread(_gen)

    async def delete_project(self, project_id: str) -> int:
        client = self._ensure_client()
        await self._ensure_bucket()
        prefix = f"projects/{project_id}/"

        def _delete_all() -> int:
            deleted = 0
            for resp in iter_list_objects_v2(client, bucket=self.bucket, Prefix=prefix):
                objects = resp.get("Contents") or []
                if objects:
                    keys = [{"Key": obj["Key"]} for obj in objects if obj.get("Key")]
                    if not keys:
                        continue
                    client.delete_objects(
                        Bucket=self.bucket,
                        Delete={"Objects": keys},
                    )
                    deleted += len(keys)
            return deleted

        try:
            deleted = int(await asyncio.to_thread(_delete_all))
            logger.info("s3 artifacts deleted (project_id=%s, objects=%d)", project_id, deleted)
            return deleted
        except ClientError as exc:
            logger.warning("s3 artifacts delete failed (project_id=%s): %s", project_id, exc)
            return 0

    async def list_project_ids(self) -> builtins.list[str]:
        client = self._ensure_client()
        await self._ensure_bucket()

        def _list() -> builtins.list[str]:
            ids: set[str] = set()
            for resp in iter_list_objects_v2(
                client,
                bucket=self.bucket,
                Prefix="projects/",
                Delimiter="/",
            ):
                for prefix in resp.get("CommonPrefixes") or []:
                    p = str(prefix.get("Prefix") or "")
                    parts = p.strip("/").split("/")
                    if len(parts) >= 2 and parts[0] == "projects":
                        ids.add(parts[1])
            return sorted(ids)

        try:
            return await asyncio.to_thread(_list)
        except ClientError as exc:
            logger.warning("s3 list_project_ids failed: %s", exc)
            return []
