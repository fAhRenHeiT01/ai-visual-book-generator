"""Use the production request builder, replacing network I/O with HITL."""
import json

from langgraph.types import interrupt

from .gemini import GeminiProvider


class ManualLLMProvider(GeminiProvider):
    def __init__(self, *, storage, settings):
        super().__init__(storage=storage, settings=settings, transport=self._manual_transport)
        self.exchanges = []

    def chat_input(self, payload):
        """Flatten the effective request into text plus separate image attachments.

        Build from the same content used by the SDK, including masked source
        blocks and bounded history. Formatting changes only the inspection view.
        """
        system = json.loads(payload["system_instruction"])
        parts = payload["contents"][0]["parts"]
        content = json.loads(parts[0]["text"])
        assets = content["context"]["current_page_payload"]["assets"]
        images = [{"asset_id": asset["asset_id"], **part["inline_data"]}
            for asset, part in zip(assets, parts[1:], strict=True)]

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
        return {"prompt": prompt, "images": images}

    async def _manual_transport(self, request):
        option_id = next(key for key in self.settings.llm.strategy_families
            if request["strategy_directive"] == self.prompts[f"strategy_{key}"].text)
        payload = self.api_payload(request)
        chat = self.chat_input(payload)
        response = interrupt({"event": "llm_request", "option_id": option_id, "request": payload, **chat})
        self.exchanges.append({"option_id": option_id, "request": payload, "prompt": chat["prompt"], "response": response})
        return response
