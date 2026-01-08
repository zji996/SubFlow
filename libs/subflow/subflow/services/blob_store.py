"""Local content-addressable blob store with Postgres reference counting."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from subflow.config import Settings

logger = logging.getLogger(__name__)

FileType = Literal["input_video", "audio", "vocals"]


@dataclass(frozen=True)
class ProjectFileRef:
    file_type: FileType
    blob_hash: str
    path: str
    original_filename: str | None = None


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    """Return (sha256_hex, size_bytes) by streaming a local file."""
    p = Path(path)
    h = hashlib.sha256()
    size = 0
    with p.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


class BlobStore:
    """Local blob store rooted at `{DATA_DIR}/blobs`, with Postgres metadata."""

    _EXISTS_CACHE_TTL_SECONDS = 24 * 3600

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_dir = Path(settings.data_dir) / "blobs"
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()

    def blob_path(self, hash_hex: str) -> Path:
        h = (hash_hex or "").strip().lower()
        if len(h) < 4:
            raise ValueError("hash too short")
        return self.base_dir / h[:2] / h[2:4] / h

    def _redis_key_exists(self, hash_hex: str) -> str:
        return f"blob:exists:{hash_hex}"

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._schema_lock:
            if self._schema_ready:
                return
            await asyncio.to_thread(self._ensure_schema_sync)
            self._schema_ready = True

    def _ensure_schema_sync(self) -> None:
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("psycopg is required for BlobStore") from exc

        with psycopg.connect(self.settings.database_url, connect_timeout=1) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS file_blobs (
                      hash VARCHAR(64) PRIMARY KEY,
                      size_bytes BIGINT,
                      mime_type VARCHAR(128),
                      ref_count INT DEFAULT 0,
                      created_at TIMESTAMP DEFAULT NOW(),
                      last_accessed_at TIMESTAMP DEFAULT NOW()
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS project_files (
                      id UUID PRIMARY KEY,
                      project_id VARCHAR(64) NOT NULL,
                      file_type VARCHAR(32) NOT NULL,
                      blob_hash VARCHAR(64) NOT NULL REFERENCES file_blobs(hash),
                      original_filename VARCHAR(255),
                      created_at TIMESTAMP DEFAULT NOW(),
                      UNIQUE(project_id, file_type)
                    );
                    """
                )
            conn.commit()

    def _redis(self) -> Any:
        import redis.asyncio as redis

        return redis.from_url(str(self.settings.redis_url))

    async def _cache_exists(self, hash_hex: str) -> None:
        try:
            r = self._redis()
            await r.set(self._redis_key_exists(hash_hex), "1", ex=self._EXISTS_CACHE_TTL_SECONDS)
            await r.aclose()
        except Exception:
            return

    def _guess_mime(self, path: Path, content_type: str | None) -> str | None:
        if content_type:
            return str(content_type).split(";", 1)[0].strip() or None
        guess, _ = mimetypes.guess_type(str(path))
        return guess

    async def ingest_file(
        self,
        *,
        project_id: str,
        file_type: FileType,
        local_path: str,
        original_filename: str | None = None,
        mime_type: str | None = None,
        move: bool = False,
    ) -> ProjectFileRef:
        hash_hex, size_bytes = await asyncio.to_thread(sha256_file, local_path)
        return await self.ingest_hashed_file(
            project_id=project_id,
            file_type=file_type,
            local_path=local_path,
            hash_hex=hash_hex,
            size_bytes=size_bytes,
            original_filename=original_filename,
            mime_type=mime_type,
            move=move,
        )

    async def ingest_hashed_file(
        self,
        *,
        project_id: str,
        file_type: FileType,
        local_path: str,
        hash_hex: str,
        size_bytes: int,
        original_filename: str | None = None,
        mime_type: str | None = None,
        move: bool = False,
    ) -> ProjectFileRef:
        try:
            await self._ensure_schema()
            ref = await asyncio.to_thread(
                self._ingest_hashed_file_sync,
                project_id,
                file_type,
                local_path,
                hash_hex,
                int(size_bytes),
                original_filename,
                mime_type,
                bool(move),
            )
            await self._cache_exists(str(ref.blob_hash))
            return ref
        except Exception as exc:
            logger.warning("BlobStore ingest skipped (project_id=%s, file_type=%s): %s", project_id, file_type, exc)
            fallback = Path(local_path)
            blob_path = None
            try:
                blob_path = self.blob_path(hash_hex)
            except Exception:
                blob_path = None
            if blob_path is not None and blob_path.exists():
                fallback = blob_path
            return ProjectFileRef(
                file_type=file_type,
                blob_hash=str(hash_hex),
                path=str(fallback),
                original_filename=original_filename,
            )

    def _ingest_hashed_file_sync(
        self,
        project_id: str,
        file_type: FileType,
        local_path: str,
        hash_hex: str,
        size_bytes: int,
        original_filename: str | None,
        mime_type: str | None,
        move: bool,
    ) -> ProjectFileRef:
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("psycopg is required for BlobStore") from exc

        src = Path(local_path)
        if not src.exists():
            raise FileNotFoundError(local_path)

        dst = self.blob_path(hash_hex)
        dst.parent.mkdir(parents=True, exist_ok=True)

        if not dst.exists():
            try:
                if move:
                    try:
                        os.replace(src, dst)
                    except OSError:
                        shutil.move(str(src), str(dst))
                else:
                    shutil.copy2(str(src), str(dst))
            except FileExistsError:
                if move and src.exists():
                    try:
                        src.unlink()
                    except Exception:
                        pass

        with psycopg.connect(self.settings.database_url, connect_timeout=1) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT blob_hash FROM project_files WHERE project_id=%s AND file_type=%s",
                    (project_id, str(file_type)),
                )
                row = cur.fetchone()
                old_hash = str(row[0]) if row else None

                if old_hash and old_hash == hash_hex:
                    cur.execute(
                        "UPDATE file_blobs SET last_accessed_at=NOW() WHERE hash=%s",
                        (hash_hex,),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO file_blobs (hash, size_bytes, mime_type, ref_count, created_at, last_accessed_at)
                        VALUES (%s, %s, %s, 1, NOW(), NOW())
                        ON CONFLICT (hash) DO UPDATE
                        SET ref_count = file_blobs.ref_count + 1,
                            last_accessed_at = NOW(),
                            size_bytes = EXCLUDED.size_bytes,
                            mime_type = COALESCE(EXCLUDED.mime_type, file_blobs.mime_type);
                        """,
                        (hash_hex, int(size_bytes), mime_type),
                    )
                    if old_hash:
                        cur.execute(
                            """
                            UPDATE file_blobs
                            SET ref_count = GREATEST(ref_count - 1, 0),
                                last_accessed_at = NOW()
                            WHERE hash=%s;
                            """,
                            (old_hash,),
                        )

                    if row:
                        cur.execute(
                            """
                            UPDATE project_files
                            SET blob_hash=%s, original_filename=%s
                            WHERE project_id=%s AND file_type=%s;
                            """,
                            (hash_hex, original_filename, project_id, str(file_type)),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO project_files (id, project_id, file_type, blob_hash, original_filename, created_at)
                            VALUES (%s, %s, %s, %s, %s, NOW());
                            """,
                            (uuid4(), project_id, str(file_type), hash_hex, original_filename),
                        )
            conn.commit()

        return ProjectFileRef(
            file_type=file_type,
            blob_hash=hash_hex,
            path=str(dst),
            original_filename=original_filename,
        )

    async def release_project_files(self, project_id: str) -> int:
        try:
            await self._ensure_schema()
            return int(await asyncio.to_thread(self._release_project_files_sync, project_id))
        except Exception as exc:
            logger.warning("BlobStore release skipped (project_id=%s): %s", project_id, exc)
            return 0

    def _release_project_files_sync(self, project_id: str) -> int:
        import psycopg

        removed = 0
        with psycopg.connect(self.settings.database_url, connect_timeout=1) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT blob_hash FROM project_files WHERE project_id=%s",
                    (project_id,),
                )
                hashes = [str(r[0]) for r in (cur.fetchall() or [])]
                cur.execute("DELETE FROM project_files WHERE project_id=%s", (project_id,))
                removed = int(cur.rowcount or 0)

                for h in hashes:
                    cur.execute(
                        """
                        UPDATE file_blobs
                        SET ref_count = GREATEST(ref_count - 1, 0),
                            last_accessed_at = NOW()
                        WHERE hash=%s;
                        """,
                        (h,),
                    )
            conn.commit()
        return removed

    async def gc_unreferenced(self, *, limit: int = 1000, dry_run: bool = True) -> int:
        """Delete blobs with ref_count=0 from disk and remove their DB rows."""
        try:
            await self._ensure_schema()
            return int(await asyncio.to_thread(self._gc_unreferenced_sync, int(limit), bool(dry_run)))
        except Exception as exc:
            logger.warning("BlobStore gc skipped: %s", exc)
            return 0

    def _gc_unreferenced_sync(self, limit: int, dry_run: bool) -> int:
        import psycopg

        deleted = 0
        with psycopg.connect(self.settings.database_url, connect_timeout=1) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT hash
                    FROM file_blobs
                    WHERE ref_count <= 0
                    ORDER BY last_accessed_at ASC
                    LIMIT %s;
                    """,
                    (int(limit),),
                )
                hashes = [str(r[0]) for r in (cur.fetchall() or [])]

                for h in hashes:
                    path = self.blob_path(h)
                    if not dry_run:
                        try:
                            if path.exists():
                                path.unlink()
                        except Exception:
                            continue

                    if not dry_run:
                        cur.execute("DELETE FROM file_blobs WHERE hash=%s AND ref_count <= 0", (h,))
                    deleted += 1
            if not dry_run:
                conn.commit()
        return deleted
