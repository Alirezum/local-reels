from datetime import date, datetime, timezone

import pytest


@pytest.fixture
def fixed_stats_clock(monkeypatch, sandbox):
    from backend.app import stats

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 15, 12, tzinfo=timezone.utc).astimezone(tz)

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 15)

    monkeypatch.setattr(stats, "datetime", FixedDatetime)
    monkeypatch.setattr(stats, "date", FixedDate)


def test_empty_stats(client, fixed_stats_clock):
    assert client.get("/api/stats/summary").json() == {
        "total_watch_seconds": 0,
        "total_views": 0,
        "videos_watched": 0,
    }
    assert client.get("/api/stats/top-videos").json() == []
    assert client.get("/api/stats/folders").json() == []
    assert client.get("/api/stats/daily", params={"days": 2}).json() == [
        {"date": "2026-06-14", "watch_seconds": 0, "views": 0},
        {"date": "2026-06-15", "watch_seconds": 0, "views": 0},
    ]


@pytest.mark.parametrize("duration", [0, 4.25, 3600])
def test_watch_persistence(client, library, sql, duration):
    video_id = library["root.mp4"]["id"]
    payload = {
        "video_id": video_id,
        "start_time": 2,
        "end_time": 8,
        "duration_watched": duration,
    }
    response = client.post("/api/watch", json=payload)
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert sql("SELECT video_id, start_time, end_time, duration_watched FROM watch_events") == [
        payload
    ]
    assert client.get("/api/stats/summary").json() == {
        "total_watch_seconds": duration,
        "total_views": 1,
        "videos_watched": 1,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"duration_watched": -1},
        {"duration_watched": 3601},
        {"duration_watched": "bad"},
        {"start_time": None},
        {"end_time": "bad"},
    ],
)
def test_invalid_watch_does_not_write(client, library, sql, changes):
    payload = {
        "video_id": library["root.mp4"]["id"],
        "start_time": 0,
        "end_time": 5,
        "duration_watched": 5,
    }
    response = client.post("/api/watch", json={**payload, **changes})
    assert response.status_code == 422
    assert sql("SELECT * FROM watch_events") == []


@pytest.mark.parametrize("field", ["video_id", "start_time", "end_time", "duration_watched"])
def test_missing_watch_fields(client, library, sql, field):
    payload = {
        "video_id": library["root.mp4"]["id"],
        "start_time": 0,
        "end_time": 5,
        "duration_watched": 5,
    }
    del payload[field]
    assert client.post("/api/watch", json=payload).status_code == 422
    assert sql("SELECT * FROM watch_events") == []


def test_unknown_watch_video(client, sql):
    response = client.post(
        "/api/watch",
        json={
            "video_id": "unknown",
            "start_time": 0,
            "end_time": 1,
            "duration_watched": 1,
        },
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown video_id"}
    assert sql("SELECT * FROM watch_events") == []


def test_session_statistics_and_date_windows(client, library, sql, fixed_stats_clock):
    root_id = library["root.mp4"]["id"]
    nested_id = library["Alpha/first clip.MP4"]["id"]
    for video_id, duration, timestamp in [
        (root_id, 5, "2026-06-13T12:00:00Z"),
        (root_id, 4, "2026-06-15T12:00:00Z"),
        (root_id, 6, "2026-06-15T12:00:10Z"),
        (root_id, 10, "2026-06-15T12:01:00Z"),
        (nested_id, 30, "2026-06-15T12:00:05Z"),
    ]:
        response = client.post(
            "/api/watch",
            json={
                "video_id": video_id,
                "start_time": 0,
                "end_time": duration,
                "duration_watched": duration,
            },
        )
        assert response.status_code == 200
        sql(
            "UPDATE watch_events SET created_at = ? WHERE id = (SELECT MAX(id) FROM watch_events)",
            (timestamp,),
        )
    assert client.get("/api/stats/summary").json() == {
        "total_watch_seconds": 55,
        "total_views": 4,
        "videos_watched": 2,
    }
    top = [
        {
            "video_id": nested_id,
            "filename": "Alpha/first clip.MP4",
            "watch_seconds": 30,
            "views": 1,
        },
        {"video_id": root_id, "filename": "root.mp4", "watch_seconds": 25, "views": 3},
    ]
    assert client.get("/api/stats/top-videos").json() == top
    assert client.get("/api/stats/top-videos", params={"limit": 1}).json() == top[:1]
    assert client.get("/api/stats/daily", params={"days": 3}).json() == [
        {"date": "2026-06-13", "watch_seconds": 5, "views": 1},
        {"date": "2026-06-14", "watch_seconds": 0, "views": 0},
        {"date": "2026-06-15", "watch_seconds": 50, "views": 3},
    ]
    assert client.get("/api/stats/daily", params={"days": 1}).json() == [
        {"date": "2026-06-15", "watch_seconds": 50, "views": 3},
    ]
    assert client.get("/api/stats/folders", params={"days": 1}).json() == [
        {"folder": "Alpha", "watch_seconds": 30, "views": 1},
        {"folder": "(root)", "watch_seconds": 20, "views": 2},
    ]
    assert client.get("/api/stats/folders", params={"days": 3}).json() == [
        {"folder": "Alpha", "watch_seconds": 30, "views": 1},
        {"folder": "(root)", "watch_seconds": 25, "views": 3},
    ]
