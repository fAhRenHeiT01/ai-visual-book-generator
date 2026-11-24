"""Canonical pointer-based contracts shared through the v1 OpenAPI document."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AudienceMode(str, Enum):
    INTERNAL = "internal"
    CLIENT_FACING = "client_facing"


class PageSize(str, Enum):
    A4 = "A4"
    US_LETTER = "LETTER"


class BookDirection(str, Enum):
    AUTO = "auto"
    BRAND_LED_EDITORIAL = "brand_led_editorial"
    CONSULTING_REPORT = "consulting_report"
    CAMPAIGN_PRESENTATION = "campaign_presentation"


Composition = Literal["flow", "opener", "comparison", "portrait_story"]
SurfaceTreatment = Literal["plain", "brand_panel", "tinted_band"]
EmphasisTreatment = Literal["balanced", "headline", "evidence", "testimonial"]
MediaPlacement = Literal["in_flow", "panoramic", "paired", "portrait_rail", "protected"]


class AssetKind(str, Enum):
    PHOTO = "photo"
    CHART = "chart"
    DIAGRAM = "diagram"
    LOGO = "logo"


class MetricClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    UNDISCLOSED = "undisclosed"
    UNVERIFIED = "unverified"


class LayoutArchetype(str, Enum):
    FULL_BLEED_HERO = "full_bleed_hero"
    MINIMALIST_SWISS = "minimalist_swiss"
    SECTION_DIVIDER = "section_divider"
    EDITORIAL_ASYMMETRIC = "editorial_asymmetric"
    TWO_COL_EXECUTIVE = "two_col_executive"
    TOP_MEDIA_NARRATIVE = "top_media_narrative"
    CHART_FOCUS_BAND = "chart_focus_band"
    GUIDED_ALTERNATING = "guided_alternating"
    DASHBOARD_SPLIT = "dashboard_split"
    MODULAR_CARDS = "modular_cards"
    SAFE_FLOW_FALLBACK = "safe_flow_fallback"


class SurfaceRole(str, Enum):
    PAPER = "paper"
    SURFACE_TINT = "surface_tint"
    BRAND_DARK = "brand_dark"
    ACCENT_SOFT = "accent_soft"


class ComponentType(str, Enum):
    HEADING = "heading"
    BODY_PROSE = "body_prose"
    BULLET_LIST = "bullet_list"
    IMAGE_FRAME = "image_frame"
    PULL_QUOTE = "pull_quote"
    STAT_CALLOUT = "stat_callout"
    CAPTION = "caption"
    DIVIDER_RULE = "divider_rule"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DesignTokens(StrictModel):
    theme_id: str
    palette_source: str = Field(description="preset | manual | website_extracted")
    color_paper: str = "#FFFFFF"
    color_ink_primary: str = "#111827"
    color_ink_muted: str = "#4B5563"
    color_brand_primary: str = "#1D4ED8"
    color_brand_accent: str = "#0EA5E9"
    color_surface_tint: str = "#F3F4F6"
    font_heading: str = "Inter"
    font_body: str = "Source Serif 4"
    radius_px: int = Field(default=6, ge=0, le=24)
    page_margin_mm: float = Field(default=16.0, ge=10.0, le=30.0)
    chrome_band_mm: float = Field(default=12.0, ge=0.0, le=20.0)


class MasterChromeConfig(StrictModel):
    enabled: bool = True
    header_left: str = ""
    header_right: str = "{chapter_title}"
    footer_left: str = ""
    footer_center: str = ""
    footer_right: str = "Page {page_number} of {total_pages}"
    suppress_on_archetypes: list[LayoutArchetype] = Field(
        default_factory=lambda: [LayoutArchetype.FULL_BLEED_HERO, LayoutArchetype.SECTION_DIVIDER]
    )


class BookContext(StrictModel):
    title: str = ""
    objective: str = ""
    tone_keywords: list[str] = Field(default_factory=list)
    audience_mode: AudienceMode = AudienceMode.INTERNAL
    page_size: PageSize = PageSize.A4
    source_website_url: str | None = None
    direction: BookDirection = Field(default_factory=lambda: BookDirection.AUTO)
    resolved_direction: Literal["brand_led_editorial", "consulting_report", "campaign_presentation"] | None = Field(default_factory=lambda: None)


class SourceMetricAnnotation(StrictModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    classification: MetricClassification


class SourceSpan(StrictModel):
    span_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    source_block_id: str
    text: str
    kind: str


class SpanGroup(StrictModel):
    span_ids: list[str] = Field(min_length=1)
    role: Literal["heading", "prose", "list", "quote", "metric", "fact", "shoutout"]


class SourceGrouping(StrictModel):
    groups: list[SpanGroup]


class AtomicTextBlock(StrictModel):
    block_id: str
    kind: str
    text: str
    word_count: int
    char_count: int
    source_span_ids: list[str] = Field(default_factory=list)
    source_start: int | None = Field(default_factory=lambda: None, ge=0)
    source_end: int | None = Field(default_factory=lambda: None, ge=0)
    metric_annotations: list[SourceMetricAnnotation] = Field(default_factory=list)


class ImageAssetMeta(StrictModel):
    asset_id: str
    storage_key: str
    thumbnail_key: str | None = None
    mime_type: str
    width_px: int
    height_px: int
    aspect_ratio: float
    estimated_dpi: int | None = None
    asset_kind: AssetKind = AssetKind.PHOTO
    alt_caption: str = ""


class MetricEntry(StrictModel):
    metric_id: str
    source_block_id: str
    raw_value: str
    context_snippet: str
    classification: MetricClassification
    approved_for_export: bool = False


class PlacedComponent(StrictModel):
    component_id: str
    component_type: ComponentType
    slot_id: str
    source_block_ids: list[str] = Field(default_factory=list)
    source_asset_id: str | None = None
    extracted_excerpt: str | None = None
    object_fit: str = "contain"
    surface_role: SurfaceRole = SurfaceRole.PAPER
    emphasis: bool = False


class PageLayoutAST(StrictModel):
    option_id: str
    strategy_tag: str
    archetype: LayoutArchetype
    rationale: str = Field(max_length=280)
    surface_role: SurfaceRole = SurfaceRole.PAPER
    density_scale: str = "normal"
    components: list[PlacedComponent]
    column_count: int = Field(default=1, ge=1, le=3)
    composition: Composition = Field(default_factory=lambda: "flow")
    surface_treatment: SurfaceTreatment = Field(default_factory=lambda: "plain")
    emphasis_treatment: EmphasisTreatment = Field(default_factory=lambda: "balanced")
    media_placement: MediaPlacement = Field(default_factory=lambda: "in_flow")


class ValidationIssue(StrictModel):
    code: str
    severity: str
    message: str
    target_option: str


class PageGenerationResult(StrictModel):
    page_id: str
    page_number: int
    input_blocks: list[AtomicTextBlock]
    input_assets: list[ImageAssetMeta]
    metrics_ledger: list[MetricEntry]
    option_a: PageLayoutAST
    option_b: PageLayoutAST
    selected_option_id: str | None = None
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    repair_attempts: int = 0
    used_fallback: bool = False


# Explicit roots include contracts that are not yet referenced by an API route.
CONTRACT_MODELS = (
    StrictModel, DesignTokens, MasterChromeConfig, BookContext, AtomicTextBlock,
    ImageAssetMeta, MetricEntry, PlacedComponent, PageLayoutAST, ValidationIssue,
    PageGenerationResult,
    SourceSpan, SpanGroup, SourceGrouping, SourceMetricAnnotation,
)
