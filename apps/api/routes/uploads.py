"""Uploads API routes."""

from __future__ import annotations

import asyncio
import mimetypes
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from subflow.config import Settings

router = APIRouter(tags=["uploads"])


class UploadResponse(BaseModel):
    storage_key: str
    media_url: str
    size_bytes: int
    content_type: str


def _sanitize_filename(filename: str | None) -> str:
    raw = str(filename or "").strip()
    base = Path(raw).name
    base = base.replace("\x00", "")
    if not base:
        return "upload.bin"
    return base[:255]


def _detect_content_type(filename: str, provided: str | None) -> str:
    candidate = str(provided or "").strip()
    if candidate:
        return candidate
    guessed, _ = mimetypes.guess_type(filename)
    return str(guessed or "application/octet-stream")


def _file_size(upload: UploadFile) -> int:
    f = upload.file
    try:
        current = f.tell()
        f.seek(0, os.SEEK_END)
        size = int(f.tell())
        f.seek(current, os.SEEK_SET)
        return max(0, size)
    except Exception:
        return int(getattr(upload, "size", 0) or 0)


async def _write_upload_to_path(
    upload: UploadFile,
    target_path: Path,
    *,
    max_bytes: int,
    chunk_size: int = 8 * 1024 * 1024,
) -> int:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with target_path.open("wb") as f:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(status_code=413, detail="file too large")
                f.write(chunk)
    except HTTPException:
        try:
            target_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return written


async def _s3_upload(
    settings: Settings,
    upload: UploadFile,
    *,
    key: str,
) -> str:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint.rstrip("/"),
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(s3={"addressing_style": "path"}),
    )
    bucket = settings.s3_bucket_name

    def _ensure_bucket() -> None:
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", "") or "")
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            client.create_bucket(Bucket=bucket)

    await asyncio.to_thread(_ensure_bucket)
    await upload.seek(0)

    def _do_upload() -> None:
        client.upload_fileobj(upload.file, bucket, key)

    await asyncio.to_thread(_do_upload)

    expires_in = max(1, int(settings.s3_presign_expires_hours) * 3600)

    def _presign() -> str:
        return str(
            client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        )

    return await asyncio.to_thread(_presign)


@router.post("/upload", response_model=UploadResponse)
async def upload_file(request: Request, file: UploadFile = File(...)) -> UploadResponse:
    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="settings not initialized")

    safe_name = _sanitize_filename(file.filename)
    content_type = _detect_content_type(safe_name, file.content_type)

    upload_id = uuid4().hex
    storage_key = f"uploads/{upload_id}/{safe_name}"

    max_bytes = int(getattr(settings, "upload_max_bytes", 10 * 1024 * 1024 * 1024) or 0)
    if max_bytes <= 0:
        max_bytes = 10 * 1024 * 1024 * 1024

    backend = str(getattr(settings, "artifact_store_backend", "local") or "local").strip().lower()

    try:
        if backend == "s3":
            size_bytes = _file_size(file)
            if size_bytes and size_bytes > max_bytes:
                raise HTTPException(status_code=413, detail="file too large")
            media_url = await _s3_upload(settings, file, key=storage_key)
            return UploadResponse(
                storage_key=storage_key,
                media_url=media_url,
                size_bytes=size_bytes,
                content_type=content_type,
            )

        target_path = Path(settings.data_dir) / "uploads" / upload_id / safe_name
        size_bytes = await _write_upload_to_path(file, target_path, max_bytes=max_bytes)
        return UploadResponse(
            storage_key=storage_key,
            media_url=str(target_path),
            size_bytes=size_bytes,
            content_type=content_type,
        )
    finally:
        try:
            await file.close()
        except Exception:
            pass
