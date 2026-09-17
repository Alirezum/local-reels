"""Aggregated watch-time statistics.

The frontend flushes a watch chunk every ~5 s, so raw event rows are *not*
views. A "view" is one continuous watch session per video: consecutive events
for the same video less than 30 s apart count as a single view.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import aiosqlite
from fastapi import APIRouter, Query, Request

from .schemas import DailyOut, FolderStatOut, SummaryOut, TopVideoOut

router = APIRouter(prefix="/api/stats", tags=["stats"])

# Extracts the top-level folder from a relative POSIX path ("trips/paris.mp4" -> "trips").
FOLDER_EXPR = "CASE WHEN instr(v.filename, '/') > 0 THEN substr(v.filename, 1, instr(v.filename, '/') - 1) ELSE '(root)' END"

VIEW_GAP_SECONDS = 30

# Adds an `is_new_view` flag (1 = start of a watch session) to every event.
SESSIONS_CTE = f"""
WITH sessions AS (
    SELECT
        video_id,
        created_at,
        duration_watched,
        CASE
            WHEN LAG(created_at) OVER w IS NULL
                 OR (julianday(created_at) - julianday(LAG(created_at) OVER w)) * 86400.0
                    >= {VIEW_GAP_SECONDS}
            THEN 1
            ELSE 0
        END AS is_new_view
    FROM watch_events
    WINDOW w AS (PARTITION BY video_id ORDER BY created_at)
)
"""


@router.get("/summary", response_model=SummaryOut)
async def summary(request: Request) -> SummaryOut:
    conn: aiosqlite.Connection = request.app.state.conn
    sql = (
        SESSIONS_CTE
        + "SELECT COALESCE(SUM(duration_watched), 0) AS total, "
        "COALESCE(SUM(is_new_view), 0) AS views, "
        "COUNT(DISTINCT video_id) AS videos FROM sessions"
    )
    async with conn.execute(sql) as cur:
        row = await cur.fetchone()
    return SummaryOut(
        total_watch_seconds=round(float(row["total"]), 2),
        total_views=int(row["views"]),
        videos_watched=int(row["videos"]),
    )


@router.get("/top-videos", response_model=list[TopVideoOut])
async def top_videos(
    request: Request, limit: int = Query(default=10, ge=1, le=100)
) -> list[TopVideoOut]:
    conn: aiosqlite.Connection = request.app.state.conn
    sql = (
        SESSIONS_CTE
        + "SELECT s.video_id AS video_id, v.filename AS filename, "
        "SUM(s.duration_watched) AS watch_seconds, SUM(s.is_new_view) AS views "
        "FROM sessions s JOIN videos v ON v.id = s.video_id "
        "GROUP BY s.video_id ORDER BY watch_seconds DESC LIMIT ?"
    )
    async with conn.execute(sql, (limit,)) as cur:
        rows = await cur.fetchall()
    return [
        TopVideoOut(
            video_id=r["video_id"],
            filename=r["filename"],
            watch_seconds=round(float(r["watch_seconds"]), 2),
            views=int(r["views"]),
        )
        for r in rows
    ]


def _window_start(days: int) -> date:
    return datetime.now(timezone.utc).date() - timedelta(days=days - 1)


@router.get("/daily", response_model=list[DailyOut])
async def daily(
    request: Request, days: int = Query(default=30, ge=1, le=365)
) -> list[DailyOut]:
    conn: aiosqlite.Connection = request.app.state.conn
    start = _window_start(days)
    sql = (
        SESSIONS_CTE
        + "SELECT date(created_at) AS day, SUM(duration_watched) AS watch_seconds, "
        "SUM(is_new_view) AS views FROM sessions WHERE date(created_at) >= ? "
        "GROUP BY day"
    )
    async with conn.execute(sql, (start.isoformat(),)) as cur:
        rows = await cur.fetchall()
    by_day = {r["day"]: r for r in rows}

    out: list[DailyOut] = []
    for i in range(days):
        key = (start + timedelta(days=i)).isoformat()
        r = by_day.get(key)
        out.append(
            DailyOut(
                date=key,
                watch_seconds=round(float(r["watch_seconds"]), 2) if r else 0.0,
                views=int(r["views"]) if r else 0,
            )
        )
    return out


@router.get("/folders", response_model=list[FolderStatOut])
async def folders(
    request: Request, days: int = Query(default=30, ge=1, le=365)
) -> list[FolderStatOut]:
    conn: aiosqlite.Connection = request.app.state.conn
    sql = (
        SESSIONS_CTE
        + f"SELECT {FOLDER_EXPR} AS folder, "
        "SUM(s.duration_watched) AS watch_seconds, SUM(s.is_new_view) AS views "
        "FROM sessions s JOIN videos v ON v.id = s.video_id "
        "WHERE date(s.created_at) >= ? "
        "GROUP BY folder ORDER BY watch_seconds DESC"
    )
    async with conn.execute(sql, (_window_start(days).isoformat(),)) as cur:
        rows = await cur.fetchall()
    return [
        FolderStatOut(
            folder=r["folder"],
            watch_seconds=round(float(r["watch_seconds"]), 2),
            views=int(r["views"]),
        )
        for r in rows
    ]
