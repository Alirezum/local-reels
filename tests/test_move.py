import pytest


def test_move_to_existing_folder_updates_library(client, sandbox, library, sql):
    root_id = library["root.mp4"]["id"]
    response = client.post("/api/videos/move", json={"video_id": root_id, "folder": "Alpha"})
    assert response.status_code == 200
    body = response.json()
    assert body["relpath"] == "Alpha/root.mp4"
    assert not (sandbox.media_dir / "root.mp4").exists()
    assert (sandbox.media_dir / "Alpha" / "root.mp4").is_file()
    rows = sql("SELECT id, filename, path FROM videos WHERE filename = 'Alpha/root.mp4'")
    assert len(rows) == 1
    assert rows[0]["path"] == str(sandbox.media_dir / "Alpha" / "root.mp4")
    listing = {item["relpath"]: item for item in client.get("/api/videos").json()}
    assert set(listing) == {
        "Alpha/root.mp4",
        "Alpha/first clip.MP4",
        "Alpha/nested/photo.PNG",
        "beta/last.webm",
    }
    folders = client.get("/api/videos/folders").json()
    assert folders == [{"name": "Alpha", "count": 3}, {"name": "beta", "count": 1}]


def test_move_preserves_history_flags_and_created_at(client, sandbox, library, sql):
    root_id = library["root.mp4"]["id"]
    original_created = library["root.mp4"]["created_at"]
    assert (
        client.post(
            "/api/watch",
            json={"video_id": root_id, "start_time": 0, "end_time": 5, "duration_watched": 5},
        ).status_code
        == 200
    )
    assert (
        client.post("/api/flags", json={"video_id": root_id, "favorite": True}).status_code == 200
    )
    response = client.post("/api/videos/move", json={"video_id": root_id, "folder": "beta"})
    assert response.status_code == 200
    new_id = response.json()["id"]
    assert new_id != root_id
    assert sql("SELECT COUNT(*) AS n FROM watch_events WHERE video_id = ?", (new_id,)) == [{"n": 1}]
    assert sql("SELECT COUNT(*) AS n FROM watch_events WHERE video_id = ?", (root_id,)) == [
        {"n": 0}
    ]
    assert sql("SELECT favorite FROM user_flags WHERE video_id = ?", (new_id,)) == [{"favorite": 1}]
    assert sql("SELECT COUNT(*) AS n FROM user_flags WHERE video_id = ?", (root_id,)) == [{"n": 0}]
    stats = client.get("/api/stats/summary").json()
    assert stats == {"total_watch_seconds": 5, "total_views": 1, "videos_watched": 1}
    favorites = client.get("/api/videos", params={"favorites": True}).json()
    assert [item["relpath"] for item in favorites] == ["beta/root.mp4"]
    listing = {item["relpath"]: item for item in client.get("/api/videos").json()}
    assert listing["beta/root.mp4"]["created_at"] == original_created
    assert listing["beta/root.mp4"]["favorite"] is True


def test_move_to_root_and_rescan_stability(client, sandbox, library):
    nested_id = library["Alpha/first clip.MP4"]["id"]
    response = client.post("/api/videos/move", json={"video_id": nested_id, "folder": ""})
    assert response.status_code == 200
    assert response.json()["relpath"] == "first clip.MP4"
    assert not (sandbox.media_dir / "Alpha" / "first clip.MP4").exists()
    assert (sandbox.media_dir / "first clip.MP4").is_file()
    before = {item["relpath"] for item in client.get("/api/videos").json()}
    assert client.get("/api/videos").json() == client.get("/api/videos").json()
    after = {item["relpath"] for item in client.get("/api/videos").json()}
    assert (
        before
        == after
        == {
            "first clip.MP4",
            "root.mp4",
            "Alpha/nested/photo.PNG",
            "beta/last.webm",
        }
    )
    assert (
        client.post("/api/videos/move", json={"video_id": nested_id, "folder": "Alpha"}).status_code
        == 404
    )


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"video_id": "unknown-id", "folder": "Alpha"}, 404),
        ({"video_id": "missing", "folder": ""}, 404),
        ({"video_id": "", "folder": ""}, 404),
    ],
)
def test_move_unknown_video(client, library, payload, status):
    assert client.post("/api/videos/move", json=payload).status_code == status


def test_move_rejects_traversal_and_bad_names(client, sandbox, library, sql):
    root_id = library["root.mp4"]["id"]
    for folder in ["../outside", "..", "Alpha/nested", ".hidden", "a/b"]:
        response = client.post("/api/videos/move", json={"video_id": root_id, "folder": folder})
        assert response.status_code == 400, folder
    assert (sandbox.media_dir / "root.mp4").is_file()
    assert sql("SELECT COUNT(*) AS n FROM videos WHERE removed = 0") == [{"n": 4}]


def test_move_conflict_target_file_exists(client, sandbox, library, sql):
    root_id = library["root.mp4"]["id"]
    (sandbox.media_dir / "beta" / "root.mp4").write_bytes(b"target already there")
    response = client.post("/api/videos/move", json={"video_id": root_id, "folder": "beta"})
    assert response.status_code == 409
    assert (sandbox.media_dir / "root.mp4").is_file()
    row = sql("SELECT COUNT(*) AS n FROM videos WHERE filename = 'beta/root.mp4'")
    assert row == [{"n": 0}]


def test_move_missing_source_falls_back_to_root_path(client, sandbox, library, sql):
    root_id = library["root.mp4"]["id"]
    stale = sandbox.root / "elsewhere.mp4"
    stale.write_bytes(b"moved earlier")
    sql("UPDATE videos SET path = ? WHERE id = ?", (str(stale), root_id))
    response = client.post("/api/videos/move", json={"video_id": root_id, "folder": "beta"})
    assert response.status_code == 200
    assert not stale.exists()
    assert (sandbox.media_dir / "beta" / "root.mp4").is_file()
    assert sql("SELECT path FROM videos WHERE id = ?", (response.json()["id"],))[0]["path"] == str(
        sandbox.media_dir / "beta" / "root.mp4"
    )


def test_move_image_and_folder_counts_update(client, sandbox, library):
    photo_id = library["Alpha/nested/photo.PNG"]["id"]
    response = client.post("/api/videos/move", json={"video_id": photo_id, "folder": "beta"})
    assert response.status_code == 200
    assert response.json()["relpath"] == "beta/photo.PNG"
    folders = {f["name"]: f["count"] for f in client.get("/api/videos/folders").json()}
    assert folders == {"Alpha": 1, "beta": 2, "(root)": 1}
    assert client.get(f"/videos/{'beta/photo.PNG'}").status_code == 200
