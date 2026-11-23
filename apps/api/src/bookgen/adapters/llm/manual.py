"""Use the production request builder, replacing network I/O with HITL."""
import json

from langgraph.types import interrupt

from .gemini import GeminiProvider, asset_metadata


class ManualLLMProvider(GeminiProvider):
    def __init__(self, *, storage, settings):
        super().__init__(storage=storage, settings=settings, transport=self._manual_transport)
        self.exchanges = []

    @staticmethod
    def metadata_request(payload, assets=()):
        """Present persisted requests without image parts or storage fields.

        Older requests did not include dimensions. Recover only resolution facts
        from local state, retaining the request's already privacy-masked caption.
        The original persisted interrupt is never modified.
        """
        payload = json.loads(json.dumps(payload))
        parts = payload["contents"][0]["parts"]
        content = json.loads(parts[0]["text"])
        local = {asset["asset_id"]: asset_metadata(asset) for asset in assets}
        projected = []
        for asset in content["context"]["current_page_payload"]["assets"]:
            metadata = asset_metadata(asset)
            for key in ("width_px", "height_px", "estimated_dpi"):
                if key not in metadata and key in local.get(metadata["asset_id"], {}):
                    metadata[key] = local[metadata["asset_id"]][key]
            projected.append(metadata)
        content["context"]["current_page_payload"]["assets"] = projected
        payload["contents"] = [{"role": "user", "parts": [{"text": json.dumps(content)}]}]
        return payload

    def present_exchange(self, exchange, assets=()):
        """Adapt legacy interrupts/exchanges while preserving current prompts."""
        request = self.metadata_request(exchange["request"], assets)
        changed = request != exchange["request"] or "images" in exchange or not exchange.get("prompt")
        result = {key: value for key, value in exchange.items() if key != "images"}
        result["request"] = request
        if changed:
            result.update(self.chat_input(request))
        return result

    def chat_input(self, payload):
        """Flatten the effective metadata-only request into copyable text.

        Build from the same content used by the SDK, including masked source
        blocks and bounded history. Formatting changes only the inspection view.
        """
        payload = self.metadata_request(payload)
        system = json.loads(payload["system_instruction"])
        parts = payload["contents"][0]["parts"]
        content = json.loads(parts[0]["text"])

        def pretty(value):
            return json.dumps(value, indent=2, ensure_ascii=False)

        prompt = self.prompts["debug_chat"].text.format(
            system_instructions=system["system"]["text"].rstrip(),
            global_context=pretty(system["global_book_context"]),
            strategy_directive=content["strategy_directive"].rstrip(),
            page_context=pretty(content["context"]),
            repair_directive=content.get("repair_directive", "").rstrip(),
            repair_context=pretty(content.get("repair", {})),
            response_schema=pretty(payload["generation_config"]["response_json_schema"]))
        return {"prompt": prompt}

    async def _manual_transport(self, request):
        option_id = next(key for key in self.settings.llm.strategy_families
            if request["strategy_directive"] == self.prompts[f"strategy_{key}"].text)
        payload = self.api_payload(request)
        chat = self.chat_input(payload)
        response = interrupt({"event": "llm_request", "option_id": option_id, "request": payload, **chat})
        if isinstance(response, dict):
            # The debugger binds a reply to the persisted request rather than
            # the request rebuilt while LangGraph replays this node. String
            # resumes from older checkpoints remain supported.
            payload = response["request"]
            chat = {"prompt": response["prompt"]}
            response = response["response"]
        self.exchanges.append(self.present_exchange({"option_id": option_id, "request": payload, "prompt": chat["prompt"], "response": response}))
        return response
