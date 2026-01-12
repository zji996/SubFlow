from __future__ import annotations


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
