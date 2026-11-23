"""Typed extraction limits and palettes, activated by the existing YAML loader."""

import re
from pydantic import Field, model_validator
from bookgen.schemas import DesignTokens
from .base import StrictConfig


class ThemeConfig(StrictConfig):
    # Preserve the loader's empty optional-module contract without Python defaults.
    preset_palettes: dict[str, DesignTokens] | None = Field(default=None, min_length=1)
    default_preset: str | None = None
    contrast_min_ratio: float | None = Field(default=None, ge=1, le=21)
    max_response_bytes: int | None = Field(default=None, gt=0)
    timeout_seconds: float | None = Field(default=None, gt=0)
    max_redirects: int | None = Field(default=None, ge=0)
    color_pattern: str | None = None
    css_color_pattern: str | None = None
    css_primary_names: list[str] | None = None
    css_accent_names: list[str] | None = None
    logo_thumbnail_size: int | None = Field(default=None, gt=0, le=768)

    @model_validator(mode='after')
    def validate_patterns_and_preset(self):
        for pattern in (self.color_pattern, self.css_color_pattern):
            if pattern is not None:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise ValueError('Invalid theme pattern') from exc
        if self.preset_palettes and self.default_preset not in self.preset_palettes:
            raise ValueError('Default theme preset must exist')
        return self

    def require_complete(self):
        if any(getattr(self, name) is None for name in type(self).model_fields):
            raise ValueError('Theme settings are incomplete')
        return self
