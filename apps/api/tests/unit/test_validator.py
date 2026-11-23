"""The domain gate checks pointers and configured grammar without rewriting copy."""

import importlib.util

import pytest

from bookgen.config import load_settings
from bookgen.schemas import (
    AtomicTextBlock, ComponentType, ImageAssetMeta, LayoutArchetype,
    PageLayoutAST, PlacedComponent,
)


def validator():
    assert importlib.util.find_spec("bookgen.domain") is not None, "validator domain must be implemented"
    assert importlib.util.find_spec("bookgen.domain.validator") is not None, "deterministic validator must be implemented"
    from bookgen.domain.validator import deterministic_validator
    return deterministic_validator


def block(block_id="b1", text="Revenue grew 20%, exactly."):
    return AtomicTextBlock(block_id=block_id, kind="paragraph", text=text,
                           word_count=len(text.split()), char_count=len(text))


def asset(asset_id="a1", kind="chart"):
    return ImageAssetMeta(asset_id=asset_id, storage_key=asset_id, thumbnail_key=asset_id,
                          mime_type="image/png", width_px=600, height_px=800,
                          aspect_ratio=.75, asset_kind=kind)


def layout(option="option_a", archetype="two_col_executive", components=None):
    if components is None:
        components = [PlacedComponent(component_id="body", component_type="body_prose",
                                      slot_id="body", source_block_ids=["b1"])]
    return PageLayoutAST(option_id=option, strategy_tag=archetype, archetype=archetype,
                         rationale="Stable layout.", components=components)


def check(first=None, blocks=None, assets=(), recent=(), second=None, grammar=None):
    return validator()(
        [first or layout(), second or layout("option_b", "guided_alternating")],
        [block()] if blocks is None else blocks, assets, recent,
        grammar=grammar or load_settings().grammar,
    )


def assert_issue(issues, code, target="option_a"):
    assert any(i.code == code and i.target_option == target and i.severity == "error"
               for i in issues), issues


def test_valid_pair_is_accepted():
    assert check() == []


@pytest.mark.parametrize("ids, code", [([], "MISSING_BLOCK_ID"), (["b1", "fake"], "UNKNOWN_BLOCK_ID")])
def test_block_completeness(ids, code):
    page = layout()
    page.components[0].source_block_ids = ids
    assert_issue(check(page), code)


@pytest.mark.parametrize("kind", ["pull_quote", "stat_callout"])
@pytest.mark.parametrize("excerpt", [None, "", "grew 21%", "Revenue grew 20% exactly.", "Other text."])
def test_excerpts_must_be_exact_and_from_referenced_source(kind, excerpt):
    page = layout()
    page.components.append(PlacedComponent(component_id="quote", component_type=kind,
        slot_id="callout", source_block_ids=["b1"], extracted_excerpt=excerpt))
    assert_issue(check(page, blocks=[block(), block("b2", "Other text.")]), "HALLUCINATED_EXCERPT")


@pytest.mark.parametrize("kind", ["pull_quote", "stat_callout"])
def test_valid_excerpts_supplement_body_but_cannot_replace_it(kind):
    callout = PlacedComponent(component_id="quote", component_type=kind, slot_id="callout",
                             source_block_ids=["b1"], extracted_excerpt="grew 20%, exactly.")
    page = layout()
    page.components.append(callout)
    assert check(page) == []
    assert_issue(check(layout(components=[callout])), "MISSING_BLOCK_ID")


def test_excerpt_without_source_pointer_is_invalid():
    page = layout()
    page.components.append(PlacedComponent(component_id="quote", component_type="pull_quote",
        slot_id="callout", extracted_excerpt="Revenue"))
    assert_issue(check(page), "HALLUCINATED_EXCERPT")


@pytest.mark.parametrize("source_id,code", [(None, "MISSING_ASSET_ID"), ("invented", "UNKNOWN_ASSET_ID")])
def test_asset_completeness(source_id, code):
    page = layout()
    if source_id:
        page.components.append(PlacedComponent(component_id="media", component_type="image_frame",
            slot_id="media_main", source_asset_id=source_id))
    assert_issue(check(page, assets=[asset()]), code)


