"""Runtime configuration endpoints (media directory)."""

from __future__ import annotations

from pathlib import Path

import aiosqlite
from fastapi import APIRouter, HTTPException, Request

from .config import resolve_path
from .db import set_setting
from .scan import sync_directory
from .schemas import ConfigIn, ConfigOut
from .videos import fetch_videos

config_router = APIRouter(prefix="/api/config", tags=["config"])


@config_router.get("", response_model=ConfigOut)
async def get_config(request: Request) -> ConfigOut:
    video_dir: Path = request.app.state.video_dir
    conn: aiosqlite.Connection = request.app.state.conn
    videos = await fetch_videos(conn)
    return ConfigOut(
        video_dir=str(video_dir),
        exists=video_dir.is_dir(),
        video_count=len(videos),
    )


@config_router.post("", response_model=ConfigOut)
async def update_config(payload: ConfigIn, request: Request) -> ConfigOut:
    conn: aiosqlite.Connection = request.app.state.conn
    candidate = resolve_path(payload.video_dir, base=Path.cwd())
    if not candidate.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a valid directory: {candidate}")

    await set_setting(conn, "video_dir", str(candidate))
    await sync_directory(request.app, video_dir=candidate)
    videos = await fetch_videos(conn)
    return ConfigOut(video_dir=str(candidate), exists=True, video_count=len(videos))
