"""Strict provider settings and versioned, repository-owned prompt documents."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
import yaml

from .base import StrictConfig


class LLMConfig(StrictConfig):
    provider: Literal["gemini", "mock"]
    transport_mode: Literal["developer", "vertex"]
    model: str = Field(min_length=1)
    max_repair_retries: int = Field(ge=0)
    temperature: float = Field(ge=0, le=2)
    prompt_cache_ttl_seconds: int = Field(ge=0, validation_alias=AliasChoices("cache_ttl_seconds", "prompt_cache_ttl_seconds"))
    rhythm_window: int = Field(ge=1, le=3)
    strategy_families: dict[str, str]
    explicit_cache: bool


class PromptDocument(StrictConfig):
    version: str = Field(min_length=1)
    text: str = Field(min_length=1)


def load_prompts(directory: Path | None = None) -> dict[str, PromptDocument]:
    directory = directory or Path(__file__).resolve().parents[5] / "config/prompts"
    return {name: PromptDocument.model_validate(yaml.safe_load((directory / f"{name}.yaml").read_text(encoding="utf-8")))
            for name in ("system_art_director", "strategy_option_a", "strategy_option_b", "critic_repair")}
