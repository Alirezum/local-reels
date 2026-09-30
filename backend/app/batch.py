"""Daily batch mode: a fixed per-day subset of the library.

A batch is one row per calendar day (client-local `YYYY-MM-DD`) holding an
ordered list of video IDs. Selection is pure random over the visible library
(optionally scoped to one top-level folder); edits (remove / add-random) only
touch the stored ID list, so a batch is stable across reloads and devices.
"""

from __future__ import annotations

import json
import random
import re

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request

from .scan import sync_directory
from .schemas import BatchAddIn, BatchContinueIn, BatchNewIn, BatchOut, BatchReplaceIn
from .videos import fetch_videos

router = APIRouter(prefix="/api/batch", tags=["batch"])

_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
_DATE_RE = re.compile(_DATE_PATTERN)


def _check_date(value: str) -> str:
    if not _DATE_RE.match(value):
        raise HTTPException(status_code=400, detail="Invalid date, expected YYYY-MM-DD")
    return value


def _normalize_folder(folder: str | None) -> str | None:
    if folder is None:
        return None
    folder = folder.strip()
    return folder or None


async def _read_row(conn: aiosqlite.Connection, date: str) -> aiosqlite.Row | None:
    async with conn.execute(
        "SELECT date, size, folder, video_ids FROM daily_batches WHERE date = ?", (date,)
    ) as cur:
        return await cur.fetchone()


async def _batch_out(conn: aiosqlite.Connection, row: aiosqlite.Row) -> BatchOut:
    try:
        ids = json.loads(row["video_ids"])
    except (TypeError, ValueError):
        ids = []
    pool = await fetch_videos(conn, folder=row["folder"])
    by_id = {video.id: video for video in pool}
    return BatchOut(
        date=row["date"],
        size=row["size"],
        folder=row["folder"],
        videos=[by_id[video_id] for video_id in ids if video_id in by_id],
    )


async def _store_batch(
    conn: aiosqlite.Connection, *, date: str, size: int, folder: str | None, ids: list[str]
) -> None:
    await conn.execute(
        "INSERT INTO daily_batches (date, size, folder, video_ids, created_at) "
        "VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) "
        "ON CONFLICT(date) DO UPDATE SET size = excluded.size, folder = excluded.folder, "
        "video_ids = excluded.video_ids",
        (date, size, folder, json.dumps(ids)),
    )
    await conn.commit()


@router.get("", response_model=BatchOut)
async def get_batch(
    request: Request, date: str = Query(pattern=_DATE_PATTERN)
) -> BatchOut:
    conn: aiosqlite.Connection = request.app.state.conn
    row = await _read_row(conn, date)
    if row is None:
        raise HTTPException(status_code=404, detail="No batch for this date")
    await sync_directory(request.app)
    return await _batch_out(conn, row)


@router.get("/previous", response_model=BatchOut)
async def get_previous_batch(
    request: Request, before: str = Query(pattern=_DATE_PATTERN)
) -> BatchOut:
    conn: aiosqlite.Connection = request.app.state.conn
    async with conn.execute(
        "SELECT date, size, folder, video_ids FROM daily_batches "
        "WHERE date < ? ORDER BY date DESC LIMIT 1",
        (before,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No previous batch")
    await sync_directory(request.app)
    return await _batch_out(conn, row)


@router.post("/new", response_model=BatchOut)
async def new_batch(payload: BatchNewIn, request: Request) -> BatchOut:
    conn: aiosqlite.Connection = request.app.state.conn
    folder = _normalize_folder(payload.folder)
    await sync_directory(request.app)
    pool = await fetch_videos(conn, folder=folder)
    if not pool:
        raise HTTPException(status_code=400, detail="No videos available for this scope")
    picked = random.sample(pool, min(payload.size, len(pool)))
    await _store_batch(
        conn, date=payload.date, size=payload.size, folder=folder, ids=[v.id for v in picked]
    )
    row = await _read_row(conn, payload.date)
    assert row is not None
    return await _batch_out(conn, row)


@router.post("/continue", response_model=BatchOut)
async def continue_batch(payload: BatchContinueIn, request: Request) -> BatchOut:
    conn: aiosqlite.Connection = request.app.state.conn
    source = await _read_row(conn, payload.from_date)
    if source is None:
        raise HTTPException(status_code=404, detail="No previous batch")
    await _store_batch(
        conn,
        date=payload.date,
        size=source["size"],
        folder=source["folder"],
        ids=list(json.loads(source["video_ids"])),
    )
    await sync_directory(request.app)
    row = await _read_row(conn, payload.date)
    assert row is not None
    return await _batch_out(conn, row)


@router.post("/add-random", response_model=BatchOut)
async def add_random_to_batch(payload: BatchAddIn, request: Request) -> BatchOut:
    conn: aiosqlite.Connection = request.app.state.conn
    row = await _read_row(conn, payload.date)
    if row is None:
        raise HTTPException(status_code=404, detail="No batch for this date")
    await sync_directory(request.app)
    ids: list[str] = list(json.loads(row["video_ids"]))
    pool = await fetch_videos(conn, folder=row["folder"])
    candidates = [video for video in pool if video.id not in ids]
    if not candidates:
        raise HTTPException(status_code=400, detail="No more videos to add")
    ids.append(random.choice(candidates).id)
    await _store_batch(conn, date=row["date"], size=row["size"], folder=row["folder"], ids=ids)
    updated = await _read_row(conn, payload.date)
    assert updated is not None
    return await _batch_out(conn, updated)


@router.delete("/{date}/{video_id}", response_model=BatchOut)
async def remove_from_batch(date: str, video_id: str, request: Request) -> BatchOut:
    _check_date(date)
    conn: aiosqlite.Connection = request.app.state.conn
    row = await _read_row(conn, date)
    if row is None:
        raise HTTPException(status_code=404, detail="No batch for this date")
    ids: list[str] = list(json.loads(row["video_ids"]))
    if video_id not in ids:
        raise HTTPException(status_code=404, detail="Video is not in this batch")
    ids.remove(video_id)
    await _store_batch(conn, date=row["date"], size=row["size"], folder=row["folder"], ids=ids)
    updated = await _read_row(conn, date)
    assert updated is not None
    return await _batch_out(conn, updated)


@router.post("/replace", response_model=BatchOut)
async def replace_in_batch(payload: BatchReplaceIn, request: Request) -> BatchOut:
    """Swap one stored video ID for another (e.g. after moving a file, which
    gives it a new ID), keeping its position in the batch."""
    conn: aiosqlite.Connection = request.app.state.conn
    row = await _read_row(conn, payload.date)
    if row is None:
        raise HTTPException(status_code=404, detail="No batch for this date")
    ids: list[str] = list(json.loads(row["video_ids"]))
    if payload.old_id not in ids:
        raise HTTPException(status_code=404, detail="Video is not in this batch")
    async with conn.execute(
        "SELECT 1 FROM videos WHERE id = ? AND removed = 0", (payload.new_id,)
    ) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Unknown video_id")
    ids = [payload.new_id if video_id == payload.old_id else video_id for video_id in ids]
    await _store_batch(conn, date=row["date"], size=row["size"], folder=row["folder"], ids=ids)
    updated = await _read_row(conn, payload.date)
    assert updated is not None
    await sync_directory(request.app)
    return await _batch_out(conn, updated)
