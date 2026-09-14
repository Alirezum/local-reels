"""Watch-event recording."""

from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, HTTPException, Request

from .schemas import WatchIn

router = APIRouter(prefix="/api/watch", tags=["watch"])


@router.post("")
async def record_watch(payload: WatchIn, request: Request) -> dict[str, bool]:
    conn: aiosqlite.Connection = request.app.state.conn
    async with conn.execute("SELECT 1 FROM videos WHERE id = ?", (payload.video_id,)) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Unknown video_id")

    duration = max(0.0, min(payload.duration_watched, 3600.0))
    await conn.execute(
        "INSERT INTO watch_events (video_id, start_time, end_time, duration_watched, created_at) "
        "VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
        (payload.video_id, payload.start_time, payload.end_time, duration),
    )
    await conn.commit()
    return {"ok": True}
