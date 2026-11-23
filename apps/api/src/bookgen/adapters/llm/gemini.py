"""Gemini structured output through one bounded initial/repair request builder."""

import asyncio
import base64
from hashlib import sha256
from io import BytesIO
import json
import time

from PIL import Image

from bookgen.config.llm import load_prompts
from bookgen.schemas import ComponentType, PageLayoutAST, SurfaceRole

from .context import request_context


_GEMINI_JSON_SCHEMA_KEYS = frozenset({
    "$id", "$defs", "$ref", "$anchor", "type", "format", "title", "description",
    "enum", "items", "prefixItems", "minItems", "maxItems", "minimum", "maximum",
    "anyOf", "oneOf", "properties", "additionalProperties", "required", "propertyOrdering",
})


def _gemini_json_schema(model):
    """Return Pydantic's schema using only Gemini responseJsonSchema keywords.

    Pydantic remains the authoritative validator after generation. Gemini's JSON
    Schema subset omits several JSON Schema validation keywords such as defaults
    and string length bounds, so those are intentionally left to local validation.
    """
    def supported(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key not in _GEMINI_JSON_SCHEMA_KEYS:
                    continue
                if key in {"properties", "$defs"} and isinstance(item, dict):
                    # These objects are maps whose names are user schema keys,
                    # rather than JSON Schema keywords themselves.
                    result[key] = {name: supported(schema) for name, schema in item.items()}
                else:
                    result[key] = supported(item)
            return result
        if isinstance(value, list):
            return [supported(item) for item in value]
        return value

    return supported(model.model_json_schema())


class GeminiProvider:
    def __init__(self, *, storage, settings, transport=None, client=None):
        self.storage = storage
        self.settings = settings
        self.prompts = load_prompts()
        self.transport = transport or self._sdk_transport
        self.client = client
        self._caches = {}
        self._cache_lock = asyncio.Lock()

    def _thumbnail(self, asset):
        config = self.settings.profiling
        if config is None:
            raise ValueError("Profiling settings are required")
        with Image.open(BytesIO(self.storage.get(asset.thumbnail_key))) as source:
            source.thumbnail((config.thumbnail_max_px, config.thumbnail_max_px), Image.Resampling.LANCZOS)
            data = BytesIO()
            source.save(data, format="PNG")
        return {"mime_type": "image/png", "data": base64.b64encode(data.getvalue()).decode("ascii")}

    def _request(self, *, context, blocks, assets, strategy_tag, rhythm_history=None, page_number=None):
        metadata = request_context.get()
        history = list(metadata.rhythm_history if rhythm_history is None else rhythm_history)[-self.settings.llm.rhythm_window:]
        # Pick only compact summary fields even if callers accidentally pass rich history.
        history = [{key: entry[key] for key in ("page_num", "archetype", "density_class", "has_callout")} for entry in history]
        global_context = {
            "book": context.model_dump(mode="json"),
            "semantic_token_roles": {"surface": [role.value for role in SurfaceRole], "components": [kind.value for kind in ComponentType]},
            "grammar": self.settings.grammar.model_dump(mode="json"),
        }
        prefix = json.dumps({"system": self.prompts["system_art_director"].model_dump(), "global_book_context": global_context}, sort_keys=True)
        option = next(key for key, value in self.settings.llm.strategy_families.items() if value == strategy_tag)
        return {
            "model": self.settings.llm.model,
            "temperature": self.settings.llm.temperature,
            "transport_mode": self.settings.llm.transport_mode,
            "response_schema": PageLayoutAST,
            "cache_prefix": prefix,
            "cache_key": sha256(prefix.encode()).hexdigest(),
            "cache_ttl_seconds": self.settings.llm.prompt_cache_ttl_seconds,
            "strategy_directive": self.prompts[f"strategy_{option}"].text,
            "context": {
                "global_book_context": global_context,
                "sliding_rhythm_window": {"pages": history, "excluded_archetypes": [entry["archetype"] for entry in history]},
                "current_page_payload": {
                    "page_number": page_number if page_number is not None else metadata.page_number,
                    "blocks": [block.model_dump(mode="json") for block in blocks],
                    "assets": [{"asset_id": asset.asset_id, "aspect_ratio": asset.aspect_ratio, "asset_kind": asset.asset_kind.value, "alt_caption": asset.alt_caption, "inline_data": self._thumbnail(asset)} for asset in assets],
                },
            },
        }

    async def generate_candidate(self, *, context, blocks, assets, strategy_tag, rhythm_history=None, page_number=None):
        request = self._request(context=context, blocks=blocks, assets=assets, strategy_tag=strategy_tag, rhythm_history=rhythm_history, page_number=page_number)
        return self._parse(await self.transport(request))

    async def repair_candidate(self, *, context, blocks, assets, strategy_tag, candidate, issues, rhythm_history=None, page_number=None):
        request = self._request(context=context, blocks=blocks, assets=assets, strategy_tag=strategy_tag, rhythm_history=rhythm_history, page_number=page_number)
        request["repair_directive"] = self.prompts["critic_repair"].text
        request["repair"] = {"candidate": candidate.model_dump(mode="json") if isinstance(candidate, PageLayoutAST) else candidate,
                             "issues": [issue.model_dump(mode="json") for issue in issues]}
        return self._parse(await self.transport(request))

    @staticmethod
    def _parse(response):
        if isinstance(response, PageLayoutAST):
            return response
        if isinstance(response, str):
            return PageLayoutAST.model_validate_json(response)
        return PageLayoutAST.model_validate(response)

    async def _sdk_transport(self, request):
        from google import genai
        from google.genai import types

        # Credentials stay in the SDK's environment/ADC chain, outside checkpoints.
        if self.client is None:
            self.client = genai.Client(vertexai=self.settings.llm.transport_mode == "vertex")
        payload = json.loads(json.dumps(request["context"]))
        payload.pop("global_book_context")
        images = []
        for asset in payload["current_page_payload"]["assets"]:
            inline = asset.pop("inline_data")
            images.append(types.Part.from_bytes(data=base64.b64decode(inline["data"]), mime_type=inline["mime_type"]))
        content = {"strategy_directive": request["strategy_directive"], "context": payload}
        if "repair" in request:
            content.update(repair_directive=request["repair_directive"], repair=request["repair"])
        config = dict(temperature=request["temperature"], response_mime_type="application/json",
                      response_json_schema=_gemini_json_schema(request["response_schema"]))
        if self.settings.llm.explicit_cache and request["cache_ttl_seconds"]:
            async with self._cache_lock:
                entry = self._caches.get(request["cache_key"])
                if entry is None or entry[1] <= time.monotonic():
                    cached = await self.client.aio.caches.create(model=request["model"], config=types.CreateCachedContentConfig(
                        system_instruction=request["cache_prefix"], ttl=f"{request['cache_ttl_seconds']}s"))
                    entry = (cached.name, time.monotonic() + request["cache_ttl_seconds"])
                    self._caches[request["cache_key"]] = entry
                config["cached_content"] = entry[0]
        else:
            config["system_instruction"] = request["cache_prefix"]
        response = await self.client.aio.models.generate_content(model=request["model"],
            contents=[types.Part.from_text(text=json.dumps(content)), *images], config=types.GenerateContentConfig(**config))
        return response.parsed if response.parsed is not None else response.text

    async def close(self):
        if self.client is not None:
            await self.client.aio.aclose()
