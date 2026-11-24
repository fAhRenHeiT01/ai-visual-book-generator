"""Typed, YAML-owned parsing and preflight parameters."""

import re
from typing import Annotated, Self

from pydantic import AfterValidator, Field, model_validator

from bookgen.schemas import AssetKind

from .base import StrictConfig


def _valid_pattern(value: str) -> str:
    try:
        re.compile(value)
    except re.error as exc:
        raise ValueError(f"Invalid profiling pattern: {exc}") from exc
    return value


Pattern = Annotated[str, AfterValidator(_valid_pattern)]


class BlockPatterns(StrictConfig):
    heading: Pattern
    list: Pattern
    quote: Pattern
    blank: Pattern
    word: Pattern


class GroupingConfig(StrictConfig):
    sentence_boundary: Pattern
    max_span_chars: int = Field(gt=0)
    max_spans: int = Field(gt=0)
    max_input_chars: int = Field(gt=0)


class ProfilingConfig(StrictConfig):
    # An empty optional module is accepted at configuration boot. Actual profiling
    # requires its YAML values rather than introducing duplicate Python defaults.
    thumbnail_max_px: int | None = Field(default=None, gt=0, le=768)
    allowed_mime_types: list[str] | None = Field(default=None, min_length=1)
    min_dpi: int | None = Field(default=None, gt=0)
    aspect_ratio_min: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    aspect_ratio_max: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    block_patterns: BlockPatterns | None = None
    chart_heuristics: dict[AssetKind, list[Pattern]] | None = None
    grouping: GroupingConfig | None = None

    @model_validator(mode="after")
    def ordered_aspect_bounds(self) -> Self:
        if self.aspect_ratio_min is not None and self.aspect_ratio_max is not None:
            if self.aspect_ratio_min > self.aspect_ratio_max:
                raise ValueError("aspect_ratio_min must not exceed aspect_ratio_max")
        return self

    def require_complete(self) -> Self:
        missing = [name for name in type(self).model_fields if getattr(self, name) is None]
        if missing:
            raise ValueError(f"Profiling settings are incomplete: {', '.join(missing)}")
        return self
