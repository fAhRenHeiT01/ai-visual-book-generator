"""The published contract preserves pointers and rejects unrecognized layout data."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "apps/api/src"))


def schemas():
    assert importlib.util.find_spec("bookgen.schemas") is not None, "canonical schemas must be implemented"
    from bookgen import schemas as contracts

    return contracts


def layout(**overrides):
    return {
        "option_id": "option_a",
        "strategy_tag": "editorial_visual",
        "archetype": "editorial_asymmetric",
        "rationale": "Pair the source prose with its chart.",
        "components": [
            {"component_id": "cmp_01", "component_type": "body_prose", "slot_id": "col_left", "source_block_ids": ["blk_01"]},
            {"component_id": "cmp_02", "component_type": "image_frame", "slot_id": "media_main", "source_asset_id": "img_01"},
        ],
        **overrides,
    }


@pytest.mark.parametrize("field,value", [("html", "<p>mutated</p>"), ("css", "color:red"), ("unknown", True)])
@pytest.mark.parametrize("nested", [False, True])
def test_rejects_unknown_root_and_nested_fields(field, value, nested):
    payload = layout()
    target = payload["components"][0] if nested else payload
    target[field] = value
    with pytest.raises(ValidationError) as error:
        schemas().PageLayoutAST.model_validate(payload)
    assert error.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("column_count", [0, 4])
def test_rejects_invalid_columns(column_count):
    with pytest.raises(ValidationError):
        schemas().PageLayoutAST.model_validate(layout(column_count=column_count))


@pytest.mark.parametrize("column_count", [1, 3])
def test_accepts_boundary_columns(column_count):
    assert schemas().PageLayoutAST.model_validate(layout(column_count=column_count)).column_count == column_count


def test_rationale_length_is_bounded():
    model = schemas().PageLayoutAST
    assert len(model.model_validate(layout(rationale="a" * 280)).rationale) == 280
    with pytest.raises(ValidationError):
        model.model_validate(layout(rationale="a" * 281))


def test_layout_json_schema_is_strict_and_serializable():
    document = json.loads(json.dumps(schemas().PageLayoutAST.model_json_schema()))
    assert document["additionalProperties"] is False
    assert document["$defs"]["PlacedComponent"]["additionalProperties"] is False
    assert len(document["$defs"]["LayoutArchetype"]["enum"]) == 11
    assert document["properties"]["column_count"]["minimum"] == 1
    assert document["properties"]["column_count"]["maximum"] == 3


def test_generation_result_round_trip_preserves_source_ids_and_text():
    model = schemas().PageGenerationResult
    original = model.model_validate({
        "page_id": "page_01", "page_number": 1,
        "input_blocks": [{"block_id": "blk_01", "kind": "paragraph", "text": "Original copy stays verbatim.", "word_count": 4, "char_count": 29}],
        "input_assets": [{"asset_id": "img_01", "storage_key": "original/chart.png", "thumbnail_key": "thumb/chart.png", "mime_type": "image/png", "width_px": 1200, "height_px": 600, "aspect_ratio": 2, "asset_kind": "chart"}],
        "metrics_ledger": [{"metric_id": "met_01", "source_block_id": "blk_01", "raw_value": "4", "context_snippet": "Original copy", "classification": "public"}],
        "option_a": layout(), "option_b": layout(option_id="option_b"),
    })
    restored = model.model_validate_json(original.model_dump_json())
    assert restored == original
    assert restored.input_blocks[0].text == "Original copy stays verbatim."
    assert restored.option_a.components[0].source_block_ids == ["blk_01"]
    assert restored.option_b.components[1].source_asset_id == "img_01"
    assert restored.metrics_ledger[0].source_block_id == "blk_01"


def test_openapi_publishes_every_canonical_model_and_enum():
    contracts = schemas()
    from bookgen.main import create_app

    document = create_app().openapi()
    assert document["info"]["version"] == "1.0.0"
    names = [
        "StrictModel", "DesignTokens", "MasterChromeConfig", "BookContext", "AtomicTextBlock",
        "ImageAssetMeta", "MetricEntry", "PlacedComponent", "PageLayoutAST", "ValidationIssue",
        "PageGenerationResult", "AudienceMode", "PageSize", "AssetKind", "MetricClassification",
        "LayoutArchetype", "SurfaceRole", "ComponentType",
    ]
    published = document["components"]["schemas"]
    for name in names:
        assert name in published
        model = getattr(contracts, name)
        if hasattr(model, "model_fields"):
            assert published[name]["additionalProperties"] is False
            assert set(published[name]["properties"]) == set(model.model_fields)
        else:
            assert published[name]["enum"] == [item.value for item in model]
    assert len(published["LayoutArchetype"]["enum"]) == 11


def test_create_app_validates_settings_before_serving(monkeypatch):
    schemas()
    from bookgen.main import create_app

    monkeypatch.setenv("BOOKGEN__LLM__MAX_REPAIR_RETRIES", "-1")
    with pytest.raises(ValidationError):
        create_app()
