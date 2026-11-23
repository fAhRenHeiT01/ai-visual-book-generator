"""Shared strict configuration contract."""

from pydantic import BaseModel, ConfigDict


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
