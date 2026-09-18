import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    db_path = tmp_path / "database" / "test.db"
    monkeypatch.setenv("VIDEO_DIR", str(media_dir))
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "8000")
    from backend.app import config, db, scan

    settings = config.Settings(
        _env_file=None,
        video_dir=str(media_dir),
        db_path=str(db_path),
        host="127.0.0.1",
        port=8000,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "settings", settings)
    monkeypatch.setattr(db, "settings", settings)
    monkeypatch.setattr(scan, "settings", settings)
    monkeypatch.setattr(db, "_conn", None)
    probes = []
    durations = {}

    async def probe_duration(path):
        probes.append(path)
        return durations.get(path.name, 12.5)

    monkeypatch.setattr(scan, "probe_duration", probe_duration)
    return SimpleNamespace(
        root=tmp_path,
        media_dir=media_dir,
        db_path=db_path,
        probes=probes,
        durations=durations,
    )


@pytest.fixture
def client(sandbox):
    from backend.app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def sql(sandbox):
    def execute(statement, parameters=()):
        with closing(sqlite3.connect(sandbox.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                return [dict(row) for row in conn.execute(statement, parameters).fetchall()]

    return execute


@pytest.fixture
def library(client, sandbox):
    for relpath, content in {
        "root.mp4": b"0123456789",
        "Alpha/first clip.MP4": b"first",
        "Alpha/nested/photo.PNG": b"photo",
        "beta/last.webm": b"last",
    }.items():
        path = sandbox.media_dir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    response = client.get("/api/videos")
    assert response.status_code == 200
    return {item["relpath"]: item for item in response.json()}
