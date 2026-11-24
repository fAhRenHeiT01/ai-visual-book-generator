"""Fallback pairs retain all inputs and survive the three-archetype exclusion window."""

import importlib.util
from itertools import combinations

import pytest

from bookgen.config import load_settings
from bookgen.schemas import AtomicTextBlock, ImageAssetMeta


def builder():
    assert importlib.util.find_spec("bookgen.domain") is not None, "fallback domain must be implemented"
    assert importlib.util.find_spec("bookgen.domain.fallback") is not None, "safe fallback builder must be implemented"
    from bookgen.domain.fallback import safe_fallback_builder
    return safe_fallback_builder


def inputs(words, kinds):
    blocks = [AtomicTextBlock(block_id="b2", kind="paragraph", text="word " * words,
                              word_count=words, char_count=5 * words),
              AtomicTextBlock(block_id="b1", kind="paragraph", text="Last.", word_count=1, char_count=5)]
    assets = [ImageAssetMeta(asset_id=f"a{i}", storage_key=f"asset/{i}", thumbnail_key=f"thumb/{i}",
        mime_type="image/png", width_px=400, height_px=800, aspect_ratio=.5, asset_kind=kind)
        for i, kind in enumerate(kinds)]
    return blocks, assets


@pytest.mark.parametrize("words,kinds", [(20, []), (20, ["photo"]),
    (20, ["chart"] * 4), (800, []), (800, ["chart", "diagram", "photo", "chart"])])
def test_fallback_pair_is_valid_complete_stable_and_protected(words, kinds):
    from bookgen.domain.validator import deterministic_validator

    blocks, assets = inputs(words, kinds)
    grammar = load_settings().grammar
    recent = ["safe_flow_fallback", "two_col_executive", "guided_alternating"]
    pair = builder()(blocks, assets, recent, grammar=grammar)
    assert pair == builder()(blocks, assets, recent, grammar=grammar)
    assert deterministic_validator(pair, blocks, assets, recent, grammar=grammar) == []
    assert [p.option_id for p in pair] == ["option_a", "option_b"]
    families = []
    for page in pair:
        assert page.archetype not in recent
        families.append(getattr(grammar, page.archetype.value).family)
        assert [ref for c in page.components for ref in c.source_block_ids] == [b.block_id for b in blocks]
        assert [c.source_asset_id for c in page.components if c.source_asset_id] == [a.asset_id for a in assets]
        assert all(c.object_fit == "contain" for c in page.components if c.source_asset_id)
    assert len(set(families)) == 2


def test_every_three_archetype_exclusions_leave_two_dense_families():
    from bookgen.domain.validator import deterministic_validator

    grammar = load_settings().grammar
    blocks, assets = inputs(800, ["chart"] * 4)
    for recent in combinations(grammar.archetypes(), 3):
        pair = builder()(blocks, assets, recent, grammar=grammar)
        assert deterministic_validator(pair, blocks, assets, recent, grammar=grammar) == []


def test_empty_input_still_returns_a_valid_pair():
    from bookgen.domain.validator import deterministic_validator

    pair = builder()([], [])
    assert deterministic_validator(pair, [], []) == []


def test_ineligible_configuration_fails_explicitly():
    grammar = load_settings().grammar
    for rule in grammar.archetypes().values():
        rule.max_images = 0
    blocks, assets = inputs(20, ["photo"])
    with pytest.raises(ValueError, match="distinct eligible families"):
        builder()(blocks, assets, grammar=grammar)


@pytest.mark.parametrize("mutation", ["chars", "role", "shared"])
def test_fallback_skips_slots_that_cannot_safely_hold_inputs(mutation):
    from bookgen.domain.validator import deterministic_validator

    grammar = load_settings().grammar
    rule = grammar.safe_flow_fallback
    if mutation == "chars":
        rule.slots[rule.fallback_body_slot].max_chars = 1
    elif mutation == "role":
        rule.slots[rule.fallback_body_slot].role = "media"
    else:
        rule.fallback_media_slot = rule.fallback_body_slot
    blocks, assets = inputs(20, ["chart"])
    pair = builder()(blocks, assets, grammar=grammar)
    assert all(page.archetype != "safe_flow_fallback" for page in pair)
    assert deterministic_validator(pair, blocks, assets, grammar=grammar) == []

