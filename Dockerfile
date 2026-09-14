# --- Stage 1: build the Vue frontend -----------------------------
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python backend + built frontend ---------------------
FROM python:3.13-slim
# ffmpeg provides ffprobe for accurate video durations.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY backend ./backend
RUN pip install --no-cache-dir .

COPY --from=frontend /build/dist ./frontend/dist

ENV VIDEO_DIR=/data/videos \
    DB_PATH=/data/db/localreel.db \
    HOST=0.0.0.0 \
    PORT=8000

VOLUME ["/data/videos", "/data/db"]
EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.app.main:app --host ${HOST} --port ${PORT}"]
