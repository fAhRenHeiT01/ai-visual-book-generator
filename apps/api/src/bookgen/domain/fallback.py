"""Deterministic source-pointer layouts using the same named grammar as providers."""

from collections import defaultdict
from collections.abc import Sequence

from bookgen.config import load_settings
from bookgen.config.grammar import GrammarConfig
from bookgen.domain.direction import eligible_treatments, resolve_direction
from bookgen.schemas import (
    AtomicTextBlock, BookContext, ComponentType, ImageAssetMeta, LayoutArchetype,
    PageLayoutAST, PlacedComponent,
)


def safe_fallback_builder(
    source_blocks: Sequence[AtomicTextBlock],
    source_assets: Sequence[ImageAssetMeta],
    recent_archetypes: Sequence[LayoutArchetype | str] = (),
    *, grammar: GrammarConfig | None = None, context: BookContext | None = None,
    metrics=None, compliance=None,
) -> tuple[PageLayoutAST, PageLayoutAST]:
    """Preserve every full pointer; optional focal excerpts supplement body copy."""
    from bookgen.domain.compliance import callout_eligible, compliance_metrics_scan
    grammar = grammar if grammar is not None else load_settings().grammar
    context = resolve_direction(context or BookContext(), grammar=grammar)
    metrics = metrics if metrics is not None else compliance_metrics_scan(source_blocks, config=compliance)
    design = grammar.art_direction
    style = design.styles[context.resolved_direction]
    treatments = eligible_treatments(source_blocks, source_assets, grammar=grammar)
    rules = grammar.archetypes()
    words = sum(len(b.text.split()) for b in source_blocks)
    chars = sum(len(b.text) for b in source_blocks)
    selected: list[PageLayoutAST] = []
    families: set[str] = set()
    for option_id in ('option_a', 'option_b'):
        is_a = option_id == 'option_a'
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
                kind = design.role_components.get(block.kind, ComponentType.BODY_PROSE)
                if treatment.composition == 'opener' and i == 0:
                    kind = ComponentType.HEADING
                preferred = design.heading_slot if kind == ComponentType.HEADING else rule.fallback_body_slot
                components.append(PlacedComponent(component_id=f'text_{i}', component_type=kind,
                    slot_id=text_slot(preferred, kind, block.text), source_block_ids=[block.block_id],
                    emphasis=kind == ComponentType.HEADING))
            components.extend(PlacedComponent(component_id=f'media_{i}', component_type=ComponentType.IMAGE_FRAME,
                slot_id=('media_secondary' if i and 'media_secondary' in rule.slots else rule.fallback_media_slot),
                source_asset_id=asset.asset_id, object_fit=grammar.protected_object_fit)
                for i, asset in enumerate(source_assets))
            # A single exact focal element establishes hierarchy without rewriting copy.
            for i, block in enumerate(source_blocks):
                focal = design.focal_components.get(block.kind)
                if focal is None:
                    continue
                if focal == ComponentType.STAT_CALLOUT and (not any(m.source_block_id == block.block_id for m in metrics)
                        or any(m.source_block_id == block.block_id and not callout_eligible(m, context.audience_mode, config=compliance) for m in metrics)):
                    continue
                slot = rule.slots.get(design.focal_slot)
                if (slot is None or focal not in grammar.slot_role_components[slot.role]
                        or (slot.max_chars is not None and len(block.text) > slot.max_chars)):
                    continue
                components.append(PlacedComponent(component_id=f'focal_{i}', component_type=focal,
                    slot_id=design.focal_slot, source_block_ids=[block.block_id],
                    extracted_excerpt=block.text, emphasis=is_a))
                break
            page = PageLayoutAST(option_id=option_id, strategy_tag=rule.family, archetype=archetype,
                rationale='Source roles and media constraints establish a complete page hierarchy.',
                density_scale=grammar.fallback_density, column_count=rule.column_count, components=components,
                composition=treatment.composition, media_placement=treatment.media_placement,
                surface_treatment=style.surface_a if is_a else style.surface_b,
                emphasis_treatment=(treatment.emphasis_a if is_a else treatment.emphasis_b)
                    if treatment.composition != 'flow' else (style.emphasis_a if is_a else style.emphasis_b))
            selected.append(page)
            families.add(rule.family)
            break
        if len(selected) != (1 if is_a else 2):
            raise ValueError('Grammar does not provide two distinct eligible families for these inputs and exclusions.')
    return selected[0], selected[1]
