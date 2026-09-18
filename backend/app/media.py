"""Byte-range streaming of local video and image files.

Browsers (and ffmpeg-style clients) rely on HTTP Range requests for
<video> seeking; this serves files from the configured directory (including
its subfolders) and nothing else.
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

router = APIRouter(tags=["media"])

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")
_CHUNK_BYTES = 1024 * 1024


def _file_iter(path: Path, start: int, length: int) -> Iterator[bytes]:
    with path.open("rb") as fh:
        fh.seek(start)
        remaining = length
        while remaining > 0:
            chunk = fh.read(min(_CHUNK_BYTES, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    match = _RANGE_RE.match(header.strip())
    if not match or (not match.group(1) and not match.group(2)):
        raise ValueError("Invalid range")

    if match.group(1):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else size - 1
    else:  # suffix range: last N bytes
        suffix = int(match.group(2))
        start = max(size - suffix, 0)
        end = size - 1

    end = min(end, size - 1)
    if start > end or start >= size:
        return None
    return start, end


@router.get("/videos/{rel:path}")
async def stream_video(rel: str, request: Request) -> Response:
    root: Path = request.app.state.video_dir
    try:
        target = (root / rel).resolve()
    except OSError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(status_code=404, detail="Video not found")

    size = target.stat().st_size
    media_type = mimetypes.guess_type(rel)[0] or "video/mp4"
    range_header = request.headers.get("range")

    if not range_header:
        return FileResponse(
            target,
            media_type=media_type,
            headers={"Accept-Ranges": "bytes", "Content-Length": str(size)},
        )

    try:
        byte_range = _parse_range(range_header, size)
    except ValueError:
        raise HTTPException(status_code=416, detail="Invalid range")

    if byte_range is None:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
        )

    start, end = byte_range
    length = end - start + 1
    return StreamingResponse(
        _file_iter(target, start, length),
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(length),
            "Accept-Ranges": "bytes",
        },
    )
