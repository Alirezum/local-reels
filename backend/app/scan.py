"""Media directory scanning and metadata probing.

``sync_directory`` is called on startup, whenever the configured directory
changes, and lazily before listing videos, so files added to the folder show
up without restarting the server. The scan is recursive (subfolders included,
hidden files/dirs skipped). ffprobe is only run for new/changed videos;
durations are cached in SQLite. Images need no probing (duration 0).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

from .config import settings
from .db import get_setting

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger("localreel.scan")

VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi", ".ogv", ".ogg"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp"}
MEDIA_EXTS = VIDEO_EXTS | IMAGE_EXTS

_PROBE_SEM = asyncio.Semaphore(8)


def media_kind(rel_path: str) -> str:
    return "image" if Path(rel_path).suffix.lower() in IMAGE_EXTS else "video"


def video_id_for(rel_path: str) -> str:
    return hashlib.sha1(rel_path.encode("utf-8")).hexdigest()[:16]


def iter_media_files(root: Path) -> list[tuple[str, Path]]:
    """Return sorted (relative_posix_path, absolute_path) for all media files.

    Recursive; skips hidden files/dirs and never follows symlinked
    directories (avoids cycles); skips itself via (dev, ino) memo.
    """
    found: list[tuple[str, Path]] = []
    seen_dirs: set[tuple[int, int]] = set()

    def walk(directory: Path, prefix: str) -> None:
        try:
            st = directory.stat()
            key = (st.st_dev, st.st_ino)
            if key in seen_dirs:
                return
            seen_dirs.add(key)
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    walk(Path(entry.path), f"{prefix}{entry.name}/")
                elif entry.is_file() and Path(entry.name).suffix.lower() in MEDIA_EXTS:
                    found.append((f"{prefix}{entry.name}", Path(entry.path)))
            except OSError:
                continue

    walk(root, "")
    return found


async def probe_duration(path: Path) -> float:
    """Return the duration in seconds via ffprobe, or 0.0 if unavailable."""
    if shutil.which("ffprobe") is None:
        return 0.0
    async with _PROBE_SEM:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
            data = json.loads(out or b"{}")
            return round(float(data.get("format", {}).get("duration") or 0.0), 2)
        except Exception:
            logger.warning("ffprobe failed for %s", path, exc_info=True)
            return 0.0


def resolve_video_dir(override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    return settings.resolved_video_dir()


async def sync_directory(app: "FastAPI", video_dir: Path | None = None) -> Path:
    """Scan the (optionally new) media dir, upsert rows, return the dir used."""
    conn: aiosqlite.Connection = app.state.conn
    if video_dir is None:
        video_dir = resolve_video_dir(await get_setting(conn, "video_dir"))
    app.state.video_dir = video_dir

    if not video_dir.is_dir():
        logger.warning("Video directory does not exist: %s", video_dir)
        await conn.execute("UPDATE videos SET removed = 1 WHERE removed = 0")
        await conn.commit()
        return video_dir

    files = iter_media_files(video_dir)

    existing: dict[str, aiosqlite.Row] = {}
    async with conn.execute("SELECT filename, duration, size, mtime FROM videos") as cur:
        for row in await cur.fetchall():
            existing[row["filename"]] = row

    infos: list[dict] = []
    to_probe: list[dict] = []
    for rel, abs_path in files:
        try:
            st = abs_path.stat()
        except OSError:
            continue
        kind = media_kind(rel)
        info = {
            "rel": rel,
            "path": abs_path,
            "kind": kind,
            "size": st.st_size,
            "mtime": st.st_mtime,
            "duration": 0.0,
        }
        old = existing.get(rel)
        if kind == "image":
            pass  # duration irrelevant
        elif (
            old is not None
            and old["size"] == st.st_size
            and abs(old["mtime"] - st.st_mtime) < 2
            and old["duration"] > 0
        ):
            info["duration"] = old["duration"]  # cached, skip ffprobe
        else:
            to_probe.append(info)
        infos.append(info)

    if to_probe:
        if shutil.which("ffprobe") is None:
            logger.warning("ffprobe not found; durations will report as 0")
        durations = await asyncio.gather(*(probe_duration(i["path"]) for i in to_probe))
        for info, dur in zip(to_probe, durations):
            info["duration"] = dur

    await conn.executemany(
        """
        INSERT INTO videos (id, filename, path, type, duration, size, mtime, removed, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        ON CONFLICT(filename) DO UPDATE SET
            path = excluded.path,
            type = excluded.type,
            duration = excluded.duration,
            size = excluded.size,
            mtime = excluded.mtime,
            removed = 0
        """,
        [
            (
                video_id_for(i["rel"]),
                i["rel"],
                str(i["path"]),
                i["kind"],
                i["duration"],
                i["size"],
                i["mtime"],
            )
            for i in infos
        ],
    )

    # Flag DB rows whose files disappeared from disk (kept for stats integrity).
    rels = [i["rel"] for i in infos]
    if rels:
        placeholders = ",".join("?" * len(rels))
        await conn.execute(
            f"UPDATE videos SET removed = 1 WHERE removed = 0 AND filename NOT IN ({placeholders})",
            rels,
        )
    else:
        await conn.execute("UPDATE videos SET removed = 1 WHERE removed = 0")
    await conn.commit()
    return video_dir
