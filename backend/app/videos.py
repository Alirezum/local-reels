"""Video listing endpoints."""

from __future__ import annotations

import random
from pathlib import Path
from urllib.parse import quote

import aiosqlite
from fastapi import APIRouter, Query, Request

from .scan import sync_directory
from .schemas import FolderOut, VideoOut
from .weights import fetch_view_weights, weighted_sample_without_replacement

router = APIRouter(prefix="/api/videos", tags=["videos"])

ROOT_FOLDER = "(root)"

# Re-exported for backward compatibility (tests import from here).
__all__ = [
    "ROOT_FOLDER",
    "router",
    "top_folder",
    "fetch_videos",
    "list_videos",
    "random_videos",
    "list_folders",
    "fetch_view_weights",
    "weighted_sample_without_replacement",
]


def top_folder(relpath: str) -> str:
    return relpath.split("/", 1)[0] if "/" in relpath else ROOT_FOLDER


async def fetch_videos(
    conn: aiosqlite.Connection,
    *,
    folder: str | list[str] | None = None,
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
    folders: list[str] = [folder] if isinstance(folder, str) else list(folder or [])
    folders = [f for f in folders if f]
    # Dedupe while preserving order.
    folders = list(dict.fromkeys(folders))
    if folders:
        clauses: list[str] = []
        for name in folders:
            if name == ROOT_FOLDER:
                clauses.append("v.filename NOT LIKE '%/%'")
            else:
                clauses.append("v.filename LIKE ?")
                params.append(f"{name}/%")
        sql += " AND (" + " OR ".join(clauses) + ")"
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
    folder: list[str] | None = Query(default=None),
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
    folder: list[str] | None = Query(default=None),
    favorites: bool = Query(default=False),
) -> list[VideoOut]:
    conn: aiosqlite.Connection = request.app.state.conn
    videos = await fetch_videos(
        conn, folder=folder, favorites_only=favorites, include_blocked=False
    )
    if order == "weighted":
        weights = await fetch_view_weights(conn)
        # expovariate keys already mix equal weights uniformly; no pre-shuffle needed.
        videos = weighted_sample_without_replacement(videos, weights)
    else:
        random.shuffle(videos)
    return videos[:limit] if limit else videos


@router.get("/folders", response_model=list[FolderOut])
async def list_folders(request: Request) -> list[FolderOut]:
    conn: aiosqlite.Connection = request.app.state.conn
    videos = await fetch_videos(conn)
    counts: dict[str, int] = {}
    for video in videos:
        folder = top_folder(video.relpath)
        counts[folder] = counts.get(folder, 0) + 1
    video_dir: Path = request.app.state.video_dir
    if video_dir.is_dir():
        for entry in sorted(video_dir.iterdir()):
            if entry.is_dir() and entry.name not in counts and not entry.name.startswith("."):
                counts[entry.name] = 0
    return sorted(
        (FolderOut(name=k, count=n) for k, n in counts.items()),
        key=lambda f: (f.name == ROOT_FOLDER, f.name.lower()),
    )
