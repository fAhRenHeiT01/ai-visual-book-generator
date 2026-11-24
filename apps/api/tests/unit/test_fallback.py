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
