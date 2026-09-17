import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import media, stats, videos, watch
from .db import close_connection, get_connection, init_schema
from .scan import sync_directory

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    conn = await get_connection()
    app.state.conn = conn
    try:
        await init_schema(conn)
        await sync_directory(app)  # resolves app.state.video_dir + syncs the video index
        yield
    finally:
        await close_connection()


app = FastAPI(title="Local Reels", version="1.0.0", lifespan=lifespan)

# Single local user; permissive CORS only to ease dev/debugging.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(videos.router)
app.include_router(videos.config_router)
app.include_router(videos.flag_router)
app.include_router(watch.router)
app.include_router(stats.router)
app.include_router(media.router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> Response:
        if full_path.startswith(("api", "videos")):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(FRONTEND_DIST.resolve()):
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

else:

    @app.get("/", include_in_schema=False)
    async def missing_frontend() -> JSONResponse:
        return JSONResponse(
            {"detail": "Frontend not built. Run: cd frontend && npm install && npm run build"},
            status_code=200,
        )
