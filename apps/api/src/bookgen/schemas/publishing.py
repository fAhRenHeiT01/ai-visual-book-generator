"""Stable phase two envelopes. MVP handlers explicitly report unavailable features."""
from typing import Literal

from pydantic import Field, HttpUrl

from bookgen.schemas import AudienceMode, DesignTokens, MasterChromeConfig, MetricEntry, PageGenerationResult, StrictModel


class ComplianceMetric(StrictModel):
    page_id: str
    metric: MetricEntry
    decision: Literal["approve", "redact"] | None = None


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


class ThemeExtractResponse(StrictModel):
    status: Literal["available", "unavailable"] = "unavailable"
    tokens: DesignTokens | None = None


class SessionAppearance(StrictModel):
    tokens: DesignTokens
    chrome: MasterChromeConfig


class AppearanceResponse(SessionAppearance):
    status: Literal["available", "unavailable"] = "unavailable"
