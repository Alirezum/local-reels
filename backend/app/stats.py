"""Aggregated watch-time statistics."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import aiosqlite
from fastapi import APIRouter, Query, Request

from .schemas import DailyOut, SummaryOut, TopVideoOut

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/summary", response_model=SummaryOut)
async def summary(request: Request) -> SummaryOut:
    conn: aiosqlite.Connection = request.app.state.conn
    sql = (
        "SELECT COALESCE(SUM(duration_watched), 0) AS total, "
        "COUNT(*) AS views, COUNT(DISTINCT video_id) AS videos "
        "FROM watch_events"
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
        "SELECT e.video_id AS video_id, v.filename AS filename, "
        "SUM(e.duration_watched) AS watch_seconds, COUNT(*) AS views "
        "FROM watch_events e JOIN videos v ON v.id = e.video_id "
        "GROUP BY e.video_id ORDER BY watch_seconds DESC LIMIT ?"
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


@router.get("/daily", response_model=list[DailyOut])
async def daily(
    request: Request, days: int = Query(default=30, ge=1, le=365)
) -> list[DailyOut]:
    conn: aiosqlite.Connection = request.app.state.conn
    since = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    sql = (
        "SELECT date(created_at) AS day, SUM(duration_watched) AS watch_seconds, "
        "COUNT(*) AS views FROM watch_events WHERE date(created_at) >= ? "
        "GROUP BY day"
    )
    async with conn.execute(sql, (since,)) as cur:
        rows = await cur.fetchall()
    by_day = {r["day"]: r for r in rows}

    out: list[DailyOut] = []
    start = date.today() - timedelta(days=days - 1)
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
