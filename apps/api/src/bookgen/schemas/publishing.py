"""Stable phase two envelopes. MVP handlers explicitly report unavailable features."""
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, StringConstraints

from bookgen.schemas import AudienceMode, DesignTokens, MasterChromeConfig, MetricEntry, PageGenerationResult, StrictModel


class ComplianceMetric(StrictModel):
    page_id: str
    metric: MetricEntry
    decision: Literal["approve", "redact"] | None = None
    source_start: int | None = Field(default=None, ge=0, description="Inclusive Unicode code point offset in the exact source block.")
    source_end: int | None = Field(default=None, ge=0, description="Exclusive Unicode code point offset in the exact source block.")


class ComplianceReport(StrictModel):
    status: Literal["available", "unavailable"] = "unavailable"
    ledger: list[ComplianceMetric] = Field(default_factory=list)
    eligible: bool = False
    audience_mode: AudienceMode = AudienceMode.INTERNAL
    publishable_pages: list[PageGenerationResult] = Field(default_factory=list)


class ComplianceDecision(StrictModel):
    page_id: str
    metric_id: str
    action: Literal["approve", "redact"]


class ThemeExtractRequest(StrictModel):
    url: HttpUrl
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None


class ThemeExtractResponse(StrictModel):
    status: Literal["available", "unavailable"] = "unavailable"
    tokens: DesignTokens | None = None
    theme_id: str | None = None


class ThemeLibraryEntry(StrictModel):
    theme_id: str
    name: str
    source_url: HttpUrl | None = None
    tokens: DesignTokens


class ThemeListResponse(StrictModel):
    themes: list[ThemeLibraryEntry] = Field(default_factory=list)


class ThemeApplyRequest(StrictModel):
    theme_id: str = Field(min_length=1)


class SessionAppearance(StrictModel):
    tokens: DesignTokens
    chrome: MasterChromeConfig


class AppearanceResponse(SessionAppearance):
    status: Literal["available", "unavailable"] = "unavailable"
