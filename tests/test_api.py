import re
from unittest.mock import Mock

import pytest


def test_health_and_empty_library(client, sandbox):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    for endpoint in (
        "/api/videos",
        "/api/videos/random",
        "/api/videos/folders",
        "/api/blocked",
    ):
        response = client.get(endpoint)
        assert response.status_code == 200
        assert response.json() == []
    assert client.get("/api/config").json() == {
        "video_dir": str(sandbox.media_dir),
        "exists": True,
        "video_count": 0,
    }


def test_listing_metadata_and_folders(client, library):
    assert list(library) == sorted(library)
    video = library["Alpha/first clip.MP4"]
    assert video == {
        "id": video["id"],
        "filename": "first clip.MP4",
        "relpath": "Alpha/first clip.MP4",
        "type": "video",
        "url": "/videos/Alpha/first%20clip.MP4",
        "duration": 12.5,
        "size": 5,
        "favorite": False,
        "created_at": video["created_at"],
    }
    assert re.fullmatch(r"[0-9a-f]{16}", video["id"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", video["created_at"])
    image = library["Alpha/nested/photo.PNG"]
    assert image["type"] == "image"
    assert image["duration"] == 0
    assert image["filename"] == "photo.PNG"
    assert client.get("/api/videos/folders").json() == [
        {"name": "Alpha", "count": 2},
        {"name": "beta", "count": 1},
        {"name": "(root)", "count": 1},
    ]


@pytest.mark.parametrize(
    ("folder", "expected"),
    [
        ("(root)", ["root.mp4"]),
        ("Alpha", ["Alpha/first clip.MP4", "Alpha/nested/photo.PNG"]),
        ("Alpha/nested", ["Alpha/nested/photo.PNG"]),
        ("missing", []),
    ],
)
def test_folder_filter(client, library, folder, expected):
    response = client.get("/api/videos", params={"folder": folder})
    assert response.status_code == 200
    assert [item["relpath"] for item in response.json()] == expected


def test_flags_partial_updates_and_filtering(client, library):
    video_id = library["Alpha/first clip.MP4"]["id"]

    def update(**fields):
        response = client.post("/api/flags", json={"video_id": video_id, **fields})
        assert response.status_code == 200
        return response.json()

    assert update(favorite=True) == {"favorite": True, "blocked": False}
    favorites = client.get("/api/videos", params={"favorites": True}).json()
    assert [item["id"] for item in favorites] == [video_id]
    assert favorites[0]["favorite"] is True
    assert client.get("/api/videos", params={"favorites": True, "folder": "beta"}).json() == []
    assert update(blocked=True) == {"favorite": True, "blocked": True}
    assert client.get("/api/videos", params={"favorites": True}).json() == []
    assert video_id not in {item["id"] for item in client.get("/api/videos").json()}
    assert client.get("/api/blocked").json() == [
        {"id": video_id, "relpath": "Alpha/first clip.MP4"}
    ]
    assert client.get("/api/videos/folders").json()[0] == {"name": "Alpha", "count": 1}
    assert client.get("/api/config").json()["video_count"] == 3
    assert update(favorite=False) == {"favorite": False, "blocked": True}
    assert update(favorite=True, blocked=None) == {"favorite": True, "blocked": True}
    assert update(blocked=False) == {"favorite": True, "blocked": False}
    assert client.get("/api/blocked").json() == []
    assert update(favorite=False, blocked=False) == {
        "favorite": False,
        "blocked": False,
    }


@pytest.mark.parametrize(
    ("payload", "status", "detail"),
    [
        ({"video_id": "unknown", "favorite": True}, 404, "Unknown video_id"),
        ({"video_id": "unknown"}, 400, "Nothing to update"),
        (
            {"video_id": "unknown", "favorite": None, "blocked": None},
            400,
            "Nothing to update",
        ),
        ({"favorite": True}, 422, None),
    ],
)
def test_invalid_flags(client, payload, status, detail):
    response = client.post("/api/flags", json=payload)
    assert response.status_code == status
    if detail:
        assert response.json() == {"detail": detail}


@pytest.mark.parametrize("order", ["random", "weighted"])
def test_random_membership_limits_and_filters(client, library, order):
    blocked_id = library["beta/last.webm"]["id"]
    favorite_id = library["Alpha/first clip.MP4"]["id"]
    assert (
        client.post("/api/flags", json={"video_id": blocked_id, "blocked": True}).status_code == 200
    )
    assert (
        client.post("/api/flags", json={"video_id": favorite_id, "favorite": True}).status_code
        == 200
    )
    assert (
        client.post(
            "/api/watch",
            json={
                "video_id": favorite_id,
                "start_time": 0,
                "end_time": 5,
                "duration_watched": 5,
            },
        ).status_code
        == 200
    )
    expected = {item["id"] for item in library.values()} - {blocked_id}
    response = client.get("/api/videos/random", params={"order": order})
    assert response.status_code == 200
    items = response.json()
    assert len(items) == len(expected)
    assert {item["id"] for item in items} == expected
    limited = client.get("/api/videos/random", params={"order": order, "limit": 2}).json()
    assert len(limited) == len({item["id"] for item in limited}) == 2
    assert {item["id"] for item in limited} <= expected
    filtered = client.get(
        "/api/videos/random",
        params={
            "order": order,
            "folder": "Alpha",
            "favorites": True,
        },
    ).json()
    assert [item["id"] for item in filtered] == [favorite_id]
    assert (
        client.get("/api/videos/random", params={"order": order, "folder": "missing"}).json() == []
    )


@pytest.mark.parametrize(
    ("count", "weights", "fraction", "expected", "totals", "shuffles"),
    [
        (0, {}, 0, [], [], 0),
        (1, {}, 0, ["0"], [1.0], 0),
        (3, {}, 0, ["0", "1", "2"], [3.0, 2.0, 1.0], 0),
        (3, {}, 1, ["2", "1", "0"], [3.0, 2.0, 1.0], 0),
        (3, {}, 2, ["2", "1", "0"], [3.0, 2.0, 1.0], 0),
        (3, {"0": 0.0, "1": 0.0, "2": 0.0}, 0, ["2", "1", "0"], [], 1),
        (3, {"0": -3.0}, 0, ["2", "1", "0"], [], 1),
        (3, {"0": 0.0}, 0, ["0", "1", "2"], [2.0, 2.0, 1.0], 0),
        (3, {"0": 0.0, "1": 2.0, "2": 0.0}, 1, ["1", "2", "0"], [2.0], 1),
    ],
)
def test_weighted_sampling_edges(
    sandbox, monkeypatch, count, weights, fraction, expected, totals, shuffles
):
    from backend.app import videos
    from backend.app.schemas import VideoOut

    items = [
        VideoOut(
            id=str(index),
            filename=f"{index}.mp4",
            relpath=f"{index}.mp4",
            type="video",
            url=f"/videos/{index}.mp4",
            duration=0,
            size=0,
            created_at="2026-01-01T00:00:00Z",
        )
        for index in range(count)
    ]
    original_items = list(items)
    original_weights = dict(weights)
    uniform = Mock(side_effect=lambda start, total: total * fraction)
    shuffle = Mock(side_effect=lambda pool: pool.reverse())
    monkeypatch.setattr(videos.random, "uniform", uniform)
    monkeypatch.setattr(videos.random, "shuffle", shuffle)

    result = videos.weighted_sample_without_replacement(items, weights)

    assert [item.id for item in result] == expected
    assert items == original_items
    assert weights == original_weights
    assert result is not items
    assert [call.args for call in uniform.call_args_list] == [(0, total) for total in totals]
    assert shuffle.call_count == shuffles


@pytest.mark.parametrize(
    ("endpoint", "params"),
    [
        ("/api/videos/random", {"limit": 0}),
        ("/api/videos/random", {"limit": 501}),
        ("/api/videos/random", {"order": "invalid"}),
        ("/api/videos", {"favorites": "invalid"}),
        ("/api/stats/top-videos", {"limit": 0}),
        ("/api/stats/top-videos", {"limit": 101}),
        ("/api/stats/daily", {"days": 0}),
        ("/api/stats/daily", {"days": 366}),
        ("/api/stats/folders", {"days": 0}),
        ("/api/stats/folders", {"days": 366}),
    ],
)
def test_query_validation(client, endpoint, params):
    assert client.get(endpoint, params=params).status_code == 422
