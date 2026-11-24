"""Renderer slot grammar and domain policies; null capacities mean reflow."""

from typing import Literal

from pydantic import Field, model_validator

from bookgen.schemas import (AssetKind, AudienceMode, BookDirection, ComponentType,
    LayoutArchetype, Composition, SurfaceTreatment, EmphasisTreatment, MediaPlacement, SurfaceRole)

from .base import StrictConfig


SlotId = Literal["header", "body", "col_left", "col_right", "media_main",
                 "media_secondary", "callout", "footer"]
SlotRole = Literal["text", "media", "mixed", "decoration"]


class SlotRule(StrictConfig):
    role: SlotRole
    max_chars: int | None = Field(ge=0)
    allows_overlay: bool


class ArchetypeRule(StrictConfig):
    family: str = Field(min_length=1)
    renderer_shape: Literal["full_page", "media_prose_split", "column_flow", "minimalist_swiss",
                            "top_media_narrative", "chart_focus_band", "dashboard_split", "modular_cards"]
    max_words: int | None = Field(gt=0)
    max_images: int | None = Field(ge=0)
    slots: dict[SlotId, SlotRule] = Field(min_length=1)
    reflow: bool
    column_count: int = Field(ge=1, le=3)
    fallback_body_slot: SlotId
    fallback_media_slot: SlotId

    @model_validator(mode="after")
    def check_fallback_slots(self) -> "ArchetypeRule":
        if self.fallback_body_slot not in self.slots or self.fallback_media_slot not in self.slots:
            raise ValueError("Fallback slots must belong to the archetype")
        if not self.reflow and (self.max_words is None or self.max_images is None
                                or any(s.max_chars is None for s in self.slots.values())):
            raise ValueError("Unbounded capacities require a reflow-capable renderer")
        return self


class DirectionRule(StrictConfig):
    direction: BookDirection
    keywords: list[str]
    audiences: list[AudienceMode] = Field(default_factory=list)


class DirectionStyle(StrictConfig):
    surface_a: SurfaceTreatment
    surface_b: SurfaceTreatment
    emphasis_a: EmphasisTreatment
    emphasis_b: EmphasisTreatment


class TreatmentRule(StrictConfig):
    composition: Composition
    media_placement: MediaPlacement
    emphasis_a: EmphasisTreatment
    emphasis_b: EmphasisTreatment
    required_roles: list[str] = Field(default_factory=list)
    asset_kinds: list[AssetKind] = Field(default_factory=list)
    min_assets: int = Field(default=0, ge=0)
    max_words: int | None = Field(default=None, gt=0)
    min_aspect_ratio: float | None = Field(default=None, gt=0)
    max_aspect_ratio: float | None = Field(default=None, gt=0)
    archetypes_a: list[LayoutArchetype]
    archetypes_b: list[LayoutArchetype]


class ComponentTreatment(StrictConfig):
    section_dividers: bool
    heading_emphasis: bool
    focal_emphasis: bool
    focal_surface: SurfaceRole


class RationaleConfig(StrictConfig):
    layout: str = Field(min_length=1)
    media: str = Field(min_length=1)
    no_text: str = Field(min_length=1)
    no_media: str = Field(min_length=1)


class ArtDirectionConfig(StrictConfig):
    default_direction: BookDirection
    auto_rules: list[DirectionRule]
    styles: dict[BookDirection, DirectionStyle]
    treatments: list[TreatmentRule] = Field(min_length=1)
    role_components: dict[str, ComponentType]
    focal_components: dict[str, ComponentType]
    heading_slot: SlotId
    focal_slot: SlotId
    protected_forbidden_placements: list[MediaPlacement]
    component_treatments: dict[Literal['option_a', 'option_b'], ComponentTreatment]
    divider_component: Literal[ComponentType.DIVIDER_RULE]
    rationale: RationaleConfig


class GrammarConfig(StrictConfig):
    art_direction: ArtDirectionConfig
    density_scales: list[Literal["airy", "normal", "compact"]] = Field(min_length=1)
    object_fits: list[Literal["contain", "cover"]] = Field(min_length=1)
    protected_asset_kinds: list[AssetKind] = Field(min_length=1)
    protected_object_fit: Literal["contain"]
    forbid_protected_overlay: bool
    body_component_types: list[ComponentType] = Field(min_length=1)
    excerpt_component_types: list[ComponentType] = Field(min_length=1)
    slot_role_components: dict[SlotRole, list[ComponentType]]
    fallback_order: list[LayoutArchetype] = Field(min_length=2)
    fallback_density: Literal["airy", "normal", "compact"]
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

    def archetypes(self) -> dict[LayoutArchetype, ArchetypeRule]:
        """Return canonical enum order, independent of YAML key ordering."""
        return {archetype: getattr(self, archetype.value) for archetype in LayoutArchetype}

    @model_validator(mode="after")
    def check_policies(self) -> "GrammarConfig":
        if self.fallback_density not in self.density_scales or self.protected_object_fit not in self.object_fits:
            raise ValueError("Fallback density and protected fit must be permitted")
        for rule in self.archetypes().values():
            for slot in rule.slots.values():
                if slot.role not in self.slot_role_components:
                    raise ValueError("Every slot role must define its permitted components")
        return self
