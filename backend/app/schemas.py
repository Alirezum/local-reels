"""Pydantic request/response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VideoOut(BaseModel):
    id: str
    filename: str  # display name (basename)
    relpath: str  # path relative to the video dir, used for the stream URL
    type: str  # "video" | "image"
    url: str
    duration: float
    size: int
    favorite: bool = False
    created_at: str


class FlagIn(BaseModel):
    video_id: str
    favorite: bool | None = None
    blocked: bool | None = None


class MoveIn(BaseModel):
    video_id: str
    folder: str = ""


class FolderOut(BaseModel):
    name: str
    count: int


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


class FolderStatOut(BaseModel):
    folder: str
    watch_seconds: float
    views: int


class BatchNewIn(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    size: int = Field(ge=1, le=500)
    folder: str | None = None


class BatchContinueIn(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    from_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class BatchAddIn(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class BatchReplaceIn(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    old_id: str
    new_id: str


class BatchOut(BaseModel):
    date: str
    size: int
    folder: str | None = None
    videos: list[VideoOut]
