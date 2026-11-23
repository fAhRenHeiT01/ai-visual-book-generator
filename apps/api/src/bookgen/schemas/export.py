"""Strict assembly input and immutable print manifest contracts."""
from typing import Literal
from pydantic import Field
from bookgen.schemas import BookContext, DesignTokens, MasterChromeConfig, PageGenerationResult, StrictModel


class AssemblyOptions(StrictModel):
    imprint: str | None = None
    preface: str | None = None
    appendix: str | None = None
    closing_cover: bool = False
    section_titles: dict[str, str] = Field(default_factory=dict)


class TocEntry(StrictModel):
    title: str
    anchor: str
    page_number: int = Field(ge=1)


class PrintPage(StrictModel):
    kind: Literal['cover', 'imprint', 'preface', 'toc', 'section', 'body', 'appendix', 'closing_cover']
    anchor: str
    title: str
    chapter_title: str
    page_number: int = Field(ge=1)
    total_pages: int = Field(ge=1)
    result: PageGenerationResult
    expected_text: list[str]


class PrintManifest(StrictModel):
    session_id: str
    context: BookContext
    tokens: DesignTokens
    chrome: MasterChromeConfig
    pages: list[PrintPage]
    toc: list[TocEntry]
    safety_buffer_percent: float = Field(ge=5, le=8)
