"""Move media files between top-level folders, preserving IDs and history."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import aiosqlite
from fastapi import APIRouter, HTTPException, Request

from .db import video_exists
from .scan import video_id_for
from .schemas import MoveIn
from .videos import ROOT_FOLDER

move_router = APIRouter(prefix="/api/videos", tags=["videos"])


def _move_target(root: Path, folder: str, filename: str) -> Path:
    target_dir = (root / folder).resolve() if folder else root.resolve()
    if not target_dir.is_relative_to(root.resolve()):
        raise HTTPException(status_code=400, detail="Invalid folder")
    return target_dir / filename


async def _remap_batches(
    conn: aiosqlite.Connection, old_id: str, new_id: str
) -> None:
    # A move gives the file a new ID; rewrite stored batch lists so the video
    # stays in its batches instead of silently dropping out of them.
    async with conn.execute("SELECT date, video_ids FROM daily_batches") as cur:
        rows = await cur.fetchall()
    for row in rows:
        try:
            ids = json.loads(row["video_ids"])
        except (TypeError, ValueError):
            continue
        if old_id not in ids:
            continue
        remapped = [new_id if video_id == old_id else video_id for video_id in ids]
        await conn.execute(
            "UPDATE daily_batches SET video_ids = ? WHERE date = ?",
            (json.dumps(remapped), row["date"]),
        )


async def _move_file(conn: aiosqlite.Connection, request: Request, payload: MoveIn) -> str:
    root: Path = request.app.state.video_dir
    async with conn.execute(
        "SELECT filename, path, type, duration, size, mtime, created_at FROM videos WHERE id = ? AND removed = 0",
        (payload.video_id,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown video_id")
    folder = payload.folder.strip().strip("/")
    if folder in ("", ROOT_FOLDER):
        folder = ""
    elif "/" in folder or folder.startswith(".") or "\\" in folder:
        raise HTTPException(status_code=400, detail="Invalid folder name")

    filename = Path(row["filename"]).name
    source = Path(row["path"])
    if not source.is_file():
        source = root / row["filename"]
    target = _move_target(root, folder, filename)
    if not target.parent.is_dir():
        raise HTTPException(status_code=400, detail=f"Folder does not exist: {folder}")
    if target.exists():
        raise HTTPException(status_code=409, detail=f"Target already exists: {folder}/{filename}")

    new_rel = f"{folder}/{filename}" if folder else filename
    new_id = video_id_for(new_rel)
    if new_id != payload.video_id and await video_exists(conn, new_id):
        raise HTTPException(status_code=409, detail="A record for this path already exists")

    shutil.move(str(source), str(target))
    await conn.execute("PRAGMA defer_foreign_keys = ON")
    await conn.execute(
        "UPDATE videos SET id = ?, filename = ?, path = ? WHERE id = ?",
        (new_id, new_rel, str(target), payload.video_id),
    )
    await conn.execute(
        "UPDATE watch_events SET video_id = ? WHERE video_id = ?", (new_id, payload.video_id)
    )
    await conn.execute(
        "UPDATE user_flags SET video_id = ? WHERE video_id = ?", (new_id, payload.video_id)
    )
    if new_id != payload.video_id:
        await _remap_batches(conn, payload.video_id, new_id)
    await conn.commit()
    return new_rel


@move_router.post("/move")
async def move_video(payload: MoveIn, request: Request) -> dict[str, str]:
    conn: aiosqlite.Connection = request.app.state.conn
    new_rel = await _move_file(conn, request, payload)
    return {"id": video_id_for(new_rel), "relpath": new_rel}
