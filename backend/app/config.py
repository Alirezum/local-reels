"""Environment-backed settings for Local Reels.

Values come from environment variables and an optional ``.env`` file in the
project root (see ``.env.example``).
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_path(value: str, *, base: Path | None = None) -> Path:
    """Resolve a configured path to an absolute path.

    ``~`` is expanded; absolute paths are used as-is; relative paths join
    ``base`` (working directory callers pass ``Path.cwd()`` explicitly,
    settings default to the project root) before resolving.
    """
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return ((base if base is not None else PROJECT_ROOT) / path).resolve()


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
        return resolve_path(self.video_dir)

    def resolved_db_path(self) -> Path:
        return resolve_path(self.db_path)


settings = Settings()
