"""Provider requests expose only bounded context and validated thumbnails."""

import base64
import importlib.util
from io import BytesIO
from pathlib import Path
import sys

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "apps/api/src"))


def implementation():
    assert importlib.util.find_spec("bookgen.adapters.llm") is not None, "Gemini adapter must be implemented"
    from bookgen.adapters.llm.gemini import GeminiProvider
    from bookgen.adapters.storage.local_fs import LocalFSStorage
    from bookgen.config import load_settings
    return GeminiProvider, LocalFSStorage, load_settings


async def test_structured_requests_distinct_strategies_cache_and_thumbnails(tmp_path):
    Provider, Storage, settings = implementation()
    from bookgen.domain.profiler import ImageInput, profile_content
    from bookgen.domain.fallback import safe_fallback_builder
    from bookgen.schemas import BookContext, PageLayoutAST
    storage = Storage(tmp_path)
    image = BytesIO()
    Image.new("RGB", (1800, 1000)).save(image, "PNG")
    profile = profile_content("Exact current page text.", [ImageInput(image.getvalue())], storage=storage)
    requests = []

    async def transport(request):
        requests.append(request)
        return safe_fallback_builder(profile.blocks, profile.assets)[len(requests) % 2 == 0].model_dump(mode="json")

    provider = Provider(storage=storage, settings=settings(), transport=transport)
    for strategy in ("editorial_visual", "executive_structured"):
        result = await provider.generate_candidate(context=BookContext(title="Book"), blocks=profile.blocks, assets=profile.assets, strategy_tag=strategy)
        assert isinstance(result, PageLayoutAST)
    assert requests[0]["response_schema"] is PageLayoutAST
    assert requests[0]["strategy_directive"] != requests[1]["strategy_directive"]
    assert requests[0]["cache_prefix"] == requests[1]["cache_prefix"]
    assert requests[0]["cache_ttl_seconds"] == settings().llm.prompt_cache_ttl_seconds
    slices = requests[0]["context"]
    assert set(slices) == {"global_book_context", "sliding_rhythm_window", "current_page_payload"}
    thumbnail = base64.b64decode(slices["current_page_payload"]["assets"][0]["inline_data"]["data"])
    with Image.open(BytesIO(thumbnail)) as decoded:
        assert max(decoded.size) <= 768
    assert "storage_key" not in str(slices)
    assert slices["current_page_payload"]["blocks"][0]["text"] == "Exact current page text."


@pytest.mark.parametrize("page_number", [2, 498])
async def test_context_and_repairs_stay_bounded_for_long_books(tmp_path, page_number):
    Provider, Storage, settings = implementation()
    from bookgen.domain.profiler import profile_content
    from bookgen.domain.fallback import safe_fallback_builder
    from bookgen.schemas import BookContext, ValidationIssue
    storage = Storage(tmp_path)
    profile = profile_content("Current source.", storage=storage)
    pair = safe_fallback_builder(profile.blocks, [])
    requests = []

    async def transport(request):
        requests.append(request)
        return pair[0].model_dump(mode="json")

    provider = Provider(storage=storage, settings=settings(), transport=transport)
    history = [{"page_num": n, "archetype": "minimalist_swiss", "density_class": "normal", "has_callout": False} for n in range(1, page_number)]
    kwargs = dict(context=BookContext(), blocks=profile.blocks, assets=[], strategy_tag="editorial_visual", rhythm_history=history, page_number=page_number)
    await provider.generate_candidate(**kwargs)
    error = ValidationIssue(code="MISSING_BLOCK_ID", severity="error", message="Missing blk_02", target_option="option_a")
    await provider.repair_candidate(**kwargs, candidate=pair[0], issues=[error])
    for request in requests:
        assert set(request["context"]) == {"global_book_context", "sliding_rhythm_window", "current_page_payload"}
        assert len(request["context"]["sliding_rhythm_window"]["pages"]) <= 3
    assert requests[1]["repair"]["issues"][0]["message"] == "Missing blk_02"
    assert requests[0]["cache_prefix"] == requests[1]["cache_prefix"]
    assert requests[1]["repair_directive"]


