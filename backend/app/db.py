"""Async SQLite access layer."""

from __future__ import annotations

import aiosqlite

from .config import settings

_conn: aiosqlite.Connection | None = None

# `videos.filename` holds the file's POSIX path relative to the video
# directory (e.g. "clip.mp4" or "trips/paris.mp4"), which makes it unique.

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id         TEXT PRIMARY KEY,
    filename   TEXT NOT NULL UNIQUE,
    path       TEXT NOT NULL,
    type       TEXT NOT NULL DEFAULT 'video',
    duration   REAL NOT NULL DEFAULT 0,
    size       INTEGER NOT NULL DEFAULT 0,
    mtime      REAL NOT NULL DEFAULT 0,
    removed    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watch_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id         TEXT NOT NULL REFERENCES videos(id),
    start_time       REAL NOT NULL,
    end_time         REAL NOT NULL,
    duration_watched REAL NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_watch_video ON watch_events(video_id);
CREATE INDEX IF NOT EXISTS idx_watch_time  ON watch_events(created_at);

CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_flags (
    video_id   TEXT PRIMARY KEY REFERENCES videos(id),
    favorite   INTEGER NOT NULL DEFAULT 0,
    blocked    INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_batches (
    date       TEXT PRIMARY KEY,
    size       INTEGER NOT NULL,
    folder     TEXT,
    video_ids  TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
"""


async def get_connection() -> aiosqlite.Connection:
    global _conn
    if _conn is None:
        db_path = settings.resolved_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _conn = await aiosqlite.connect(db_path)
        try:
            _conn.row_factory = aiosqlite.Row
            await _conn.execute("PRAGMA foreign_keys = ON")
            await _conn.execute("PRAGMA journal_mode = WAL")
        except BaseException:
            await close_connection()
            raise
    return _conn


async def close_connection() -> None:
    global _conn
    conn = _conn
    _conn = None
    if conn is not None:
        await conn.close()


async def init_schema(conn: aiosqlite.Connection) -> None:
    await conn.executescript(SCHEMA)
    # Runtime migration: add `type` column to databases created before image support.
    async with conn.execute("PRAGMA table_info(videos)") as cur:
        columns = {row["name"] for row in await cur.fetchall()}
    if "type" not in columns:
        await conn.execute("ALTER TABLE videos ADD COLUMN type TEXT NOT NULL DEFAULT 'video'")
    await conn.commit()


async def get_setting(conn: aiosqlite.Connection, key: str) -> str | None:
    async with conn.execute("SELECT value FROM config WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
    return row["value"] if row else None


async def set_setting(conn: aiosqlite.Connection, key: str, value: str) -> None:
    await conn.execute(
        "INSERT INTO config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await conn.commit()
