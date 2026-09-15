# Local Reels

A self-hosted, Instagram-style **Reels** player for videos that already live on your
machine — plus a personal watch-time analytics dashboard. No accounts, no uploads,
no feed, no likes: just your folder of videos, shuffled into a full-screen vertical
feed, with accurate stats on what you actually watched.

- **Backend:** FastAPI (Python 3.10+, async, type hints) + SQLite (aiosqlite)
- **Frontend:** Vue 3 (Composition API) + Vite + Chart.js
- **Media:** any local directory you configure — changeable at runtime, no code edits

## Features

**Reels feed (`/`)**

- Full-screen vertical scroll-snap feed, TikTok/Instagram-style
- Plays **videos and photos** from any folder, **recursively** (subfolders included)
- Photos just sit there until you swipe — no auto-advance
- Autoplay when in view, pause + rewind when out of view, videos loop
- **Discovery shuffle** (default): less-watched media appears more often; toggle 🎲/🌱 (or `s`) for pure random
- **Folder filter** and **favorites-only** mode in the header (📂 / ♥)
- **Favorite** (♡/♥) and **hide** (🚫 "don't show again") any reel; hidden items can be un-hidden from the dashboard
- Tap to play/pause, mute/unmute toggle (remembered), thin progress bar, rotate (⟳ / `r`)
- Keyboard: `↑` / `↓` navigate, `Space` play/pause, `m` mute, `s` shuffle, `r` rotate
- Broken/undecodable files are flagged and skipped, the feed keeps going

**Analytics dashboard (`/dashboard`)**

