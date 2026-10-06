"""User flags (favorite / blocked) endpoints."""

from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, HTTPException, Request

from .db import video_exists
from .schemas import FlagIn

flag_router = APIRouter(tags=["flags"])


async def _update_flags(conn: aiosqlite.Connection, payload: FlagIn) -> None:
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


@flag_router.post("/api/flags")
async def set_flags(payload: FlagIn, request: Request) -> dict[str, bool]:
    conn: aiosqlite.Connection = request.app.state.conn
    if payload.favorite is None and payload.blocked is None:
        raise HTTPException(status_code=400, detail="Nothing to update")

    if not await video_exists(conn, payload.video_id):
        raise HTTPException(status_code=404, detail="Unknown video_id")

    await _update_flags(conn, payload)
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
