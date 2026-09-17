import os

import pytest


def test_scan_caches_duration_and_reprobes_changed_files(client, sandbox, library):
    expected = {
        sandbox.media_dir / "root.mp4",
        sandbox.media_dir / "Alpha/first clip.MP4",
        sandbox.media_dir / "beta/last.webm",
    }
    assert len(sandbox.probes) == 3
    assert set(sandbox.probes) == expected
    assert client.get("/api/videos").status_code == 200
    assert len(sandbox.probes) == 3
    path = sandbox.media_dir / "root.mp4"
    sandbox.durations[path.name] = 24
    path.write_bytes(b"longer than the original")
    updated = {item["relpath"]: item for item in client.get("/api/videos").json()}
    assert sandbox.probes[3:] == [path]
    assert updated["root.mp4"]["duration"] == 24
    assert updated["root.mp4"]["size"] == path.stat().st_size
    assert updated["root.mp4"]["id"] == library["root.mp4"]["id"]
    assert updated["root.mp4"]["created_at"] == library["root.mp4"]["created_at"]
    sandbox.durations[path.name] = 36
    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 10))
    updated = {item["relpath"]: item for item in client.get("/api/videos").json()}
    assert sandbox.probes[4:] == [path]
    assert updated["root.mp4"]["duration"] == 36
    assert client.get("/api/videos").status_code == 200
    assert len(sandbox.probes) == 5


def test_zero_duration_is_reprobed(client, sandbox):
    path = sandbox.media_dir / "unknown.mp4"
    path.write_bytes(b"unknown")
    sandbox.durations[path.name] = 0
    assert client.get("/api/videos").json()[0]["duration"] == 0
    assert client.get("/api/videos").json()[0]["duration"] == 0
    assert sandbox.probes == [path, path]


def test_recursive_scan_skips_hidden_unsupported_and_symlink_directories(client, sandbox):
    for relpath in [
        "visible.MP4",
        "nested/image.jpg",
        ".hidden.mp4",
        ".private/video.mp4",
        "nested/.hidden.png",
        "notes.txt",
    ]:
        path = sandbox.media_dir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data")
    outside = sandbox.root / "outside"
    outside.mkdir()
    (outside / "external.mp4").write_bytes(b"outside")
    (sandbox.media_dir / "linked").symlink_to(outside, target_is_directory=True)
    (sandbox.media_dir / "cycle").symlink_to(sandbox.media_dir, target_is_directory=True)
    items = client.get("/api/videos").json()
    assert [item["relpath"] for item in items] == ["nested/image.jpg", "visible.MP4"]
    assert sandbox.probes == [sandbox.media_dir / "visible.MP4"]


def test_removal_retains_history_and_restoration_retains_identity(client, sandbox, library, sql):
    original = library["root.mp4"]
    video_id = original["id"]
    path = sandbox.media_dir / "root.mp4"
    assert (
        client.post(
            "/api/watch",
            json={
                "video_id": video_id,
                "start_time": 0,
                "end_time": 5,
                "duration_watched": 5,
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/flags",
            json={
                "video_id": video_id,
                "favorite": True,
                "blocked": True,
            },
        ).status_code
        == 200
    )
    path.unlink()
    assert len(client.get("/api/videos").json()) == 3
    assert client.get("/api/blocked").json() == []
    assert client.get(original["url"]).status_code == 404
    assert sql("SELECT removed FROM videos WHERE id = ?", (video_id,)) == [{"removed": 1}]
    assert sql("SELECT COUNT(*) AS count FROM watch_events") == [{"count": 1}]
    assert client.get("/api/stats/summary").json() == {
        "total_watch_seconds": 5,
        "total_views": 1,
        "videos_watched": 1,
    }
    assert client.get("/api/stats/top-videos").json() == [
        {"video_id": video_id, "filename": "root.mp4", "watch_seconds": 5, "views": 1}
    ]
    path.write_bytes(b"restored")
    assert len(client.get("/api/videos").json()) == 3
    assert client.get("/api/blocked").json() == [{"id": video_id, "relpath": "root.mp4"}]
    assert client.post("/api/flags", json={"video_id": video_id, "blocked": False}).json() == {
        "favorite": True,
        "blocked": False,
    }
    restored = client.get("/api/videos", params={"favorites": True}).json()[0]
    assert restored["id"] == video_id
    assert restored["created_at"] == original["created_at"]
    assert sql("SELECT removed FROM videos WHERE id = ?", (video_id,)) == [{"removed": 0}]


@pytest.mark.parametrize("remove_directory", [False, True])
def test_empty_or_missing_directory_marks_all_removed(client, sandbox, sql, remove_directory):
    path = sandbox.media_dir / "only.mp4"
    path.write_bytes(b"only")
    assert len(client.get("/api/videos").json()) == 1
    path.unlink()
    if remove_directory:
        sandbox.media_dir.rmdir()
    assert client.get("/api/videos").json() == []
    assert sql("SELECT removed FROM videos") == [{"removed": 1}]
    assert client.get("/api/config").json() == {
        "video_dir": str(sandbox.media_dir),
        "exists": not remove_directory,
        "video_count": 0,
    }
