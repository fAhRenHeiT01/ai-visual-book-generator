"""Stable source-pointer placement using configured reflow-capable families."""

from collections.abc import Sequence

from bookgen.config import load_settings
from bookgen.config.grammar import GrammarConfig
from bookgen.schemas import (
    AtomicTextBlock, ComponentType, ImageAssetMeta, LayoutArchetype,
    PageLayoutAST, PlacedComponent,
)


def safe_fallback_builder(
    source_blocks: Sequence[AtomicTextBlock],
    source_assets: Sequence[ImageAssetMeta],
    recent_archetypes: Sequence[LayoutArchetype | str] = (),
    *, grammar: GrammarConfig | None = None,
) -> tuple[PageLayoutAST, PageLayoutAST]:
    """Return two eligible families, preserving input and pointer order exactly.

    Unbounded capacities are explicit grammar declarations for reflow renderers.
    Invalid custom grammar fails explicitly rather than returning an invalid AST.
    """
    grammar = grammar if grammar is not None else load_settings().grammar
    rules = grammar.archetypes()
    words = sum(len(b.text.split()) for b in source_blocks)
    chars = sum(len(b.text) for b in source_blocks)
    selected: list[PageLayoutAST] = []
    families: set[str] = set()
    for archetype in grammar.fallback_order:
        rule = rules[archetype]
        if archetype in recent_archetypes or rule.family in families:
            continue
        if rule.max_words is not None and words > rule.max_words:
            continue
        if rule.max_images is not None and len(source_assets) > rule.max_images:
            continue
        body = rule.slots[rule.fallback_body_slot]
        media = rule.slots[rule.fallback_media_slot]
        if body.max_chars is not None and chars > body.max_chars:
            continue
        if (ComponentType.BODY_PROSE not in grammar.slot_role_components[body.role]
                or ComponentType.IMAGE_FRAME not in grammar.slot_role_components[media.role]
                or rule.fallback_body_slot == rule.fallback_media_slot):
            continue
        components = [PlacedComponent(component_id=f"text_{i}", component_type=ComponentType.BODY_PROSE,
            slot_id=rule.fallback_body_slot, source_block_ids=[block.block_id])
            for i, block in enumerate(source_blocks)]
        components.extend(PlacedComponent(component_id=f"media_{i}", component_type=ComponentType.IMAGE_FRAME,
            slot_id=rule.fallback_media_slot, source_asset_id=asset.asset_id,
            object_fit=grammar.protected_object_fit) for i, asset in enumerate(source_assets))
        selected.append(PageLayoutAST(option_id="option_a" if not selected else "option_b",
            strategy_tag=rule.family, archetype=archetype, rationale="Complete source content in a stable reflow layout.",
            density_scale=grammar.fallback_density, column_count=rule.column_count, components=components))
        families.add(rule.family)
        if len(selected) == 2:
            return selected[0], selected[1]
    raise ValueError("Grammar does not provide two distinct eligible families for these inputs and exclusions.")
