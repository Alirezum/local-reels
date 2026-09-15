"""Video listing and runtime configuration endpoints."""

from __future__ import annotations

import random
from pathlib import Path
from urllib.parse import quote

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request

from .schemas import ConfigIn, ConfigOut, VideoOut
from .scan import sync_directory
from .stats import SESSIONS_CTE

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


async def fetch_view_weights(conn: aiosqlite.Connection) -> dict[str, float]:
    """Per-video discovery weight: less-watched -> higher weight.

    weight = 1 / (1 + view_sessions + watched_minutes / 5). Never-seen media
    score 1.0; a heavily watched clip scores near 0.
    """
    sql = (
        SESSIONS_CTE
        + "SELECT video_id, SUM(is_new_view) AS views, "
        "SUM(duration_watched) AS seconds FROM sessions GROUP BY video_id"
    )
    async with conn.execute(sql) as cur:
        rows = await cur.fetchall()
    return {
        r["video_id"]: 1.0 / (1.0 + float(r["views"]) + float(r["seconds"]) / 60.0 / 5.0)
        for r in rows
    }


def weighted_sample_without_replacement(
    videos: list[VideoOut], weights: dict[str, float]
) -> list[VideoOut]:
    pool = list(videos)
    remaining = [weights.get(v.id, 1.0) for v in pool]
    picked: list[VideoOut] = []
    while pool:
        total = sum(remaining)
        if total <= 0:
            random.shuffle(pool)
            picked.extend(pool)
            break
        r = random.uniform(0, total)
        acc = 0.0
        idx = 0
        for i, w in enumerate(remaining):
            acc += w
            if r <= acc:
                idx = i
                break
        else:
            idx = len(pool) - 1
        picked.append(pool.pop(idx))
        remaining.pop(idx)
    return picked


@router.get("/random", response_model=list[VideoOut])
async def random_videos(
    request: Request,
    limit: int | None = Query(default=None, ge=1, le=500),
    order: str = Query(default="weighted", pattern="^(weighted|random)$"),
) -> list[VideoOut]:
    conn: aiosqlite.Connection = request.app.state.conn
    videos = await list_videos(request)
    if order == "weighted":
        weights = await fetch_view_weights(conn)
        random.shuffle(videos)  # so ties among unseen are shuffled fairly
        videos = weighted_sample_without_replacement(videos, weights)
    else:
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
