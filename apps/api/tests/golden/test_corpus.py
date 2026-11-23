"""Offline contract for the marketing corpus consumed by the later gallery/evals."""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys

from PIL import Image, ImageStat
import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "apps/api/src"))
EXAMPLES = ROOT / "apps/api/src/bookgen/examples"

from bookgen.config import load_settings
from bookgen.domain.compliance import compliance_metrics_scan
from bookgen.domain.profiler import ImageInput, profile_content
from bookgen.domain.validator import deterministic_validator
from bookgen.schemas import (
    AssetKind, AudienceMode, BookContext, ComponentType, LayoutArchetype,
    PageLayoutAST, PageSize,
)


@pytest.fixture(scope="module")
def corpus():
    path = EXAMPLES / "manifest.json"
    assert path.is_file(), "Missing offline corpus manifest: examples/manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    def put(self, key, data):
        self.objects[key] = data
        return key

    def get(self, key):
        return self.objects[key]


def local_path(relative):
    path = (EXAMPLES / relative).resolve()
    assert path.is_relative_to(EXAMPLES.resolve()), f"Asset escapes corpus: {relative}"
    assert path.is_file(), f"Missing local asset: {relative}"
    return path


def profile(case, catalog):
    storage = MemoryStorage()
    inputs = [ImageInput(
        local_path(catalog[key]["path"]).read_bytes(),
        filename=Path(catalog[key]["path"]).name,
        kind=AssetKind(catalog[key]["kind"]),
        alt_caption=catalog[key]["alt_caption"],
    ) for key in case["assets"]]
    result = profile_content(case["copy"], inputs, storage=storage)
    return result, storage


def test_corpus_integrity(corpus):
    assert corpus["schema_version"] == 1
    cases = corpus["scenarios"]
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids)) == 25, "Expected exactly 25 unique scenario IDs"
    catalog = corpus["assets"]
    assert set(catalog) == {key for case in cases for key in case["assets"]}
    assert {path.name for path in (EXAMPLES / "assets").iterdir()} == {
        Path(asset["path"]).name for asset in catalog.values()
    }, "Every checked-in image must be catalogued with provenance"
    for key, asset in catalog.items():
        path = local_path(asset["path"])
        assert path.parent == EXAMPLES / "assets", key
        assert sha256(path.read_bytes()).hexdigest() == asset["sha256"], key
        with Image.open(path) as image:
            image.load()
            assert list(image.size) == [asset["width_px"], asset["height_px"]], key
            assert Image.MIME[image.format] == asset["mime_type"], key
            assert max(ImageStat.Stat(image.convert("RGB")).stddev) > 1, key
        assert asset["kind"] in {value.value for value in AssetKind}, key
        assert asset["alt_caption"].strip(), key
        origin = asset["provenance"]
        assert all(origin[field].strip() for field in (
            "creator", "origin", "license", "reuse_rights", "modifications",
        )), key
        assert origin["license"] in {"CC0-1.0", "Public Domain"}, key
    assert {asset["mime_type"] for asset in catalog.values()} == {
        "image/png", "image/jpeg", "image/webp",
    }


@pytest.mark.parametrize("index", range(25), ids=lambda index: f"scenario-{index + 1:02d}")
def test_scenario_is_consumable_and_preserves_sources(corpus, index):
    case = corpus["scenarios"][index]
    assert case["id"] and case["title"].strip() and case["copy"].strip()
    context = BookContext.model_validate(case["book_context"])
    assert context.title and context.objective and context.tone_keywords
    assert case["coverage_tags"] and len(set(case["coverage_tags"])) == len(case["coverage_tags"])
    result, storage = profile(case, corpus["assets"])
    assert result.blocks, case["id"]
    for block in result.blocks:
        assert block.text in case["copy"], case["id"]
    config = load_settings(config_dir=ROOT / "config")
    for asset in result.assets:
        if asset.thumbnail_key is None:
            assert max(asset.width_px, asset.height_px) <= config.profiling.thumbnail_max_px
            preview_bytes = storage.get(asset.storage_key)
        else:
            preview_bytes = storage.get(asset.thumbnail_key)
        with Image.open(BytesIO(preview_bytes)) as image:
            assert image.width <= asset.width_px and image.height <= asset.height_px
            if asset.thumbnail_key is not None:
                assert max(image.size) <= config.profiling.thumbnail_max_px
    assert sorted(issue.code for issue in result.issues) == sorted(case["expected"]["preflight_issue_codes"])
    layouts = [PageLayoutAST.model_validate(raw) for raw in case["reference_options"]]
    assert [layout.option_id for layout in layouts] == ["option_a", "option_b"]
    issues = deterministic_validator(layouts, result.blocks, result.assets,
        grammar=config.grammar, compliance=config.compliance, audience_mode=context.audience_mode)
    assert issues == [], f"{case['id']}: {issues}"
    ledger = compliance_metrics_scan(result.blocks, config=config.compliance)
    assert sorted({metric.classification.value for metric in ledger}) == sorted(case["expected"]["metric_classifications"])
    restricted = config.compliance.audience_policies[context.audience_mode].approval_required
    blocked = any(metric.classification in restricted for metric in ledger)
    assert blocked == case["expected"]["export_blocked"], case["id"]
    assert case["expected"]["design_notes"].strip()
    assert case["expected"]["compliance_notes"].strip()
    for layout in layouts:
        assert {component.component_type.value for component in layout.components} <= set(case["expected"]["component_types"])
        for component in layout.components:
            if component.extracted_excerpt:
                assert any(component.extracted_excerpt in block.text for block in result.blocks
                    if block.block_id in component.source_block_ids)
    failure = case["expected"].get("failure_probe")
    if failure:
        invalid = deepcopy(case["reference_options"])
        if failure["mutation"] == "cover_protected":
            media = next(component for component in invalid[0]["components"]
                if component.get("source_asset_id") in {
                    asset.asset_id for asset in result.assets
                    if asset.asset_kind in config.grammar.protected_asset_kinds})
            media["object_fit"] = "cover"
        elif failure["mutation"] == "drop_source":
            invalid[0]["components"] = [component for component in invalid[0]["components"]
                if result.blocks[-1].block_id not in component.get("source_block_ids", [])]
        elif failure["mutation"] == "invent_excerpt":
            callout = next(component for component in invalid[0]["components"] if component.get("extracted_excerpt"))
            callout["extracted_excerpt"] = failure["invalid_excerpt"]
        else:
            pytest.fail(f"Unknown corpus failure probe: {failure}")
        codes = {issue.code for issue in deterministic_validator(invalid, result.blocks, result.assets,
            grammar=config.grammar, compliance=config.compliance, audience_mode=context.audience_mode)}
        assert failure["issue_code"] in codes, case["id"]