@pytest.mark.parametrize('fixture,composition,media', [
    ('chapter-opener', 'opener', 'panoramic'),
    ('financial-comparison', 'comparison', 'paired'),
    ('portrait-testimonial', 'portrait_story', 'portrait_rail'),
])
async def test_offline_visual_fixtures_choose_source_led_treatments(fixture, composition, media):
    import json
    from pathlib import Path
    from bookgen.adapters.llm.mock import MockLLMProvider
    from bookgen.domain.profiler import profile_content
    from bookgen.schemas import BookContext
    root = Path(__file__).resolve().parents[4]
    corpus = json.loads((root / 'apps/api/src/bookgen/examples/manifest.json').read_text(encoding='utf-8'))
    case = next(c for c in corpus['scenarios'] if c['id'] == fixture)
    blocks = profile_content(case['copy'], storage=None).blocks
    assets = [ImageAssetMeta(asset_id=key, storage_key='local', **{
        name: corpus['assets'][key][name] for name in ('mime_type', 'width_px', 'height_px')
    }, aspect_ratio=corpus['assets'][key]['width_px'] / corpus['assets'][key]['height_px'],
        asset_kind=corpus['assets'][key]['kind']) for key in case['assets']]
    provider = MockLLMProvider()
    page = await provider.generate_candidate(context=BookContext.model_validate(case['book_context']),
        blocks=blocks, assets=assets, strategy_tag=provider.settings.llm.strategy_families['option_a'])
    assert page.composition == composition
    assert page.media_placement == media
    assert any(c.component_type == 'heading' for c in page.components)
    if fixture == 'financial-comparison':
        assert any(c.component_type == 'bullet_list' for c in page.components)
    from bookgen.domain.validator import deterministic_validator
    pair = [page, await provider.generate_candidate(context=BookContext.model_validate(case['book_context']),
        blocks=blocks, assets=assets, strategy_tag=provider.settings.llm.strategy_families['option_b'])]
    assert deterministic_validator(pair, blocks, assets) == []
    assert (pair[0].composition, pair[0].emphasis_treatment, pair[0].surface_treatment) != (pair[1].composition, pair[1].emphasis_treatment, pair[1].surface_treatment)


@pytest.mark.parametrize('role,classification,audience,expected', [
    ('quote', None, 'internal', 'pull_quote'),
    ('metric', 'public', 'client_facing', 'stat_callout'),
    ('metric', 'internal', 'client_facing', None),
    ('metric', 'undisclosed', 'client_facing', None),
    ('metric', 'undisclosed', 'internal', 'stat_callout'),
    ('metric', None, 'internal', None),
])
def test_fallback_focal_roles_keep_exact_full_pointers_and_respect_restrictions(role, classification, audience, expected):
    from bookgen.schemas import BookContext, MetricEntry
    from bookgen.domain.validator import deterministic_validator
    text = 'An exact quotation.' if role == 'quote' else 'Revenue grew 42%.'
    blocks = [AtomicTextBlock(block_id='source', kind=role, text=text, word_count=3, char_count=len(text))]
    metrics = [] if classification is None else [MetricEntry(metric_id='metric', source_block_id='source', raw_value='42%', context_snippet=text, classification=classification)]
    pair = builder()(blocks, [], context=BookContext(audience_mode=audience), metrics=metrics)
    assert deterministic_validator(pair, blocks, [], metrics=metrics, audience_mode=audience) == []
    for page in pair:
        body = [c for c in page.components if c.component_type == 'body_prose']
        assert len(body) == 1 and body[0].source_block_ids == ['source']
        focal = [c for c in page.components if c.extracted_excerpt]
        assert [c.component_type for c in focal] == ([expected] if expected else [])
        assert all(c.extracted_excerpt == text and c.source_block_ids == ['source'] for c in focal)


def test_named_treatment_changes_when_source_role_or_asset_facts_change():
    from bookgen.schemas import BookContext
    blocks = [AtomicTextBlock(block_id='quote', kind='quote', text='Exact source quote.', word_count=3, char_count=19)]
    _, assets = inputs(2, ['photo'])
    before = builder()(blocks, assets, context=BookContext())[0]
    assert before.composition == 'portrait_story'
    no_role = builder()([blocks[0].model_copy(update={'kind': 'paragraph'})], assets)[0]
    no_portrait = builder()(blocks, [assets[0].model_copy(update={'aspect_ratio': 2})])[0]
    assert no_role.composition != 'portrait_story'
    assert no_portrait.composition != 'portrait_story'
    no_media = builder()(blocks, [])[0]
    assert no_media.media_placement == 'in_flow'


def test_treatment_budgets_and_focal_slot_capacities_are_respected():
    from bookgen.domain.validator import deterministic_validator
    grammar = load_settings().grammar
    blocks, assets = inputs(100, ['photo'])
    assets[0].aspect_ratio = 3
    assert builder()(blocks, assets, grammar=grammar)[0].composition != 'opener'
    # Insufficient heading and focal capacity keeps exact full prose in body flow.
    for rule in grammar.archetypes().values():
        if 'header' in rule.slots:
            rule.slots['header'].max_chars = 0
        if 'callout' in rule.slots:
            rule.slots['callout'].max_chars = 0
    blocks[0].kind = 'heading'
    blocks[1].kind = 'quote'
    pair = builder()(blocks, [], grammar=grammar)
    assert deterministic_validator(pair, blocks, [], grammar=grammar) == []
    assert all(c.slot_id == 'body' for page in pair for c in page.components)
    assert all(c.extracted_excerpt is None for page in pair for c in page.components)


