from __future__ import annotations

from pathlib import Path

from subflow.models.project import StageName
from subflow.models.segment import ASRCorrectedSegment, ASRSegment, SemanticChunk, TranslationChunk
from subflow.models.serializers import (
    serialize_asr_corrected_segments,
    serialize_asr_segments,
    serialize_semantic_chunks,
)
from subflow.services.project_store import ProjectStore
from subflow.storage import get_artifact_store


def _set_project_stage(redis, project_id: str, stage: int) -> None:
    store = ProjectStore(redis, ttl_seconds=3600)

    async def _do() -> None:
        project = await store.get(project_id)
        assert project is not None
        project.current_stage = int(stage)
        await store.save(project)

    import anyio

    anyio.run(_do)


def _seed_subtitle_artifacts(settings, project_id: str) -> None:
    store = get_artifact_store(settings)
    asr_segments = [
        ASRSegment(id=0, start=0.0, end=1.0, text="a", language="en"),
        ASRSegment(id=1, start=1.0, end=2.0, text="b", language="en"),
    ]
    corrected = {
        0: ASRCorrectedSegment(id=0, asr_segment_id=0, text="A"),
    }
    chunks = [
        SemanticChunk(
            id=0,
            text="a b",
            translation="甲乙",
            asr_segment_ids=[0, 1],
            translation_chunks=[
                TranslationChunk(text="甲", segment_ids=[0]),
                TranslationChunk(text="乙", segment_ids=[1]),
            ],
        )
    ]

    async def _do() -> None:
        await store.save_json(project_id, StageName.ASR.value, "asr_segments.json", serialize_asr_segments(asr_segments))
        await store.save_json(
            project_id,
            StageName.LLM_ASR_CORRECTION.value,
            "asr_corrected_segments.json",
            serialize_asr_corrected_segments(corrected),
        )
        await store.save_json(project_id, StageName.LLM.value, "semantic_chunks.json", serialize_semantic_chunks(chunks))

    import anyio

    anyio.run(_do)


def _seed_custom_subtitle_artifacts(settings, project_id: str, *, translation: str, chunks: list[TranslationChunk]) -> None:
    store = get_artifact_store(settings)
    asr_segments = [
        ASRSegment(id=0, start=0.0, end=1.0, text="a", language="en"),
        ASRSegment(id=1, start=1.0, end=2.0, text="b", language="en"),
    ]
    corrected = {
        0: ASRCorrectedSegment(id=0, asr_segment_id=0, text="A"),
    }
    semantic_chunks = [
        SemanticChunk(
            id=0,
            text="a b",
            translation=translation,
            asr_segment_ids=[0, 1],
            translation_chunks=chunks,
        )
    ]

    async def _do() -> None:
        await store.save_json(project_id, StageName.ASR.value, "asr_segments.json", serialize_asr_segments(asr_segments))
        await store.save_json(
            project_id,
            StageName.LLM_ASR_CORRECTION.value,
            "asr_corrected_segments.json",
            serialize_asr_corrected_segments(corrected),
        )
        await store.save_json(project_id, StageName.LLM.value, "semantic_chunks.json", serialize_semantic_chunks(semantic_chunks))

    import anyio

    anyio.run(_do)


def test_upload_endpoint_saves_file_locally(client, settings) -> None:
    res = client.post("/upload", files={"file": ("demo.txt", b"hello", "text/plain")})
    assert res.status_code == 200
    payload = res.json()
    assert payload["storage_key"].startswith("uploads/")
    path = Path(payload["media_url"])
    assert path.exists()
    assert path.read_bytes() == b"hello"
    assert payload["size_bytes"] == 5


def test_exports_create_list_download_from_entries(client, redis, settings) -> None:
    res = client.post(
        "/projects",
        json={"name": "demo", "media_url": "https://example.com/v.mp4", "target_language": "zh"},
    )
    pid = res.json()["id"]
    _set_project_stage(redis, pid, 5)

    res = client.post(
        f"/projects/{pid}/exports",
        json={
            "format": "srt",
            "content": "both",
            "primary_position": "top",
            "translation_style": "per_chunk",
            "entries": [
                {"start": 0.0, "end": 1.0, "primary_text": "甲", "secondary_text": "a"},
            ],
        },
    )
    assert res.status_code == 200
    export_id = res.json()["id"]

    res = client.get(f"/projects/{pid}/exports")
    assert res.status_code == 200
    assert any(x["id"] == export_id for x in res.json())

    res = client.get(f"/projects/{pid}/exports/{export_id}/download")
    assert res.status_code == 200
    assert "甲" in res.text


