from __future__ import annotations

import argparse
import asyncio
import uuid
from pathlib import Path

from subflow.config import Settings
from subflow.models.project import Project, StageName
from subflow.pipeline import PipelineOrchestrator
from subflow.repositories import (
    ASRSegmentRepository,
    DatabasePool,
    GlobalContextRepository,
    ProjectRepository,
    SemanticChunkRepository,
    StageRunRepository,
    VADSegmentRepository,
)
from subflow.storage import get_artifact_store


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SubFlow pipeline on a local media file.")
    parser.add_argument("--media", required=True, help="Path to local video/audio file")
    parser.add_argument("--name", default="local-run", help="Project name")
    parser.add_argument("--project-id", default=None, help="Project id (defaults to random uuid)")
    parser.add_argument("--source-language", default=None, help="Source language code (optional)")
    parser.add_argument("--target-language", default="zh", help="Target language code")
    parser.add_argument("--max-duration-s", type=float, default=None, help="Only process first N seconds")
    parser.add_argument(
        "--max-asr-segments",
        type=int,
        default=None,
        help="Only keep first N ASR segments for LLM/export",
    )
    parser.add_argument("--skip-demucs", action="store_true", help="Skip vocal separation")
    parser.add_argument("--vad-device", default=None, help="VAD device, e.g. cpu/cuda")
    parser.add_argument(
        "--from-stage",
        choices=[s.value for s in StageName],
        default=None,
        help="Resume from a stage (re-run from this stage)",
    )
    return parser.parse_args()


async def _run() -> int:
    args = _parse_args()
    media_path = Path(args.media)
    if not media_path.exists():
        raise SystemExit(f"Media not found: {media_path}")

    settings = Settings()
    if args.max_duration_s is not None:
        settings.audio.max_duration_s = float(args.max_duration_s)
    if args.skip_demucs:
        settings.audio.skip_demucs = True
    if args.max_asr_segments is not None:
        settings.llm_limits.max_asr_segments = int(args.max_asr_segments)
    if args.vad_device is not None:
        settings.vad.nemo_device = str(args.vad_device)

    project_id = str(args.project_id or uuid.uuid4())
    project = Project(
        id=project_id,
        name=str(args.name),
        media_url=str(media_path),
        source_language=args.source_language,
        target_language=str(args.target_language),
    )

    pool = await DatabasePool.get_pool(settings)
    project_repo = ProjectRepository(pool)
    stage_run_repo = StageRunRepository(pool)
    vad_repo = VADSegmentRepository(pool)
    asr_repo = ASRSegmentRepository(pool)
    global_context_repo = GlobalContextRepository(pool)
    semantic_chunk_repo = SemanticChunkRepository(pool)
    existing = await project_repo.get(project.id)
    if existing is None:
        await project_repo.create(project)
    else:
        project = existing

    store = get_artifact_store(settings)
    orchestrator = PipelineOrchestrator(
        settings,
        store=store,
        project_repo=project_repo,
        stage_run_repo=stage_run_repo,
        vad_repo=vad_repo,
        asr_repo=asr_repo,
        global_context_repo=global_context_repo,
        semantic_chunk_repo=semantic_chunk_repo,
    )
    from_stage = StageName(str(args.from_stage)) if args.from_stage else None
    project, _ = await orchestrator.run_all(project, from_stage=from_stage)

    print(f"project_id={project.id} status={project.status.value} current_stage={project.current_stage}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