def test_coverage_matrix_is_derived_from_real_cases(corpus):
    cases = corpus["scenarios"]
    dimensions = {
        "archetypes": ({value.value for value in LayoutArchetype}, lambda c: {option["archetype"] for option in c["reference_options"]}),
        "component_types": ({value.value for value in ComponentType}, lambda c: {component["component_type"] for option in c["reference_options"] for component in option["components"]}),
        "asset_kinds": ({value.value for value in AssetKind}, lambda c: {corpus["assets"][key]["kind"] for key in c["assets"]}),
        "audiences": ({value.value for value in AudienceMode}, lambda c: {c["book_context"]["audience_mode"]}),
        "paper_sizes": ({value.value for value in PageSize}, lambda c: {c["book_context"]["page_size"]}),
        "outcomes": ({"normal", "repair", "fallback", "export-blocked"}, lambda c: {c["expected"]["outcome"]}),
    }
    for dimension, (supported, extract) in dimensions.items():
        actual = {value: [case["id"] for case in cases if value in extract(case)] for value in supported}
        assert all(actual.values()), f"Uncovered {dimension}: {actual}"
        assert corpus["coverage_matrix"][dimension] == actual
    for case in cases:
        expected = case["expected"]
        assert expected["outcome"] in dimensions["outcomes"][0]
        assert bool(expected.get("failure_probe")) == (expected["outcome"] in {"repair", "fallback"})
        assert expected["export_blocked"] == (expected["outcome"] == "export-blocked")


def test_required_editorial_and_asset_edges_are_substantive(corpus):
    by_id = {case["id"]: case for case in corpus["scenarios"]}
    dense = by_id["executive-500"]
    assert len(dense["copy"].split()) == 500 and dense["assets"] == []
    visual = corpus["visual_review_fixtures"]
    assert visual == {"opener": "chapter-opener", "two_chart_comparison": "financial-comparison", "portrait_testimonial": "portrait-testimonial"}
    opener = by_id[visual["opener"]]
    assert opener["copy"].count(".") == 1 and len(opener["assets"]) == 1
    photo = corpus["assets"][opener["assets"][0]]
    assert photo["kind"] == "photo" and photo["width_px"] / photo["height_px"] > 2
    financial = by_id[visual["two_chart_comparison"]]
    assert [corpus["assets"][key]["kind"] for key in financial["assets"]] == ["chart", "chart"]
    assert "- " in financial["copy"]
    portrait = by_id[visual["portrait_testimonial"]]
    assert {corpus["assets"][key]["kind"] for key in portrait["assets"]} == {"photo", "diagram"}
    assert any(corpus["assets"][key]["height_px"] > corpus["assets"][key]["width_px"]
        for key in portrait["assets"] if corpus["assets"][key]["kind"] == "photo")
    assert any(c["component_type"] == "pull_quote" for c in portrait["reference_options"][0]["components"])
    restricted = by_id["restricted-client-metrics"]
    assert restricted["book_context"]["audience_mode"] == "client_facing"
    assert all(tag in restricted["copy"] for tag in ("[INTERNAL]", "[UNDISCLOSED]"))
    assert restricted["expected"]["export_blocked"]
    required_tags = {"low-resolution", "boundary-767", "boundary-768", "boundary-769", "extreme-wide", "extreme-tall", "mixed-formats"}
    tags = {tag for case in by_id.values() for tag in case["coverage_tags"]}
    assert required_tags <= tags
    low = by_id["low-resolution-review"]
    assert any(max(corpus["assets"][key]["width_px"], corpus["assets"][key]["height_px"]) < 150
        for key in low["assets"])
    mixed = by_id["mixed-format-kit"]
    assert {corpus["assets"][key]["mime_type"] for key in mixed["assets"]} == {
        "image/png", "image/jpeg", "image/webp",
    }
    for size in (767, 768, 769):
        case = next(case for case in by_id.values() if f"boundary-{size}" in case["coverage_tags"])
        assert any(max(corpus["assets"][key]["width_px"], corpus["assets"][key]["height_px"]) == size for key in case["assets"])
    for tag, wide in (("extreme-wide", True), ("extreme-tall", False)):
        case = next(case for case in by_id.values() if tag in case["coverage_tags"])
        assert any((corpus["assets"][key]["width_px"] / corpus["assets"][key]["height_px"] > 5 if wide
            else corpus["assets"][key]["height_px"] / corpus["assets"][key]["width_px"] > 5) for key in case["assets"])
