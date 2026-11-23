"""Owned extension point for export YAML validation."""

from pydantic import Field
from .base import StrictConfig


class ExportConfig(StrictConfig):
    # Empty optional YAML remains valid for the settings loader's extension contract.
    chunk_pages: int | None = Field(default=None, ge=1, le=25)
    max_contexts: int | None = Field(default=None, ge=1)
    safety_buffer_percent: float | None = Field(default=None, ge=5, le=8)
    max_drift_retries: int | None = Field(default=None, ge=0, le=1)
    min_ssim: float | None = Field(default=None, gt=0, le=1)
    print_origin: str | None = None
    ready_timeout_ms: int | None = Field(default=None, gt=0)

    def require_complete(self):
        if any(getattr(self, name) is None for name in type(self).model_fields):
            raise ValueError('Export settings are incomplete')
        return self
