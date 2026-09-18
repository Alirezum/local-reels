import pytest


@pytest.mark.parametrize("field", ["video_dir", "db_path"])
@pytest.mark.parametrize("kind", ["relative", "absolute", "home", "empty"])
def test_settings_resolve_paths_from_project_root(sandbox, monkeypatch, field, kind):
    from backend.app import config

    project_root = sandbox.root / "project"
    home = sandbox.root / "home"
    monkeypatch.setattr(config, "PROJECT_ROOT", project_root)
    monkeypatch.setenv("HOME", str(home))
    value, expected = {
        "relative": ("nested/../target", project_root / "target"),
        "absolute": (str(sandbox.root / "target"), sandbox.root / "target"),
        "home": ("~/nested/../target", home / "target"),
        "empty": ("", project_root),
    }[kind]
    settings = config.Settings(_env_file=None, **{field: value})
    assert getattr(settings, f"resolved_{field}")() == expected.resolve()


def test_config_persists_and_controls_subsequent_scans(client, sandbox, library, sql):
    replacement = sandbox.root / "replacement"
    replacement.mkdir()
    (replacement / "new.jpg").write_bytes(b"image")
    response = client.post("/api/config", json={"video_dir": "replacement"})
    expected = {"video_dir": str(replacement), "exists": True, "video_count": 1}
    assert response.status_code == 200
    assert response.json() == expected
    assert sql("SELECT key, value FROM config") == [{"key": "video_dir", "value": str(replacement)}]
    assert client.get("/api/config").json() == expected
    (replacement / "later.mp4").write_bytes(b"later")
    assert [item["relpath"] for item in client.get("/api/videos").json()] == [
        "later.mp4",
        "new.jpg",
    ]
    assert client.get("/api/config").json()["video_count"] == 2
    assert client.get("/videos/new.jpg").content == b"image"
    assert client.get("/videos/root.mp4").status_code == 404
    assert sql("SELECT COUNT(*) AS count FROM videos WHERE removed = 1") == [{"count": 4}]


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_invalid_config_preserves_current_directory(client, sandbox, library, sql, kind):
    previous = client.get("/api/config").json()
    candidate = sandbox.root / kind
    if kind == "file":
        candidate.write_bytes(b"not a directory")
    response = client.post("/api/config", json={"video_dir": str(candidate)})
    assert response.status_code == 400
    assert response.json() == {"detail": f"Not a valid directory: {candidate}"}
    assert client.get("/api/config").json() == previous
    assert sql("SELECT * FROM config") == []
    assert len(client.get("/api/videos").json()) == 4


@pytest.mark.parametrize("payload", [{}, {"video_dir": None}, {"video_dir": 123}])
def test_config_schema_validation(client, payload):
    assert client.post("/api/config", json=payload).status_code == 422