def contextual_blocks():
    return [AtomicTextBlock(block_id=f'b{i}', kind=kind, text=text,
        word_count=len(text.split()), char_count=len(text)) for i, (kind, text) in enumerate([
            ('heading', 'A supplied title'), ('paragraph', 'Original supporting copy.'),
            ('heading', 'A supplied section'), ('quote', 'Exactly what the customer said.'),
            ('list', '- An original action'), ('caption', 'Original media caption.'),
        ])]


def test_rationales_describe_each_actual_hierarchy_and_media_without_copy():
    blocks = contextual_blocks()
    _, assets = inputs(2, ['chart'])
    pair = builder()(blocks, assets)
    assert pair[0].rationale != pair[1].rationale
    for page in pair:
        assert page.archetype.value.replace('_', ' ') in page.rationale
        assert f'{page.column_count}-column' in page.rationale
        assert 'heading' in page.rationale
        assert 'pull quote' in page.rationale
        assert 'chart' in page.rationale and 'contain' in page.rationale
        assert 'photo' not in page.rationale and 'stat callout' not in page.rationale
        assert not any(block.text in page.rationale for block in blocks)
        assert len(page.rationale) <= 280


def test_semantic_treatments_differ_with_real_sections_and_exact_callouts():
    from bookgen.domain.validator import deterministic_validator
    blocks = contextual_blocks()
    pair = builder()(blocks, [])
    assert deterministic_validator(pair, blocks, []) == []
    assert not any(c.component_type == 'divider_rule' for c in pair[0].components)
    dividers = [c for c in pair[1].components if c.component_type == 'divider_rule']
    assert len(dividers) == 1
    assert all(not c.source_block_ids and not c.source_asset_id for c in dividers)
    second_heading = next(c for c in pair[1].components if c.source_block_ids == ['b2'])
    assert second_heading.slot_id == dividers[0].slot_id == 'body'
    assert pair[1].components.index(second_heading) == pair[1].components.index(dividers[0]) + 1
    for page, surface in zip(pair, ['accent_soft', 'paper']):
        focal = next(c for c in page.components if c.component_type == 'pull_quote')
        assert focal.surface_role == surface
        assert focal.extracted_excerpt == blocks[3].text
        assert [ref for c in page.components if not c.extracted_excerpt for ref in c.source_block_ids] == [b.block_id for b in blocks]
    assert 'divider' not in pair[0].rationale and 'divider' in pair[1].rationale


@pytest.mark.parametrize('role', ['paragraph', 'caption', 'metric'])
def test_unsupported_sources_do_not_invent_titles_dividers_or_focal_elements(role):
    blocks, _ = inputs(2, [])
    blocks = [blocks[0].model_copy(update={'kind': role})]
    for page in builder()(blocks, [], metrics=[]):
        assert not any(c.component_type in ('heading', 'divider_rule', 'pull_quote', 'stat_callout') for c in page.components)
        assert 'heading' not in page.rationale and 'divider' not in page.rationale
        assert 'chart' not in page.rationale and 'photo' not in page.rationale


def test_rationale_uses_placed_facts_when_focal_capacity_is_unavailable():
    grammar = load_settings().grammar
    for rule in grammar.archetypes().values():
        if grammar.art_direction.focal_slot in rule.slots:
            rule.slots[grammar.art_direction.focal_slot].max_chars = 0
    for page in builder()(contextual_blocks(), [], grammar=grammar):
        assert 'pull quote' not in page.rationale
        assert not any(c.extracted_excerpt for c in page.components)


def test_component_profiles_and_rationale_templates_follow_loaded_grammar():
    grammar = load_settings().grammar
    profile = grammar.art_direction.component_treatments['option_b']
    profile.section_dividers = False
    profile.heading_emphasis = True
    profile.focal_surface = 'surface_tint'
    grammar.art_direction.rationale.layout = 'Configured {archetype}: {components}; {media}.'
    page = builder()(contextual_blocks(), [], grammar=grammar)[1]
    assert page.rationale.startswith('Configured two col executive:')
    assert not any(c.component_type == 'divider_rule' for c in page.components)
    assert all(c.emphasis for c in page.components if c.component_type == 'heading')
    assert next(c for c in page.components if c.extracted_excerpt).surface_role == 'surface_tint'


def test_dividers_are_omitted_if_the_body_slot_forbids_decoration():
    from bookgen.domain.validator import deterministic_validator
    grammar = load_settings().grammar
    grammar.slot_role_components['text'].remove(grammar.art_direction.divider_component)
    pair = builder()(contextual_blocks(), [], grammar=grammar)
    assert deterministic_validator(pair, contextual_blocks(), [], grammar=grammar) == []
    assert not any(c.component_type == 'divider_rule' for page in pair for c in page.components)
