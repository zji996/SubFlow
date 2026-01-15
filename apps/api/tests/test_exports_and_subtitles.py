from __future__ import annotations

from pathlib import Path

from subflow.models.segment import ASRCorrectedSegment, ASRSegment, SemanticChunk, TranslationChunk
from subflow.models.project import ProjectStatus


def _set_project_stage(pool, project_id: str, stage: int) -> None:  # noqa: ANN001
    proj = pool.projects.get(str(project_id))
    assert proj is not None
    proj.current_stage = int(stage)
    proj.status = ProjectStatus.COMPLETED


def _seed_subtitle_materials(pool, project_id: str) -> None:  # noqa: ANN001
    asr_segments = [
        ASRSegment(id=0, start=0.0, end=1.0, text="a", language="en"),
        ASRSegment(id=1, start=1.0, end=2.0, text="b", language="en"),
    ]
    chunks = [
        SemanticChunk(
            id=0,
            text="a b",
            translation="甲乙",
            asr_segment_ids=[0, 1],
            translation_chunks=[
                TranslationChunk(text="甲", segment_id=0),
                TranslationChunk(text="乙", segment_id=1),
            ],
        )
    ]
    pid = str(project_id)
    pool.asr_segments[pid] = list(asr_segments)
    pool.asr_corrections[pid] = {0: "A"}
    pool.semantic_chunks[pid] = list(chunks)


def _seed_custom_subtitle_materials(
    pool,  # noqa: ANN001
    project_id: str,
    *,
    translation: str,
    chunks: list[TranslationChunk],
) -> None:
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
    pid = str(project_id)
    pool.asr_segments[pid] = list(asr_segments)
    pool.asr_corrections[pid] = {0: str(corrected[0].text)}
    pool.semantic_chunks[pid] = list(semantic_chunks)


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
    _set_project_stage(client.app.state.db_pool, pid, 5)

    res = client.post(
        f"/projects/{pid}/exports",
        json={
            "format": "srt",
            "content": "both",
            "primary_position": "top",
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
    _seed_subtitle_materials(client.app.state.db_pool, pid)

    res = client.get(f"/projects/{pid}/subtitles/preview")
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 2

    _set_project_stage(client.app.state.db_pool, pid, 5)

    res = client.get(
        f"/projects/{pid}/subtitles/download?format=srt&content=both&primary_position=top"
    )
    assert res.status_code == 200
    assert "甲" in res.text

    res = client.post(
        f"/projects/{pid}/exports",
        json={
            "format": "srt",
            "content": "both",
            "primary_position": "top",
        },
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
    assert payload["computed_entries"][0]["primary"] == "甲"
    assert payload["computed_entries"][0]["secondary"] == "A"


def test_exports_create_from_edited_entries_propagates_per_chunk_group(
    client, redis, settings
) -> None:
    res = client.post(
        "/projects",
        json={"name": "demo", "media_url": "https://example.com/v.mp4", "target_language": "zh"},
    )
    pid = res.json()["id"]
    _seed_custom_subtitle_materials(
        client.app.state.db_pool,
        pid,
        translation="甲乙丙丁",
        chunks=[
            TranslationChunk(text="共用", segment_id=0),
            TranslationChunk(text="共用", segment_id=1),
        ],
    )
    _set_project_stage(client.app.state.db_pool, pid, 5)

    res = client.post(
        f"/projects/{pid}/exports",
        json={
            "format": "srt",
            "content": "both",
            "primary_position": "top",
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
    assert "第一次改" in res.text
    assert "AA" in res.text


def test_exports_create_from_artifacts_legacy_translation_chunks_still_work(
    client, redis, settings
) -> None:
    res = client.post(
        "/projects",
        json={"name": "demo", "media_url": "https://example.com/v.mp4", "target_language": "zh"},
    )
    pid = res.json()["id"]
    _seed_custom_subtitle_materials(
        client.app.state.db_pool,
        pid,
        translation="甲乙丙丁",
        chunks=[
            TranslationChunk(text="共用", segment_id=0),
            TranslationChunk(text="共用", segment_id=1),
        ],
    )
    _set_project_stage(client.app.state.db_pool, pid, 5)

    res = client.post(
        f"/projects/{pid}/exports",
        json={
            "format": "srt",
            "content": "both",
            "primary_position": "top",
        },
    )
    assert res.status_code == 200
    export_id = res.json()["id"]

    res = client.get(f"/projects/{pid}/exports/{export_id}/download")
    assert res.status_code == 200
    assert "共用" in res.text
