"""Video listing, user flags (favorite / blocked) and runtime configuration."""

from __future__ import annotations

import random
from pathlib import Path
from urllib.parse import quote

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request

from .scan import sync_directory
from .schemas import ConfigIn, ConfigOut, FlagIn, FolderOut, VideoOut

router = APIRouter(prefix="/api/videos", tags=["videos"])
config_router = APIRouter(prefix="/api/config", tags=["config"])
flag_router = APIRouter(tags=["flags"])

ROOT_FOLDER = "(root)"


def top_folder(relpath: str) -> str:
    return relpath.split("/", 1)[0] if "/" in relpath else ROOT_FOLDER


async def fetch_videos(
    conn: aiosqlite.Connection,
    *,
    folder: str | None = None,
    favorites_only: bool = False,
    include_blocked: bool = False,
) -> list[VideoOut]:
    sql = (
        "SELECT v.id, v.filename, v.type, v.duration, v.size, v.created_at, "
        "COALESCE(f.favorite, 0) AS favorite "
        "FROM videos v LEFT JOIN user_flags f ON f.video_id = v.id "
        "WHERE v.removed = 0"
    )
    params: list[object] = []
    if not include_blocked:
        sql += " AND COALESCE(f.blocked, 0) = 0"
    if folder == ROOT_FOLDER:
        sql += " AND v.filename NOT LIKE '%/%'"
    elif folder:
        sql += " AND v.filename LIKE ?"
        params.append(f"{folder}/%")
    if favorites_only:
        sql += " AND COALESCE(f.favorite, 0) = 1"
    sql += " ORDER BY v.filename"

    async with conn.execute(sql, params) as cur:
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
            favorite=bool(r["favorite"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.get("", response_model=list[VideoOut])
async def list_videos(
    request: Request,
    folder: str | None = Query(default=None),
    favorites: bool = Query(default=False),
) -> list[VideoOut]:
    conn: aiosqlite.Connection = request.app.state.conn
    await sync_directory(request.app)  # cheap for unchanged files; picks up new ones
    return await fetch_videos(conn, folder=folder, favorites_only=favorites)


@router.get("/random", response_model=list[VideoOut])
async def random_videos(
    request: Request,
    limit: int | None = Query(default=None, ge=1, le=500),
    order: str = Query(default="weighted", pattern="^(weighted|random)$"),
    folder: str | None = Query(default=None),
    favorites: bool = Query(default=False),
) -> list[VideoOut]:
    conn: aiosqlite.Connection = request.app.state.conn
    videos = await fetch_videos(
        conn, folder=folder, favorites_only=favorites, include_blocked=False
    )
    if order == "weighted":
        weights = await fetch_view_weights(conn)
        random.shuffle(videos)  # so ties among unseen are shuffled fairly
        videos = weighted_sample_without_replacement(videos, weights)
    else:
        random.shuffle(videos)
    return videos[:limit] if limit else videos


@router.get("/folders", response_model=list[FolderOut])
async def list_folders(request: Request) -> list[FolderOut]:
    conn: aiosqlite.Connection = request.app.state.conn
    videos = await fetch_videos(conn)
    counts: dict[str, int] = {}
    for v in videos:
        counts[top_folder(v.relpath)] = counts.get(top_folder(v.relpath), 0) + 1
    return sorted(
        (FolderOut(name=k, count=n) for k, n in counts.items()),
        key=lambda f: (f.name == ROOT_FOLDER, f.name.lower()),
    )


async def fetch_view_weights(conn: aiosqlite.Connection) -> dict[str, float]:
    """Per-video discovery weight: less-watched -> higher weight.

    weight = 1 / (1 + view_sessions + watched_minutes / 5). Never-seen media
    score 1.0; a heavily watched clip scores near 0.
    """
    from .stats import SESSIONS_CTE

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


@flag_router.post("/api/flags")
async def set_flags(payload: FlagIn, request: Request) -> dict[str, bool]:
    conn: aiosqlite.Connection = request.app.state.conn
    if payload.favorite is None and payload.blocked is None:
        raise HTTPException(status_code=400, detail="Nothing to update")

    async with conn.execute("SELECT 1 FROM videos WHERE id = ?", (payload.video_id,)) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Unknown video_id")

    # Only touch the provided fields; an existing row is updated in place so
    # unset flags keep their value. Insert (with defaults) only when absent.
    sets: list[str] = []
    params: list[object] = []
    if payload.favorite is not None:
        sets.append("favorite = ?")
        params.append(int(payload.favorite))
    if payload.blocked is not None:
        sets.append("blocked = ?")
        params.append(int(payload.blocked))
    params.append(payload.video_id)
    upd = await conn.execute(
        f"UPDATE user_flags SET {', '.join(sets)}, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE video_id = ?",
        params,
    )
    if upd.rowcount == 0:
        await conn.execute(
            "INSERT INTO user_flags (video_id, favorite, blocked, updated_at) "
            "VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
            (
                payload.video_id,
                int(payload.favorite or False),
                int(payload.blocked or False),
            ),
        )
    await conn.commit()
    async with conn.execute(
        "SELECT favorite, blocked FROM user_flags WHERE video_id = ?", (payload.video_id,)
    ) as cur:
        row = await cur.fetchone()
    return {"favorite": bool(row["favorite"]), "blocked": bool(row["blocked"])}


@flag_router.get("/api/blocked")
async def list_blocked(request: Request) -> list[dict[str, str]]:
    conn: aiosqlite.Connection = request.app.state.conn
    sql = (
        "SELECT v.id, v.filename FROM videos v "
        "JOIN user_flags f ON f.video_id = v.id "
        "WHERE COALESCE(f.blocked, 0) = 1 AND v.removed = 0 ORDER BY v.filename"
    )
    async with conn.execute(sql) as cur:
        rows = await cur.fetchall()
    return [{"id": r["id"], "relpath": r["filename"]} for r in rows]


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
    from .db import set_setting

    conn: aiosqlite.Connection = request.app.state.conn
    candidate = Path(payload.video_dir).expanduser()
    candidate = (candidate if candidate.is_absolute() else Path.cwd() / candidate).resolve()
    if not candidate.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a valid directory: {candidate}")

    await set_setting(conn, "video_dir", str(candidate))
    await sync_directory(request.app, video_dir=candidate)
    videos = await fetch_videos(conn)
    return ConfigOut(video_dir=str(candidate), exists=True, video_count=len(videos))
