"""Deterministic source-pointer layouts using the same named grammar as providers."""

from collections import defaultdict
from collections.abc import Sequence

from bookgen.config import load_settings
from bookgen.config.grammar import GrammarConfig
from bookgen.domain.direction import eligible_treatments, resolve_direction, section_boundaries, supported_components
from bookgen.schemas import (
    AtomicTextBlock, BookContext, ComponentType, ImageAssetMeta, LayoutArchetype,
    PageLayoutAST, PlacedComponent,
)


def _rationale(page, assets, *, grammar):
    """Explain only the completed AST; unavailable focal slots cannot leak claims."""
    config = grammar.art_direction.rationale
    names = sorted({component.component_type.value.replace('_', ' ')
        for component in page.components if component.component_type != ComponentType.IMAGE_FRAME})
    asset_by_id = {asset.asset_id: asset for asset in assets}
    frames = [component for component in page.components if component.source_asset_id in asset_by_id]
    media = config.no_media
    if frames:
        media = config.media.format(
            kinds='/'.join(sorted({asset_by_id[frame.source_asset_id].asset_kind.value for frame in frames})),
            fit='/'.join(sorted({frame.object_fit for frame in frames})),
            placement=page.media_placement.replace('_', ' '))
    return config.layout.format(archetype=page.archetype.value.replace('_', ' '),
        columns=page.column_count, composition=page.composition.replace('_', ' '),
        surface=page.surface_treatment.replace('_', ' '), emphasis=page.emphasis_treatment.replace('_', ' '),
        components=', '.join(names) if names else config.no_text, media=media)


def safe_fallback_builder(
    source_blocks: Sequence[AtomicTextBlock],
    source_assets: Sequence[ImageAssetMeta],
    recent_archetypes: Sequence[LayoutArchetype | str] = (),
    *, grammar: GrammarConfig | None = None, context: BookContext | None = None,
    metrics=None, compliance=None,
) -> tuple[PageLayoutAST, PageLayoutAST]:
    """Preserve every full pointer; optional focal excerpts supplement body copy."""
    grammar = grammar if grammar is not None else load_settings().grammar
    context = resolve_direction(context or BookContext(), grammar=grammar)
    design = grammar.art_direction
    supported = supported_components(context, source_blocks, grammar=grammar, metrics=metrics, compliance=compliance)
    boundaries = set(section_boundaries(source_blocks, grammar=grammar))
    style = design.styles[context.resolved_direction]
    treatments = eligible_treatments(source_blocks, source_assets, grammar=grammar)
    rules = grammar.archetypes()
    words = sum(len(b.text.split()) for b in source_blocks)
    chars = sum(len(b.text) for b in source_blocks)
    selected: list[PageLayoutAST] = []
    families: set[str] = set()
    for option_id in ('option_a', 'option_b'):
        is_a = option_id == 'option_a'
        component_style = design.component_treatments[option_id]
        candidates = []
        for treatment in treatments:
            for archetype in treatment.archetypes_a if is_a else treatment.archetypes_b:
                candidates.append((archetype, treatment))
        candidates.extend((archetype, treatments[-1]) for archetype in grammar.fallback_order)
        for archetype, treatment in candidates:
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
            used_chars = defaultdict(int)

            def text_slot(preferred, kind, text):
                slot = rule.slots.get(preferred)
                if (slot is not None and kind in grammar.slot_role_components[slot.role]
                        and (slot.max_chars is None or used_chars[preferred] + len(text) <= slot.max_chars)):
                    used_chars[preferred] += len(text)
                    return preferred
                used_chars[rule.fallback_body_slot] += len(text)
                return rule.fallback_body_slot

            components = []
            for i, block in enumerate(source_blocks):
                kind = supported[block.block_id][0]
                if treatment.composition == 'opener' and i == 0:
                    kind = ComponentType.HEADING
                if (component_style.section_dividers and block.block_id in boundaries
                        and design.divider_component in grammar.slot_role_components[body.role]):
                    components.append(PlacedComponent(component_id=f'divider_{i}',
                        component_type=design.divider_component, slot_id=rule.fallback_body_slot))
                preferred = design.heading_slot if kind == ComponentType.HEADING and i == 0 else rule.fallback_body_slot
                components.append(PlacedComponent(component_id=f'text_{i}', component_type=kind,
                    slot_id=text_slot(preferred, kind, block.text), source_block_ids=[block.block_id],
                    emphasis=kind == ComponentType.HEADING and component_style.heading_emphasis))
            components.extend(PlacedComponent(component_id=f'media_{i}', component_type=ComponentType.IMAGE_FRAME,
                slot_id=('media_secondary' if i and 'media_secondary' in rule.slots else rule.fallback_media_slot),
                source_asset_id=asset.asset_id, object_fit=grammar.protected_object_fit)
                for i, asset in enumerate(source_assets))
            # A single exact focal element establishes hierarchy without rewriting copy.
            for i, block in enumerate(source_blocks):
                focal = design.focal_components.get(block.kind)
                if focal is None or focal not in supported[block.block_id]:
                    continue
                slot = rule.slots.get(design.focal_slot)
                if (slot is None or focal not in grammar.slot_role_components[slot.role]
                        or (slot.max_chars is not None and used_chars[design.focal_slot] + len(block.text) > slot.max_chars)):
                    continue
                components.append(PlacedComponent(component_id=f'focal_{i}', component_type=focal,
                    slot_id=design.focal_slot, source_block_ids=[block.block_id],
                    extracted_excerpt=block.text, emphasis=component_style.focal_emphasis,
                    surface_role=component_style.focal_surface))
                break
            page = PageLayoutAST(option_id=option_id, strategy_tag=rule.family, archetype=archetype,
                rationale='',
                density_scale=grammar.fallback_density, column_count=rule.column_count, components=components,
                composition=treatment.composition, media_placement=treatment.media_placement,
                surface_treatment=style.surface_a if is_a else style.surface_b,
                emphasis_treatment=(treatment.emphasis_a if is_a else treatment.emphasis_b)
                    if treatment.composition != 'flow' else (style.emphasis_a if is_a else style.emphasis_b))
            page.rationale = _rationale(page, source_assets, grammar=grammar)
            selected.append(PageLayoutAST.model_validate(page.model_dump()))
            families.add(rule.family)
            break
        if len(selected) != (1 if is_a else 2):
            raise ValueError('Grammar does not provide two distinct eligible families for these inputs and exclusions.')
    return selected[0], selected[1]