@pytest.mark.parametrize("kind", ["chart", "diagram"])
@pytest.mark.parametrize("violation", ["cover", "overlay"])
def test_protected_media_cannot_crop_or_share_text_overlay(kind, violation):
    page = layout(archetype="full_bleed_hero")
    page.components.append(PlacedComponent(component_id="media", component_type="image_frame",
        slot_id="media_main", source_asset_id="a1", object_fit="cover" if violation == "cover" else "contain"))
    if violation == "overlay":
        page.components[0].slot_id = "media_main"
    assert_issue(check(page, assets=[asset(kind=kind)]), "CHART_CROP_FORBIDDEN")
    assert page.components[-1].object_fit == ("cover" if violation == "cover" else "contain")


@pytest.mark.parametrize("kind,fit", [("chart", "contain"), ("diagram", "contain"), ("photo", "cover")])
def test_contained_media_and_croppable_photos(kind, fit):
    pages = [layout(), layout("option_b", "guided_alternating")]
    for page in pages:
        page.components.append(PlacedComponent(component_id="media", component_type="image_frame",
            slot_id="media_main", source_asset_id="a1", object_fit=fit))
    assert validator()(pages, [block()], [asset(kind=kind)]) == []


@pytest.mark.parametrize("field,value,code", [("slot_id", "raw_grid", "UNKNOWN_SLOT"),
    ("object_fit", "stretch", "INVALID_OBJECT_FIT")])
def test_undefined_component_choices(field, value, code):
    page = layout()
    setattr(page.components[0], field, value)
    assert_issue(check(page), code)


def test_undefined_density_is_rejected():
    page = layout()
    page.density_scale = "tiny"
    assert_issue(check(page), "INVALID_DENSITY_SCALE")


def test_slot_character_budget_counts_all_components():
    page = layout(archetype="full_bleed_hero")
    page.components[0].slot_id = "header"
    assert_issue(check(page, blocks=[block(text="x" * 400)]), "SLOT_OVERFLOW_BUDGET")


def test_word_budget_uses_source_text_instead_of_untrusted_metadata():
    dense = block(text="word " * 400)
    dense.word_count = 1
    assert_issue(check(layout(archetype="full_bleed_hero"), [dense]), "ARCHETYPE_OVERFLOW_BUDGET")


@pytest.mark.parametrize("second", ["two_col_executive", "dashboard_split"])
def test_pair_archetype_and_family_must_differ(second):
    assert_issue(check(second=layout("option_b", second)), "DUPLICATE_STRATEGY", "option_b")


def test_exclusions_are_archetype_values_not_families():
    assert_issue(check(recent=[LayoutArchetype.TWO_COL_EXECUTIVE]), "RECENT_ARCHETYPE_REPEAT")
    assert check(recent=[LayoutArchetype.DASHBOARD_SPLIT]) == []


@pytest.mark.parametrize("mutation", ["extra", "surface", "component_surface", "archetype"])
def test_schema_errors_are_structured(mutation):
    raw = layout().model_dump(mode="json")
    if mutation == "extra":
        raw["html"] = "<div>rewritten</div>"
    elif mutation == "component_surface":
        raw["components"][0]["surface_role"] = "#fff"
    else:
        raw["surface_role" if mutation == "surface" else "archetype"] = "invented"
    assert_issue(check(raw), "SCHEMA_VALIDATION_ERROR")


def test_models_are_reparsed_after_unsafe_mutation():
    page = layout()
    page.surface_role = "#fff"
    assert_issue(check(page), "SCHEMA_VALIDATION_ERROR")


def test_pair_size_and_option_identity_are_validated():
    assert_issue(validator()([], [], []), "INVALID_OPTION_PAIR", "pair")
    assert_issue(check(second=layout()), "INVALID_OPTION_PAIR", "pair")
    first = layout("arbitrary")
    assert_issue(check(first), "INVALID_OPTION_PAIR", "pair")