def test_exports_create_from_artifacts_and_subtitle_endpoints(client, redis, settings) -> None:
    res = client.post(
        "/projects",
        json={"name": "demo", "media_url": "https://example.com/v.mp4", "target_language": "zh"},
    )
    pid = res.json()["id"]
    _seed_subtitle_artifacts(settings, pid)

    res = client.get(f"/projects/{pid}/subtitles/preview")
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 2

    _set_project_stage(redis, pid, 5)

    res = client.get(f"/projects/{pid}/subtitles/download?format=srt&content=both&primary_position=top")
    assert res.status_code == 200
    assert "甲" in res.text

    res = client.post(
        f"/projects/{pid}/exports",
        json={"format": "srt", "content": "both", "primary_position": "top", "translation_style": "per_chunk"},
    )
    assert res.status_code == 200
    export_id = res.json()["id"]

    res = client.get(f"/projects/{pid}/exports/{export_id}/download")
    assert res.status_code == 200
    assert "甲" in res.text

    res = client.get(f"/projects/{pid}/subtitles/edit-data")
    assert res.status_code == 200
    payload = res.json()
    assert len(payload["computed_entries"]) == 2
    assert payload["computed_entries"][0]["segment_id"] == 0
    assert payload["computed_entries"][0]["primary_per_chunk"] == "甲"
    assert payload["computed_entries"][0]["primary_full"] == "甲乙"
    assert payload["computed_entries"][0]["primary_per_segment"] == "甲"
    assert payload["computed_entries"][0]["secondary"] == "A"


def test_exports_create_from_edited_entries_propagates_per_chunk_group(client, redis, settings) -> None:
    res = client.post(
        "/projects",
        json={"name": "demo", "media_url": "https://example.com/v.mp4", "target_language": "zh"},
    )
    pid = res.json()["id"]
    _seed_custom_subtitle_artifacts(
        settings,
        pid,
        translation="甲乙丙丁",
        chunks=[TranslationChunk(text="共用", segment_ids=[0, 1])],
    )
    _set_project_stage(redis, pid, 5)

    res = client.post(
        f"/projects/{pid}/exports",
        json={
            "format": "srt",
            "content": "both",
            "primary_position": "top",
            "translation_style": "per_chunk",
            "edited_entries": [
                {"segment_id": 0, "primary": "第一次改", "secondary": "AA"},
                {"segment_id": 1, "primary": "最终改"},
            ],
        },
    )
    assert res.status_code == 200
    export_id = res.json()["id"]

    res = client.get(f"/projects/{pid}/exports/{export_id}/download")
    assert res.status_code == 200
    assert "最终改" in res.text
    assert "第一次改" not in res.text
    assert "AA" in res.text


def test_exports_per_segment_uses_split_full_translation(client, redis, settings) -> None:
    res = client.post(
        "/projects",
        json={"name": "demo", "media_url": "https://example.com/v.mp4", "target_language": "zh"},
    )
    pid = res.json()["id"]
    _seed_custom_subtitle_artifacts(
        settings,
        pid,
        translation="甲乙丙丁",
        chunks=[TranslationChunk(text="共用", segment_ids=[0, 1])],
    )
    _set_project_stage(redis, pid, 5)

    res = client.post(
        f"/projects/{pid}/exports",
        json={
            "format": "srt",
            "content": "both",
            "primary_position": "top",
            "translation_style": "per_segment",
        },
    )
    assert res.status_code == 200
    export_id = res.json()["id"]

    res = client.get(f"/projects/{pid}/exports/{export_id}/download")
    assert res.status_code == 200
    assert "甲乙" in res.text
    assert "丙丁" in res.text
    assert "共用" not in res.text