async def test_oversize_thumbnail_is_resized_and_invalid_output_rejected(tmp_path):
    Provider, Storage, settings = implementation()
    from bookgen.domain.profiler import ImageInput, profile_content
    from bookgen.schemas import BookContext
    storage = Storage(tmp_path)
    raw = BytesIO()
    Image.new("RGB", (1400, 1000)).save(raw, "PNG")
    profile = profile_content("Text", [ImageInput(raw.getvalue())], storage=storage)
    storage.put(profile.assets[0].thumbnail_key, raw.getvalue())
    requests = []

    async def transport(request):
        requests.append(request)
        return {"raw_html": "<body>unsafe</body>"}

    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        await Provider(storage=storage, settings=settings(), transport=transport).generate_candidate(context=BookContext(), blocks=profile.blocks, assets=profile.assets, strategy_tag="editorial_visual")
    data = requests[0]["context"]["current_page_payload"]["assets"][0]["inline_data"]["data"]
    with Image.open(BytesIO(base64.b64decode(data))) as thumbnail:
        assert max(thumbnail.size) <= 768


async def test_real_sdk_boundary_uses_structured_schema_and_inline_images(tmp_path):
    """Exercise the actual SDK config/parts with a fake async SDK client."""
    Provider, Storage, settings = implementation()
    from types import SimpleNamespace
    from bookgen.domain.profiler import ImageInput, profile_content
    from bookgen.domain.fallback import safe_fallback_builder
    from bookgen.schemas import BookContext, PageLayoutAST
    storage = Storage(tmp_path)
    data = BytesIO()
    Image.new("RGB", (1000, 900)).save(data, "PNG")
    source = profile_content("Body.", [ImageInput(data.getvalue())], storage=storage)
    requests = []
    cache_requests = []
    closed = []
    pair = safe_fallback_builder(source.blocks, source.assets)

    async def generate(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(parsed=None, text=pair[0].model_dump_json())

    async def cache(**kwargs):
        cache_requests.append(kwargs)
        return SimpleNamespace(name="cached/stable-global")

    async def close():
        closed.append(True)

    fake = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate), caches=SimpleNamespace(create=cache), aclose=close))
    config = settings()
    provider = Provider(storage=storage, settings=config, client=fake)
    kwargs = dict(context=BookContext(title="Fixed global"), blocks=source.blocks, assets=source.assets, strategy_tag="editorial_visual")
    assert isinstance(await provider.generate_candidate(**kwargs), PageLayoutAST)
    request = requests[0]
    inspected = provider.api_payload(provider._request(**kwargs))
    assert inspected["system_instruction"] == request["config"].system_instruction
    assert inspected["generation_config"]["response_json_schema"] == request["config"].response_json_schema
    assert inspected["contents"][0]["parts"][0]["text"] == request["contents"][0].text
    assert base64.b64decode(inspected["contents"][0]["parts"][1]["inline_data"]["data"]) == request["contents"][1].inline_data.data
    assert request["config"].response_schema is None
    assert request["config"].response_json_schema["additionalProperties"] is False
    assert "option_id" in request["config"].response_json_schema["properties"]
    assert set(request["config"].response_json_schema["required"]).issubset(request["config"].response_json_schema["properties"])
    assert "maxLength" not in str(request["config"].response_json_schema)
    assert "default" not in str(request["config"].response_json_schema)
    assert request["config"].response_mime_type == "application/json"
    assert request["config"].system_instruction
    assert request["contents"][1].inline_data.mime_type == "image/png"
    with Image.open(BytesIO(request["contents"][1].inline_data.data)) as thumbnail:
        assert max(thumbnail.size) <= 768
    config.llm.explicit_cache = True
    await provider.generate_candidate(**kwargs)
    await provider.generate_candidate(**kwargs)
    assert len(cache_requests) == 1
    assert requests[-1]["config"].cached_content == "cached/stable-global"
    assert cache_requests[0]["config"].ttl == "3600s"
    await provider.close()
    assert closed == [True]
