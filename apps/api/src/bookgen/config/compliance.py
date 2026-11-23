from pydantic import Field

from .base import StrictConfig


class ComplianceConfig(StrictConfig):
    tags: list[str] = Field(min_length=1)
