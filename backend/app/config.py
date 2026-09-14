"""Environment-backed settings for Local Reels.

Values come from environment variables and an optional ``.env`` file in the
project root (see ``.env.example``).
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    video_dir: str = str(PROJECT_ROOT / "videos")
    db_path: str = str(PROJECT_ROOT / "data" / "localreel.db")
    host: str = "127.0.0.1"
    port: int = 8000

    def resolved_video_dir(self) -> Path:
        p = Path(self.video_dir).expanduser()
        return (p if p.is_absolute() else PROJECT_ROOT / p).resolve()

    def resolved_db_path(self) -> Path:
        p = Path(self.db_path).expanduser()
        return (p if p.is_absolute() else PROJECT_ROOT / p).resolve()


settings = Settings()
