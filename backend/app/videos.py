"""Video listing and runtime configuration endpoints."""

from __future__ import annotations

import random
from pathlib import Path
from urllib.parse import quote

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request

from .schemas import ConfigIn, ConfigOut, VideoOut
from .scan import sync_directory

router = APIRouter(prefix="/api/videos", tags=["videos"])
config_router = APIRouter(prefix="/api/config", tags=["config"])


async def fetch_present_videos(conn: aiosqlite.Connection) -> list[VideoOut]:
    sql = (
        "SELECT id, filename, type, duration, size, created_at FROM videos "
        "WHERE removed = 0 ORDER BY filename"
    )
    async with conn.execute(sql) as cur:
        rows = await cur.fetchall()
    return [
        VideoOut(
            id=r["id"],
            filename=Path(r["filename"]).name,
            relpath=r["filename"],
            type=r["type"],
            url=f"/videos/{quote(r['filename'])}",
            duration=r["duration"],
            size=r["size"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.get("", response_model=list[VideoOut])
async def list_videos(request: Request) -> list[VideoOut]:
    conn: aiosqlite.Connection = request.app.state.conn
    await sync_directory(request.app)  # cheap for unchanged files; picks up new ones
    return await fetch_present_videos(conn)


@router.get("/random", response_model=list[VideoOut])
async def random_videos(
    request: Request, limit: int | None = Query(default=None, ge=1, le=500)
) -> list[VideoOut]:
    videos = await list_videos(request)
    random.shuffle(videos)
    return videos[:limit] if limit else videos


@config_router.get("", response_model=ConfigOut)
async def get_config(request: Request) -> ConfigOut:
    video_dir: Path = request.app.state.video_dir
    conn: aiosqlite.Connection = request.app.state.conn
    videos = await fetch_present_videos(conn)
    return ConfigOut(
        video_dir=str(video_dir),
        exists=video_dir.is_dir(),
        video_count=len(videos),
    )


@config_router.post("", response_model=ConfigOut)
async def update_config(payload: ConfigIn, request: Request) -> ConfigOut:
    from .db import set_setting

    conn: aiosqlite.Connection = request.app.state.conn
    candidate = Path(payload.video_dir).expanduser()
    candidate = (candidate if candidate.is_absolute() else Path.cwd() / candidate).resolve()
    if not candidate.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a valid directory: {candidate}")

    await set_setting(conn, "video_dir", str(candidate))
    await sync_directory(request.app, video_dir=candidate)
    videos = await fetch_present_videos(conn)
    return ConfigOut(video_dir=str(candidate), exists=True, video_count=len(videos))
