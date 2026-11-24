"""Deterministic profiling preserves source text and bounds provider images."""

from importlib import import_module
from io import BytesIO
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "apps/api/src"))


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    def put(self, key, data):
        self.objects[key] = data
        return key

    def get(self, key):
        return self.objects[key]


def profiler():
    assert (ROOT / "apps/api/src/bookgen/domain/profiler.py").is_file(), "deterministic profiler must be implemented"
    return import_module("bookgen.domain.profiler")


def image_bytes(size=(120, 80), dpi=None, format="PNG"):
    output = BytesIO()
    kwargs = {} if dpi is None else {"dpi": (dpi, dpi)}
    Image.new("RGB", size, "white").save(output, format=format, **kwargs)
    return output.getvalue()


def settings():
    from bookgen.config import load_settings

    config = load_settings(config_dir=ROOT / "config").profiling
    assert config is not None
    return config


def test_source_blocks_are_stable_ordered_and_exact():
    module = profiler()
    source = "# Café 世界\r\nRepeated café — repeated café.\r\nSecond paragraph line.\r\n\r\n- naïve item\r\n- naïve item\r\n\r\n> Exact quote.\r\n\r\n## Another heading\r\n  Trailing spaces stay.  "
    expected = [
        ("heading", "# Café 世界"),
        ("paragraph", "Repeated café — repeated café.\r\nSecond paragraph line."),
        ("list", "- naïve item\r\n- naïve item"),
        ("quote", "> Exact quote."),
        ("heading", "## Another heading"),
        ("paragraph", "  Trailing spaces stay.  "),
    ]
    first = module.profile_content(source, storage=MemoryStorage())
    second = module.profile_content(source, storage=MemoryStorage())
    assert first == second
    assert [(block.kind, block.text) for block in first.blocks] == expected
    assert [block.block_id for block in first.blocks] == [f"blk_{index:02d}" for index in range(1, 7)]
    for block in first.blocks:
        assert block.text in source
        assert block.char_count == len(block.text)
        assert block.word_count == len(block.text.split())
    assert first.assets == first.issues == []


@pytest.mark.parametrize('text,title,expected', [
    ('# Source heading\nBody copy stays.', 'Explicit title', 'Explicit title'),
    ('# Source heading\nBody copy stays.', None, 'Source heading'),
    (r'# Source heading\nBody copy stays.', None, 'Source heading'),
    ('Ordinary first sentence. More source copy.', None, 'Ordinary first sentence.'),
    ('Plain\twords\ncontinue', '  ', 'Plain words continue'),
    ('\n\t', None, ''),
])
def test_page_title_metadata_is_separate_from_normalized_source(text, title, expected):
    module = profiler()
    assert module.infer_page_title(text, title=title, settings=settings()) == expected
    assert module.normalize_page_input(text) == module.normalize_page_input(module.normalize_page_input(text))


def test_title_inference_obeys_yaml_word_budget_and_rules():
    module = profiler()
    config = settings().model_copy(deep=True)
    config.title.max_words = 3
    config.title.heading = '^TITLE: (.+)$'
    config.title.sentence_boundary = '; '
    assert module.infer_page_title('TITLE: Exact source heading\nBody.', settings=config) == 'Exact source heading'
    assert module.infer_page_title('One  two three four five', settings=config) == 'One  two three'
    assert module.infer_page_title('One two; Three four.', settings=config) == 'One two'
    assert module.infer_page_title('Body.', title='Long explicit title keeps all its words', settings=config) == 'Long explicit title keeps all its words'


@pytest.mark.parametrize("source", ["", "\n\n", " \r\n\t\r\n"])
def test_empty_text_and_no_images(source):
    result = profiler().profile_content(source, storage=MemoryStorage())
    assert result.blocks == result.assets == result.issues == []


def test_adjacent_headings_and_blank_lines_do_not_merge():
    result = profiler().profile_content("# One\n# Two\n\n\nBody\n\n1. First\n2. Second\n", storage=MemoryStorage())
    assert [block.text for block in result.blocks] == ["# One", "# Two", "Body", "1. First\n2. Second"]


