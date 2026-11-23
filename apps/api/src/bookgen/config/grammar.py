from pydantic import Field

from .base import StrictConfig


class ArchetypeRule(StrictConfig):
    max_words: int = Field(gt=0)
    max_images: int = Field(ge=0)


class GrammarConfig(StrictConfig):
    full_bleed_hero: ArchetypeRule
    minimalist_swiss: ArchetypeRule
    section_divider: ArchetypeRule
    editorial_asymmetric: ArchetypeRule
    two_col_executive: ArchetypeRule
    top_media_narrative: ArchetypeRule
    chart_focus_band: ArchetypeRule
    guided_alternating: ArchetypeRule
    dashboard_split: ArchetypeRule
    modular_cards: ArchetypeRule
    safe_flow_fallback: ArchetypeRule
