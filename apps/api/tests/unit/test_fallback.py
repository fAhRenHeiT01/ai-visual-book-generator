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