def test_single_image_metadata_and_dpi():
    module = profiler()
    original = image_bytes((1200, 800), dpi=300)
    storage = MemoryStorage()
    result = module.profile_content("", [module.ImageInput(original, filename="photo.png")], storage=storage)
    asset, = result.assets
    assert (asset.asset_id, asset.width_px, asset.height_px) == ("img_01", 1200, 800)
    assert asset.aspect_ratio == 1.5
    assert asset.estimated_dpi == 300
    assert asset.mime_type == "image/png"
    assert asset.asset_kind.value == "photo"
    assert result.issues == []
    assert storage.get(asset.storage_key) == original
    assert asset.thumbnail_key != asset.storage_key
    with Image.open(BytesIO(storage.get(asset.thumbnail_key))) as thumbnail:
        assert thumbnail.size == (768, 512)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("offset,object_count", [(-1, 1), (0, 1), (1, 2)])
@pytest.mark.parametrize("custom_edge", [None, 128])
def test_preview_derivative_is_stored_only_above_configured_edge(portrait, offset, object_count, custom_edge):
    module = profiler()
    config = settings()
    if custom_edge is not None:
        config = config.model_copy(update={"thumbnail_max_px": custom_edge})
    edge = config.thumbnail_max_px + offset
    size = (edge // 2, edge) if portrait else (edge, edge // 2)
    original = image_bytes(size)
    storage = MemoryStorage()
    result = module.profile_content("", [module.ImageInput(original)], storage=storage, settings=config)
    asset, = result.assets
    assert len(storage.objects) == object_count
    assert storage.get(asset.storage_key) == original
    if object_count == 1:
        assert asset.thumbnail_key is None
    else:
        with Image.open(BytesIO(storage.get(asset.thumbnail_key))) as preview:
            assert max(preview.size) == config.thumbnail_max_px
            scale = config.thumbnail_max_px / max(size)
            assert preview.width == pytest.approx(size[0] * scale, abs=1)
            assert preview.height == pytest.approx(size[1] * scale, abs=1)


def test_multiple_images_have_stable_ids_kinds_and_warnings():
    module = profiler()
    from bookgen.schemas import AssetKind

    inputs = [
        module.ImageInput(image_bytes((800, 1200), 72), filename="revenue-chart.png"),
        module.ImageInput(image_bytes((400, 400)), filename="workflow-diagram.png"),
        module.ImageInput(image_bytes((400, 400)), filename="brand-logo.png"),
        module.ImageInput(image_bytes((400, 400)), filename="chart.png", kind=AssetKind.PHOTO),
    ]
    first = module.profile_content("", inputs, storage=MemoryStorage())
    second = module.profile_content("", inputs, storage=MemoryStorage())
    assert first == second
    assert [asset.asset_id for asset in first.assets] == ["img_01", "img_02", "img_03", "img_04"]
    assert [asset.asset_kind for asset in first.assets] == [AssetKind.CHART, AssetKind.DIAGRAM, AssetKind.LOGO, AssetKind.PHOTO]
    assert first.assets[0].aspect_ratio == pytest.approx(2 / 3)
    assert first.assets[1].estimated_dpi is None
    assert [(issue.code, issue.severity, issue.target_option) for issue in first.issues] == [("LOW_DPI", "warning", "img_01")]


@pytest.mark.parametrize("size", [(2000, 100), (100, 2000)])
def test_valid_extreme_ratios_warn_without_rejecting(size):
    module = profiler()
    result = module.profile_content("", [module.ImageInput(image_bytes(size))], storage=MemoryStorage())
    assert len(result.assets) == 1
    assert [issue.code for issue in result.issues] == ["ASPECT_RATIO_OUT_OF_RANGE"]


@pytest.mark.parametrize("size,expected", [((1600, 800), (768, 384)), ((800, 1600), (384, 768))])
def test_thumbnails_preserve_ratio_and_never_upscale(size, expected):
    module = profiler()
    storage = MemoryStorage()
    result = module.profile_content("", [module.ImageInput(image_bytes(size))], storage=storage)
    asset, = result.assets
    with Image.open(BytesIO(storage.get(asset.thumbnail_key))) as thumbnail:
        assert thumbnail.size == expected
    with Image.open(BytesIO(storage.get(asset.storage_key))) as original:
        assert original.size == size


@pytest.mark.parametrize("data", [b"not an image", image_bytes()[:40]])
def test_corrupt_images_are_rejected_without_storage_writes(data):
    module = profiler()
    storage = MemoryStorage()
    with pytest.raises(ValueError, match="[Cc]orrupt|[Ii]nvalid"):
        module.profile_content("", [module.ImageInput(data)], storage=storage)
    assert storage.objects == {}


def test_unsupported_mime_is_rejected_and_detected_from_bytes():
    module = profiler()
    with pytest.raises(ValueError, match="MIME"):
        module.profile_content("", [module.ImageInput(image_bytes(format="GIF"), filename="pretend.png")], storage=MemoryStorage())
    result = module.profile_content("", [module.ImageInput(image_bytes(format="JPEG"), filename="pretend.gif")], storage=MemoryStorage())
    assert result.assets[0].mime_type == "image/jpeg"


def test_cmyk_jpeg_has_decodable_png_thumbnail_without_changing_original():
    module = profiler()
    output = BytesIO()
    Image.new("CMYK", (1000, 600)).save(output, format="JPEG")
    original_bytes = output.getvalue()
    storage = MemoryStorage()
    result = module.profile_content("", [module.ImageInput(original_bytes)], storage=storage)
    asset, = result.assets
    assert storage.get(asset.storage_key) == original_bytes
    with Image.open(BytesIO(storage.get(asset.thumbnail_key))) as thumbnail:
        assert thumbnail.mode == "RGB"
        assert max(thumbnail.size) <= 768


def test_transparent_webp_preserves_alpha_in_thumbnail():
    module = profiler()
    output = BytesIO()
    Image.new("RGBA", (1000, 1000), (0, 0, 0, 0)).save(output, format="WEBP")
    storage = MemoryStorage()
    result = module.profile_content("", [module.ImageInput(output.getvalue(), alt_caption="a workflow diagram")], storage=storage)
    asset, = result.assets
    assert asset.mime_type == "image/webp"
    assert asset.asset_kind.value == "diagram"
    assert asset.alt_caption == "a workflow diagram"
    with Image.open(BytesIO(storage.get(asset.thumbnail_key))) as thumbnail:
        assert thumbnail.getpixel((0, 0))[3] == 0


def test_unconfigured_or_incomplete_profiling_fails_explicitly(monkeypatch):
    module = profiler()
    from bookgen.config.profiling import ProfilingConfig

    with pytest.raises(ValueError, match="incomplete"):
        module.profile_content("", storage=MemoryStorage(), settings=ProfilingConfig())
    monkeypatch.setattr(module, "load_settings", lambda: SimpleNamespace(profiling=None))
    with pytest.raises(ValueError, match="not configured"):
        module.profile_content("", storage=MemoryStorage())


def test_custom_configuration_controls_parsing_classification_and_preflight():
    module = profiler()
    config = settings().model_dump()
    config.update(thumbnail_max_px=100, min_dpi=400, aspect_ratio_min=0.8, aspect_ratio_max=1.2)
    config["block_patterns"]["heading"] = "^TITLE:"
    config["chart_heuristics"] = {"chart": ["(?i)revenue"]}
    from bookgen.config.profiling import ProfilingConfig

    storage = MemoryStorage()
    result = module.profile_content("TITLE: Café\nBody", [module.ImageInput(image_bytes((1200, 800), 300), filename="REVENUE.png")], storage=storage, settings=ProfilingConfig.model_validate(config))
    assert result.blocks[0].kind == "heading"
    assert result.assets[0].asset_kind.value == "chart"
    assert {issue.code for issue in result.issues} == {"LOW_DPI", "ASPECT_RATIO_OUT_OF_RANGE"}
    with Image.open(BytesIO(storage.get(result.assets[0].thumbnail_key))) as image:
        assert max(image.size) == 100


@pytest.mark.parametrize("field,value", [
    ("thumbnail_max_px", 769), ("thumbnail_max_px", 0), ("min_dpi", 0),
    ("aspect_ratio_min", 0), ("aspect_ratio_max", 0.01),
    ("allowed_mime_types", []), ("block_patterns", {"heading": "["}),
    ("chart_heuristics", {"chart": ["["]}), ("unknown", True),
])
def test_invalid_profiling_settings_fail_at_boot(field, value):
    profiler()
    from bookgen.config.profiling import ProfilingConfig

    payload = settings().model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        ProfilingConfig.model_validate(payload)


def test_nested_environment_override(monkeypatch):
    profiler()
    monkeypatch.setenv("BOOKGEN__PROFILING__THUMBNAIL_MAX_PX", "128")
    assert settings().thumbnail_max_px == 128


def test_distinct_uploads_do_not_overwrite_previous_originals():
    module = profiler()
    storage = MemoryStorage()
    first = module.profile_content("", [module.ImageInput(image_bytes((300, 200)))], storage=storage)
    second = module.profile_content("", [module.ImageInput(image_bytes((200, 300)))], storage=storage)
    assert first.assets[0].storage_key != second.assets[0].storage_key
    with Image.open(BytesIO(storage.get(first.assets[0].storage_key))) as image:
        assert image.size == (300, 200)
