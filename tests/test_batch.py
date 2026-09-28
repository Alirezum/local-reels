import json

TODAY = "2026-09-22"
YESTERDAY = "2026-09-21"


def _ids(batch):
    return [item["id"] for item in batch["videos"]]


def test_get_missing_batch_is_404(client):
    assert client.get("/api/batch", params={"date": TODAY}).status_code == 404
    assert client.get("/api/batch/previous", params={"before": TODAY}).status_code == 404


def test_new_and_get_batch(client, library):
    response = client.post("/api/batch/new", json={"date": TODAY, "size": 2})
    assert response.status_code == 200
    batch = response.json()
    assert batch["date"] == TODAY
    assert batch["size"] == 2
    assert batch["folder"] is None
    assert len(batch["videos"]) == 2
    assert len(set(_ids(batch))) == 2

    fetched = client.get("/api/batch", params={"date": TODAY}).json()
    assert _ids(fetched) == _ids(batch)  # stable order, not reshuffled


def test_new_batch_size_clamped_to_library(client, library):
    batch = client.post("/api/batch/new", json={"date": TODAY, "size": 500}).json()
    assert len(batch["videos"]) == len(library)


def test_new_batch_folder_scope(client, library):
    batch = client.post(
        "/api/batch/new", json={"date": TODAY, "size": 10, "folder": "Alpha"}
    ).json()
    assert batch["folder"] == "Alpha"
    assert {item["relpath"] for item in batch["videos"]} <= {
        "Alpha/first clip.MP4",
        "Alpha/nested/photo.PNG",
    }


def test_new_batch_empty_scope_is_400(client, library):
    response = client.post("/api/batch/new", json={"date": TODAY, "size": 5, "folder": "missing"})
    assert response.status_code == 400


def test_new_batch_excludes_blocked(client, library):
    blocked_id = library["beta/last.webm"]["id"]
    client.post("/api/flags", json={"video_id": blocked_id, "blocked": True})
    batch = client.post("/api/batch/new", json={"date": TODAY, "size": 10}).json()
    assert blocked_id not in _ids(batch)


def test_continue_copies_previous_batch(client, library):
    first = client.post("/api/batch/new", json={"date": YESTERDAY, "size": 2}).json()
    continued = client.post(
        "/api/batch/continue", json={"date": TODAY, "from_date": YESTERDAY}
    ).json()
    assert _ids(continued) == _ids(first)
    assert continued["date"] == TODAY


def test_continue_missing_source_is_404(client):
    response = client.post("/api/batch/continue", json={"date": TODAY, "from_date": YESTERDAY})
    assert response.status_code == 404


def test_previous_returns_most_recent(client, library):
    client.post("/api/batch/new", json={"date": "2026-09-19", "size": 1})
    latest = client.post("/api/batch/new", json={"date": YESTERDAY, "size": 1}).json()
    previous = client.get("/api/batch/previous", params={"before": TODAY}).json()
    assert previous["date"] == latest["date"]


def test_add_random_appends_without_duplicates(client, library):
    batch = client.post("/api/batch/new", json={"date": TODAY, "size": 2}).json()
    grown = client.post("/api/batch/add-random", json={"date": TODAY}).json()
    assert len(grown["videos"]) == 3
    assert _ids(grown)[:2] == _ids(batch)
    assert len(set(_ids(grown))) == 3


def test_add_random_exhausted_is_400(client, library):
    client.post("/api/batch/new", json={"date": TODAY, "size": 500})
    response = client.post("/api/batch/add-random", json={"date": TODAY})
    assert response.status_code == 400


def test_remove_from_batch(client, library):
    batch = client.post("/api/batch/new", json={"date": TODAY, "size": 3}).json()
    victim = _ids(batch)[0]
    shrunk = client.delete(f"/api/batch/{TODAY}/{victim}").json()
    assert victim not in _ids(shrunk)
    assert len(shrunk["videos"]) == 2
    # persisted
    fetched = client.get("/api/batch", params={"date": TODAY}).json()
    assert victim not in _ids(fetched)


def test_remove_unknown_video_is_404(client, library):
    client.post("/api/batch/new", json={"date": TODAY, "size": 1})
    assert client.delete(f"/api/batch/{TODAY}/nope").status_code == 404


def test_batch_validation(client):
    assert client.get("/api/batch", params={"date": "yesterday"}).status_code == 422
    assert client.post("/api/batch/new", json={"date": TODAY, "size": 0}).status_code == 422
    assert client.post("/api/batch/new", json={"date": TODAY, "size": 501}).status_code == 422


def test_deleted_file_drops_out_of_batch(client, library, sandbox, sql):
    batch = client.post("/api/batch/new", json={"date": TODAY, "size": 10}).json()
    assert len(batch["videos"]) == len(library)
    (sandbox.media_dir / "root.mp4").unlink()
    fetched = client.get("/api/batch", params={"date": TODAY}).json()
    assert len(fetched["videos"]) == len(library) - 1
    # stored ID list is untouched; only resolution filters
    stored = sql("SELECT video_ids FROM daily_batches WHERE date = ?", (TODAY,))
    assert len(json.loads(stored[0]["video_ids"])) == len(library)
