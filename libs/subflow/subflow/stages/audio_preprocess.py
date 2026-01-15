"""Audio preprocessing stage."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import cast

import httpx

from subflow.config import Settings
from subflow.exceptions import ConfigurationError, StageExecutionError
from subflow.pipeline.context import PipelineContext, ProgressReporter
from subflow.providers import get_audio_provider
from subflow.services import BlobStore
from subflow.services.blob_store import sha256_file
from subflow.stages.base import Stage

logger = logging.getLogger(__name__)


class AudioPreprocessStage(Stage):
    name = "audio_preprocess"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = get_audio_provider(settings.audio.model_dump())

    def validate_input(self, context: PipelineContext) -> bool:
        run_id = context.get("project_id") or context.get("job_id")
        media_url = context.get("media_url") or context.get("video_url")
        return bool(run_id) and bool(media_url)

    async def execute(
        self,
        context: PipelineContext,
        progress_reporter: ProgressReporter | None = None,
    ) -> PipelineContext:
        run_id = str(context.get("project_id") or context.get("job_id") or "")
        media_url = str(context.get("media_url") or context.get("video_url") or "")
        if not run_id or not media_url:
            raise ConfigurationError("project_id/media_url is required")

        logger.info("audio_preprocess start (project_id=%s)", run_id)

        blob_store = BlobStore(self.settings)

        base_dir = Path(self.settings.data_dir) / "projects" / run_id
        base_dir.mkdir(parents=True, exist_ok=True)
        video_path = base_dir / "input_video"
        audio_path = base_dir / "audio.wav"
        demucs_out = base_dir / "demucs"

        local_video_path = context.get("video_path")
        if local_video_path and Path(str(local_video_path)).exists():
            video_path = Path(str(local_video_path))
            logger.debug("use local video_path=%s", video_path)
        else:
            if Path(media_url).exists():
                video_path = Path(media_url)
                logger.debug("use file media_url=%s", video_path)
                ref = await blob_store.ingest_file(
                    project_id=run_id,
                    file_type="input_video",
                    local_path=str(video_path),
                    original_filename=video_path.name,
                    mime_type=None,
                    move=False,
                )
                video_path = Path(ref.path)
            elif media_url.startswith("http://") or media_url.startswith("https://"):
                suffix = Path(media_url.split("?")[0]).suffix or ".mp4"
                video_path = base_dir / f"input{suffix}"
                try:
                    async with httpx.AsyncClient() as client:
                        async with client.stream("GET", media_url, timeout=600.0) as resp:
                            resp.raise_for_status()
                            h = hashlib.sha256()
                            size = 0
                            content_type = (
                                str(resp.headers.get("Content-Type") or "").strip() or None
                            )
                            with open(video_path, "wb") as f:
                                async for chunk in resp.aiter_bytes():
                                    f.write(chunk)
                                    h.update(chunk)
                                    size += len(chunk)
                except httpx.HTTPError as exc:
                    logger.exception("download failed (media_url=%s)", media_url)
                    raise StageExecutionError(self.name, f"download failed: {exc}") from exc
                logger.info("downloaded media_url to %s", video_path)
                ref = await blob_store.ingest_hashed_file(
                    project_id=run_id,
                    file_type="input_video",
                    local_path=str(video_path),
                    hash_hex=h.hexdigest(),
                    size_bytes=size,
                    original_filename=video_path.name,
                    mime_type=content_type,
                    move=True,
                )
                video_path = Path(ref.path)
            else:
                raise ConfigurationError("Unsupported media_url; provide local path or http(s) url")

        await self.provider.extract_audio(str(video_path), str(audio_path))
        logger.info("extracted audio to %s", audio_path)

        context = cast(PipelineContext, dict(context))
        context["video_path"] = str(video_path)

        audio_hash, audio_size = await asyncio.to_thread(sha256_file, audio_path)
        derived_params = {
            "provider": str(self.settings.audio.provider),
            "demucs_bin": str(self.settings.audio.demucs_bin),
            "demucs_model": str(self.settings.audio.demucs_model),
        }
        if bool(self.settings.audio.normalize):
            derived_params["normalize"] = True
            derived_params["normalize_target_db"] = float(self.settings.audio.normalize_target_db)
        cached_vocals_hash = await blob_store.get_derived(
            transform="demucs_vocals",
            src_hash=audio_hash,
            params=derived_params,
        )

        vocals_ref = None
        if cached_vocals_hash:
            cached_path = blob_store.blob_path(cached_vocals_hash)
            if cached_path.exists():
                logger.info(
                    "reuse cached vocals (audio_hash=%s, vocals_hash=%s)",
                    audio_hash,
                    cached_vocals_hash,
                )
                vocals_ref = await blob_store.ingest_hashed_file(
                    project_id=run_id,
                    file_type="vocals",
                    local_path=str(cached_path),
                    hash_hex=str(cached_vocals_hash),
                    size_bytes=int(cached_path.stat().st_size),
                    original_filename="vocals.wav",
                    mime_type="audio/wav",
                    move=False,
                )

        if vocals_ref is None:
            try:
                vocals_path = await self.provider.separate_vocals(str(audio_path), str(demucs_out))
            except Exception as exc:
                logger.exception("demucs separation failed")
                raise StageExecutionError(
                    self.name,
                    "Demucs separation failed. Demucs is required. "
                    "Ensure `demucs` is installed in the worker uv env and runnable, and set "
                    "`CUDA_VISIBLE_DEVICES=1` if GPU0 is occupied.",
                ) from exc

            if bool(self.settings.audio.normalize):
                try:
                    vocals_path = await self.provider.normalize_audio(
                        str(vocals_path),
                        str(vocals_path),
                        target_db=float(self.settings.audio.normalize_target_db),
                    )
                    logger.info(
                        "normalized vocals (target_db=%.2f, path=%s)",
                        float(self.settings.audio.normalize_target_db),
                        vocals_path,
                    )
                except Exception as exc:
                    logger.exception("vocals normalization failed")
                    raise StageExecutionError(
                        self.name,
                        "Audio normalization failed. Ensure `ffmpeg` is installed and runnable, "
                        "or disable via `AUDIO_NORMALIZE=false`.",
                    ) from exc

        audio_ref = await blob_store.ingest_hashed_file(
            project_id=run_id,
            file_type="audio",
            local_path=str(audio_path),
            hash_hex=audio_hash,
            size_bytes=audio_size,
            original_filename="audio.wav",
            mime_type="audio/wav",
            move=True,
        )

        if vocals_ref is None:
            vocals_ref = await blob_store.ingest_file(
                project_id=run_id,
                file_type="vocals",
                local_path=str(vocals_path),
                original_filename="vocals.wav",
                mime_type="audio/wav",
                move=True,
            )
            await blob_store.set_derived(
                transform="demucs_vocals",
                src_hash=audio_hash,
                dst_hash=str(vocals_ref.blob_hash),
                params=derived_params,
            )
        context["audio_path"] = str(audio_ref.path)
        context["vocals_audio_path"] = str(vocals_ref.path)
        logger.info("audio_preprocess done (vocals_audio_path=%s)", vocals_ref.path)
        return context
