from pydantic import Field

from .base import StrictConfig


class LLMConfig(StrictConfig):
    model: str = Field(min_length=1)
    max_repair_retries: int = Field(ge=0)
    temperature: float = Field(ge=0, le=2)
    prompt_cache_ttl_seconds: int = Field(ge=0)
