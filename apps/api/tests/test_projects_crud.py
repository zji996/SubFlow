from __future__ import annotations

from subflow.models.project import ProjectStatus, StageName, StageRun, StageRunStatus


def test_projects_crud_flow(client, monkeypatch) -> None:
    async def _noop_release(self, project_id: str) -> int:  # noqa: ARG001
        return 0

    monkeypatch.setattr(
        "subflow.services.blob_store.BlobStore.release_project_files", _noop_release
    )

    res = client.post(
        "/projects",
        json={"name": "demo", "media_url": "https://example.com/v.mp4", "target_language": "zh"},
    )
    assert res.status_code == 200
    proj = res.json()
    pid = proj["id"]

    res = client.get("/projects")
    assert res.status_code == 200
    assert any(p["id"] == pid for p in res.json())

    res = client.get(f"/projects/{pid}")
    assert res.status_code == 200
    assert res.json()["name"] == "demo"

    res = client.delete(f"/projects/{pid}")
    assert res.status_code == 200
    assert res.json()["deleted"] is True

    res = client.get(f"/projects/{pid}")
    assert res.status_code == 404


def test_run_rejects_export_stage(client) -> None:
    res = client.post(
        "/projects",
        json={"name": "demo", "media_url": "https://example.com/v.mp4", "target_language": "zh"},
    )
    pid = res.json()["id"]
    res = client.post(f"/projects/{pid}/run", json={"stage": "export"})
    assert res.status_code == 400


def test_retry_rejects_when_no_failed_stage(client) -> None:
    res = client.post(
        "/projects",
        json={"name": "demo", "media_url": "https://example.com/v.mp4", "target_language": "zh"},
    )
    pid = res.json()["id"]
    res = client.post(f"/projects/{pid}/retry", json={})
    assert res.status_code == 409


def test_retry_enqueues_retry_stage_task(client, redis, db_pool) -> None:
    res = client.post(
        "/projects",
        json={"name": "demo", "media_url": "https://example.com/v.mp4", "target_language": "zh"},
    )
    pid = res.json()["id"]
    db_pool.projects[pid].status = ProjectStatus.FAILED
    db_pool.projects[pid].current_stage = 4
    db_pool.stage_runs[(pid, StageName.ASR.value)] = StageRun(
        stage=StageName.ASR, status=StageRunStatus.FAILED
    )

    res = client.post(f"/projects/{pid}/retry", json={})
    assert res.status_code == 200

    items = redis.dump_queue("subflow:projects:queue")
    assert items and items[0]["type"] == "retry_stage"
    assert items[0]["project_id"] == pid
    assert items[0]["stage"] == StageName.ASR.value


def test_run_next_on_failed_project_targets_failed_stage(client, redis, db_pool) -> None:
    res = client.post(
        "/projects",
        json={"name": "demo", "media_url": "https://example.com/v.mp4", "target_language": "zh"},
    )
    pid = res.json()["id"]
    db_pool.projects[pid].status = ProjectStatus.FAILED
    db_pool.projects[pid].current_stage = 4
    db_pool.stage_runs[(pid, StageName.ASR.value)] = StageRun(
        stage=StageName.ASR, status=StageRunStatus.FAILED
    )

    res = client.post(f"/projects/{pid}/run", json={})
    assert res.status_code == 200

    items = redis.dump_queue("subflow:projects:queue")
    assert items and items[0]["type"] == "run_stage"
    assert items[0]["stage"] == StageName.ASR.value