def test_slot_role_and_image_budget_are_enforced():
    page = layout(archetype="full_bleed_hero")
    page.components[0].slot_id = "footer"
    for i in range(2):
        page.components.append(PlacedComponent(component_id=str(i), component_type="image_frame",
            slot_id="media_main", source_asset_id=f"a{i}"))
    issues = check(page, assets=[asset("a0", "photo"), asset("a1", "photo")])
    assert_issue(issues, "ARCHETYPE_IMAGE_BUDGET")
    page.components[-1].slot_id = "header"
    assert_issue(check(page, assets=[asset("a0"), asset("a1")]), "SLOT_ROLE_MISMATCH")


def test_callout_excerpt_counts_toward_slot_budget():
    dense = block(text="x" * 500)
    page = layout(archetype="full_bleed_hero")
    page.components.append(PlacedComponent(component_id="quote", component_type="pull_quote",
        slot_id="callout", source_block_ids=["b1"], extracted_excerpt=dense.text))
    assert_issue(check(page, [dense]), "SLOT_OVERFLOW_BUDGET")


def test_limits_are_loaded_from_grammar():
    grammar = load_settings().grammar
    grammar.two_col_executive.max_words = 1
    assert_issue(check(grammar=grammar), "ARCHETYPE_OVERFLOW_BUDGET")


@pytest.mark.parametrize("raw", [None, 42, "raw text", ["bad", "shape"]])
def test_non_object_options_return_schema_issues(raw):
    issues = validator()([raw, layout("option_b", "guided_alternating")], [block()], [])
    assert_issue(issues, "SCHEMA_VALIDATION_ERROR", "unknown")


def test_schema_does_not_coerce_column_count():
    raw = layout().model_dump(mode="json")
    raw["column_count"] = "2"
    assert_issue(check(raw), "SCHEMA_VALIDATION_ERROR")


def test_asset_pointer_on_text_does_not_satisfy_asset_completeness():
    page = layout()
    page.components[0].source_asset_id = "a1"
    issues = check(page, assets=[asset()])
    assert_issue(issues, "ASSET_COMPONENT_MISMATCH")
    assert_issue(issues, "MISSING_ASSET_ID")


def test_photo_overlay_must_be_permitted_by_slot_grammar():
    page = layout()
    page.components.append(PlacedComponent(component_id="media", component_type="image_frame",
        slot_id="body", source_asset_id="a1"))
    assert_issue(check(page, assets=[asset(kind="photo")]), "SLOT_OVERLAY_FORBIDDEN")


@pytest.mark.parametrize("mutation", ["missing_fallback_slot", "fixed_unbounded", "density", "fit", "role"])
def test_invalid_grammar_policies_fail_at_boot(mutation):
    from pydantic import ValidationError
    from bookgen.config.grammar import GrammarConfig

    raw = load_settings().grammar.model_dump(mode="json")
    if mutation == "missing_fallback_slot":
        del raw["two_col_executive"]["slots"]["body"]
    elif mutation == "fixed_unbounded":
        raw["two_col_executive"]["reflow"] = False
    elif mutation == "density":
        raw["density_scales"] = ["normal"]
    elif mutation == "fit":
        raw["object_fits"] = ["cover"]
    else:
        del raw["slot_role_components"]["text"]
    with pytest.raises(ValidationError):
        GrammarConfig.model_validate(raw)


def test_grammar_binds_eight_shared_renderer_shapes_and_semantic_slots():
    rules = load_settings().grammar.archetypes()
    assert len({rule.renderer_shape for rule in rules.values()}) == 8
    for left, right in [("full_bleed_hero", "section_divider"),
                        ("editorial_asymmetric", "guided_alternating"),
                        ("two_col_executive", "safe_flow_fallback")]:
        assert rules[left].renderer_shape == rules[right].renderer_shape
    assert set().union(*(rule.slots for rule in rules.values())) == {
        "header", "body", "col_left", "col_right", "media_main", "media_secondary", "callout", "footer"}
