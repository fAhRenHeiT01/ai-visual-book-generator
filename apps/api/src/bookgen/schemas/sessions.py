"""Strict request and persisted session envelopes exported through OpenAPI."""

from typing import Literal

from pydantic import Field, model_validator

from bookgen.schemas import BookContext, ImageAssetMeta, LayoutArchetype, PageGenerationResult, StrictModel


class CreateSessionRequest(StrictModel):
    context: BookContext = Field(default_factory=BookContext)


class GeneratePageRequest(StrictModel):
    text: str = ""
    asset_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_content(self):
        if not self.text.strip() and not self.asset_ids:
            raise ValueError("Provide text or uploaded asset IDs")
        if len(set(self.asset_ids)) != len(self.asset_ids):
            raise ValueError("Uploaded asset IDs must be unique")
        return self


class SelectOptionRequest(StrictModel):
    option_id: Literal["option_a", "option_b"]


class AssetUploadResponse(StrictModel):
    assets: list[ImageAssetMeta]


class SessionSnapshot(StrictModel):
    session_id: str
    debug_enabled: bool = False
    debug_active: bool = False
    context: BookContext
    current_page_index: int = Field(default=1, ge=1)
    pending_review: PageGenerationResult | None = None
    committed_pages: list[PageGenerationResult] = Field(default_factory=list)
    rolling_layout_history: list[LayoutArchetype] = Field(default_factory=list)
    assets: list[ImageAssetMeta] = Field(default_factory=list)
