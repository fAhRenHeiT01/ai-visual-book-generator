"""Resolve book intent once and derive named arrangements from bounded page facts."""

from bookgen.config import load_settings
from bookgen.schemas import BookContext, BookDirection, ComponentType


def resolve_direction(context: BookContext, *, grammar=None) -> BookContext:
    """Explicit intent wins; a saved Auto result survives palette/size changes."""
    if context.direction != BookDirection.AUTO:
        return context.model_copy(update={'resolved_direction': context.direction.value})
    if context.resolved_direction is not None:
        return context
    config = (grammar or load_settings().grammar).art_direction
    text = ' '.join([context.objective, *context.tone_keywords]).casefold()
    selected = config.default_direction
    for rule in config.auto_rules:
        if ((not rule.keywords or any(word.casefold() in text for word in rule.keywords))
                and (not rule.audiences or context.audience_mode in rule.audiences)):
            selected = rule.direction
            break
    return context.model_copy(update={'resolved_direction': selected.value})


def eligible_treatments(blocks, assets, *, grammar):
    """No source text leaves this process beyond the current-page payload."""
    words = sum(len(block.text.split()) for block in blocks)
    roles = {block.kind for block in blocks}
    eligible = []
    for rule in grammar.art_direction.treatments:
        matches = [asset for asset in assets
            if (not rule.asset_kinds or asset.asset_kind in rule.asset_kinds)
            and (rule.min_aspect_ratio is None or asset.aspect_ratio >= rule.min_aspect_ratio)
            and (rule.max_aspect_ratio is None or asset.aspect_ratio <= rule.max_aspect_ratio)]
        if (len(matches) >= rule.min_assets
                and set(rule.required_roles) <= roles
                and (rule.max_words is None or words <= rule.max_words)
                and not (rule.media_placement in grammar.art_direction.protected_forbidden_placements
                    and any(asset.asset_kind in grammar.protected_asset_kinds for asset in assets))):
            eligible.append(rule)
    return eligible


def supported_components(context, blocks, *, grammar, metrics=None, compliance=None):
    """Suggest source-backed roles; metric promotion also needs compliance evidence."""
    from bookgen.domain.compliance import callout_eligible, compliance_metrics_scan
    metrics = metrics if metrics is not None else compliance_metrics_scan(blocks, config=compliance)
    design = grammar.art_direction
    supported = {}
    for block in blocks:
        kinds = [design.role_components.get(block.kind, ComponentType.BODY_PROSE)]
        focal = design.focal_components.get(block.kind)
        if focal == ComponentType.STAT_CALLOUT:
            found = [metric for metric in metrics if metric.source_block_id == block.block_id]
            if not found or not all(callout_eligible(metric, context.audience_mode, config=compliance) for metric in found):
                focal = None
        if focal is not None:
            kinds.append(focal)
        supported[block.block_id] = kinds
    return supported


def section_boundaries(blocks, *, grammar):
    """A later source heading starts a section; decoration never invents a title."""
    return [block.block_id for i, block in enumerate(blocks)
        if i and grammar.art_direction.role_components.get(block.kind) == ComponentType.HEADING]


def arrangement_context(context, blocks, assets, *, grammar, compliance=None):
    resolved = resolve_direction(context, grammar=grammar)
    return {'direction': resolved.resolved_direction,
        'style': grammar.art_direction.styles[resolved.resolved_direction].model_dump(mode='json'),
        'eligible_treatments': [rule.model_dump(mode='json') for rule in eligible_treatments(blocks, assets, grammar=grammar)],
        'supported_components': supported_components(resolved, blocks, grammar=grammar, compliance=compliance),
        'section_boundaries': section_boundaries(blocks, grammar=grammar),
        'component_treatments': {option: treatment.model_dump(mode='json')
            for option, treatment in grammar.art_direction.component_treatments.items()},
        'semantic_groups': [{'block_id': block.block_id, 'role': block.kind,
            'word_count': len(block.text.split()), 'char_count': len(block.text)} for block in blocks]}