- Cards: total watch time, total views, videos watched, average per view
- Line chart of daily (or weekly) watch time over 7/30/90 days
- Bar chart + table of most-watched videos, and a **watch-time-by-folder** doughnut
- **Hidden items** manager (un-hide anything you 🚫'd from the feed)
- A "view" is one continuous watch session (gaps ≥ 30 s start a new one), so
  totals and averages aren't inflated by the ~5 s watch-time flushes
- Watch time is tracked *accurately*: only while the active video is actually
  playing, accounting for pauses, tab switches, and page unload

## Quickstart (local)

Prerequisites: [uv](https://docs.astral.sh/uv/) (or any Python ≥ 3.10) and Node.js ≥ 18.
`ffprobe` (from `ffmpeg`) is optional but recommended — it provides accurate video
durations (`sudo apt install ffmpeg` / `brew install ffmpeg`).

```bash
# 1. Configure — point VIDEO_DIR at your own folder
cp .env.example .env
#    edit .env, e.g.  VIDEO_DIR=/home/me/Videos/reels

# 2. Backend
uv sync                      # installs deps into .venv/  (or: pip install -e .)
uv run python -m backend     # API + built frontend on http://127.0.0.1:8000

# 3. Frontend (one-time build, then FastAPI serves it)
cd frontend && npm install && npm run build
```

Open **http://127.0.0.1:8000** for Reels and **http://127.0.0.1:8000/dashboard**
for stats. (Build the frontend before starting the backend, or restart the backend
after building — it picks up `frontend/dist` at startup.)

### Development mode (hot reload)

```bash
uv run uvicorn backend.app.main:app --reload --port 8000   # terminal 1
cd frontend && npm run dev                                 # terminal 2 → http://localhost:5173
```

The Vite dev server proxies `/api` and `/videos` to port 8000.

## Configuration

| Env var     | Default               | Meaning                                            |
| ----------- | --------------------- | -------------------------------------------------- |
| `VIDEO_DIR` | `./videos`            | Folder scanned recursively for video files and photos (absolute or relative to project root) |
| `DB_PATH`   | `./data/localreel.db` | SQLite file (created automatically)                 |
| `HOST`      | `127.0.0.1`           | Bind host for `python -m backend`                   |
| `PORT`      | `8000`                | Bind port for `python -m backend`                   |

Values are read from environment variables or a `.env` file (see `.env.example`).

**Changing the folder at runtime:** use the panel on the dashboard’s *Settings* card
(or the empty-feed screen). It calls `POST /api/config`; the new path is stored in
the database and takes precedence over `.env` until the app is inspected from the
API. Relative paths resolve against the server’s working directory.

Supported **video** extensions: `.mp4 .webm .mov .m4v .mkv .avi .ogv .ogg`
(browsers play mp4/webm reliably; mkv/avi may not decode even though they’re listed).

Supported **image** extensions: `.jpg .jpeg .png .webp .gif .avif .bmp`.

The scan is recursive: media in subfolders are included and shown by their
relative path (e.g. `trips/paris.mp4`). Hidden files and `.dot`-folders are
skipped, and symlinked directories are not followed (no cycles).

## API

| Method | Path                      | Description                                             |
| ------ | ------------------------- | ------------------------------------------------------- |
| GET    | `/api/videos`             | All media in the folder + metadata (id, filename, relpath, type, url, duration, size, favorite) |
| GET    | `/api/videos/random`      | Server-shuffled list (`?limit=25&order=weighted\|random&folder=CSM&favorites=true`) |
| GET    | `/api/videos/folders`     | Top-level folders (incl. `(root)`) with visible counts |
| POST   | `/api/flags`              | Set `favorite` and/or `blocked` on a video (`{video_id, favorite?, blocked?}`) |
| GET    | `/api/blocked`            | Hidden (blocked) items, for the dashboard un-hide list |
| POST   | `/api/watch`              | Record `{video_id, start_time, end_time, duration_watched}` |
| GET    | `/api/stats/summary`      | Total watch time, view *sessions*, distinct videos watched |
| GET    | `/api/stats/top-videos`   | Most watched media (`?limit=10`)                        |
| GET    | `/api/stats/daily`        | Watch time per day, zero-filled (`?days=30`)            |
| GET    | `/api/stats/folders`      | Watch time & views grouped by top-level folder (`?days=30`) |
| GET    | `/api/config`             | Current video directory, exists?, count                 |
| POST   | `/api/config`             | Change video directory at runtime (`{"video_dir": "…"}`) |
| GET    | `/videos/{relpath}`       | Stream a video/photo (recursive; HTTP Range / 206 supported) |

Interactive docs at `http://127.0.0.1:8000/docs`.

`type` is `"video"` or `"image"`. `relpath` is the file’s path relative to the
media directory and doubles as the display name and stream key.

## Database schema

```sql
videos(id PK, filename UNIQUE /* rel. POSIX path */, path, type, duration, size, mtime, removed, created_at)
watch_events(id PK, video_id → videos, start_time, end_time, duration_watched, created_at)
user_flags(video_id PK → videos, favorite, blocked, updated_at)   -- your hearts & 🚫 (kept separate from the disk scan)
config(key PK, value)   -- runtime settings, e.g. video_dir
```

Flags are keyed by the stable relative-path ID, so they survive rescans; renaming
or moving a file on disk gives it a new ID (flags and stats start fresh for it).

A lightweight runtime migration adds the `type` column to databases created
before image support, so existing watch history is preserved across upgrades.

Videos are (re)scanned on startup and whenever the API lists them; only new or
changed files are re-probed, so it stays cheap. Files deleted from disk are
flagged `removed` (hidden from the feed) but kept for historical stats.

## Docker

```bash
docker compose up --build
# Reels: http://localhost:8000  ·  Dashboard: http://localhost:8000/dashboard
```

Put your videos in `./videos` on the host (or edit the volume in
`docker-compose.yml`). The database persists in the named `reel-data` volume.

## Edge cases handled

- **No media found** → friendly empty state showing the configured folder + inline
  directory picker
- **Invalid directory path** → startup logs a warning, feed shows the empty state;
  `POST /api/config` rejects non-directories with `400`
- **Undecodable / broken video or image** → the tile shows an error, the file is
  excluded from future shuffled batches
- **Missing `ffprobe`** → videos still play; durations report as 0 (images never probe)
- **Seeking / scrubbing** → Range requests implemented server-side (206 Partial
  Content, 416 on invalid ranges)
- **Path traversal** (`/videos/../../etc/passwd`, `/videos/a/../../etc/passwd`,
  URL-encoded variants) → 404; nested paths are resolved and confined to the media dir
- **Symlinked folders / scan cycles** → not followed during the recursive walk
- **Server unreachable / bad payload** → frontend surfaces the error with retry;
  lost watch chunks are dropped silently rather than blocking playback

## Project layout

```
backend/app/       FastAPI: config, db (aiosqlite), directory scanner,
                   video/config/watch/stats routers, range-streaming media route
frontend/src/      Vue 3 SPA: ReelsView + ReelItem, DashboardView (Chart.js),
                   useWatchTracker (accurate per-second accounting), ConfigPanel
data/              SQLite database (created at runtime)
videos/            default video folder (create your own, or set VIDEO_DIR)
```
