"""Pydantic request/response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VideoOut(BaseModel):
    id: str
    filename: str  # display name (basename)
    relpath: str   # path relative to the video dir, used for the stream URL
    type: str      # "video" | "image"
    url: str
    duration: float
    size: int
    created_at: str


class WatchIn(BaseModel):
    video_id: str
    start_time: float
    end_time: float
    duration_watched: float = Field(ge=0, le=3600)


class ConfigIn(BaseModel):
    video_dir: str


class ConfigOut(BaseModel):
    video_dir: str
    exists: bool
    video_count: int


class SummaryOut(BaseModel):
    total_watch_seconds: float
    total_views: int
    videos_watched: int


class TopVideoOut(BaseModel):
    video_id: str
    filename: str
    watch_seconds: float
    views: int


class DailyOut(BaseModel):
    date: str
    watch_seconds: float
    views: int
