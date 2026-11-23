from pathlib import Path

from pydantic import Field

from .base import StrictConfig


class AppConfig(StrictConfig):
    storage_root: Path
    sqlite_uri: str = Field(min_length=1)
    cors_origins: list[str] = Field(min_length=1)
