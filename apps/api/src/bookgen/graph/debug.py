"""Durable node inspection using static boundaries and typed dynamic interrupts."""
import inspect
import json
from hashlib import sha256
from uuid import uuid4

from langgraph.types import Command

from bookgen.domain.theme import sanitize_tokens
from bookgen.schemas.debug import DebugSnapshot
from bookgen.schemas.publishing import AppearanceResponse


def public_state(state):
    return {key: value for key, value in state.items() if not key.startswith("debug_")}


def inspect_node(name, action, provider):
    async def run(state):
        provider.exchanges.clear()
        result = action(state)
        if inspect.isawaitable(result):
            result = await result
        return {**result, "debug_last_node": name, "debug_node_input": public_state(state),
            "debug_node_output": result, "debug_exchanges": list(provider.exchanges)}
    return run


class PageDebugger:
    def __init__(self, workflow):
        self.workflow = workflow

    def _enabled(self):
        if not self.workflow.settings.app.debug_mode:
            raise PermissionError("Enable BOOKGEN__APP__DEBUG_MODE to use the debugger")

    def _snapshot(self, sid, checkpoint):
        values = checkpoint.values
        active = values.get("debug_mode", False)
        interrupts = [item.value for task in checkpoint.tasks for item in task.interrupts] if active else []
        next_nodes = list(checkpoint.next) or [task.name for task in checkpoint.tasks if task.interrupts]
        raw_id = checkpoint.config["configurable"].get("checkpoint_id") if checkpoint.config else None
        # Multiple dynamic interrupts within one node share a checkpoint ID.
        # Bind the action to the current interrupt payload as well as that ID.
        revision = sha256(json.dumps([raw_id, interrupts], sort_keys=True).encode()).hexdigest() if raw_id else None
        # Older checkpoints contain the effective request but no chat text. Adapt
        # their presentation without changing persisted interrupts/resume tokens.
        if any(item["event"] == "llm_request" and not item.get("prompt") for item in interrupts):
            from bookgen.adapters.llm.manual import ManualLLMProvider
            provider = ManualLLMProvider(storage=self.workflow.storage, settings=self.workflow.settings)
            interrupts = [{**item, **provider.chat_input(item["request"])}
                if item["event"] == "llm_request" and not item.get("prompt") else item for item in interrupts]
        appearance = self.workflow.repository.load_appearance(sid)
        appearance = appearance.model_copy(update={"tokens": sanitize_tokens(appearance.tokens, self.workflow.settings.theme)})
        return DebugSnapshot(session_id=sid,
            checkpoint_id=revision,
            status="paused" if active and next_nodes else "completed" if active else "idle",
            next_nodes=next_nodes if active else [], last_node=values.get("debug_last_node"),
            state=public_state(values) if active else {}, node_input=values.get("debug_node_input", {}),
            node_output={**values.get("debug_node_output", {}), **({"llm_exchanges": values["debug_exchanges"]} if values.get("debug_exchanges") else {})},
            interrupts=interrupts,
            appearance=AppearanceResponse(status="available", **appearance.model_dump()))

    async def snapshot(self, sid):
        self._enabled()
        self.workflow.repository.load_context(sid)
        async with self.workflow._graph(manual_debug=True) as graph:
            return self._snapshot(sid, await graph.aget_state(self.workflow._config(sid)))

    async def start(self, sid, *, text, assets=()):
        self._enabled()
        service = self.workflow
        async with service._locks[sid]:
            snapshot = await service.snapshot(sid)
            async with service._graph(manual_debug=True) as graph:
                config = service._config(sid)
                checkpoint = await graph.aget_state(config)
                if checkpoint.next or any(task.interrupts for task in checkpoint.tasks):
                    raise ValueError("A pending generation must finish before starting another")
                state = {"session_id": sid, "context": snapshot.context.model_dump(mode="json"), "text": text,
                    "assets": [asset.model_dump(mode="json") for asset in assets], "page_id": uuid4().hex,
                    "page_number": snapshot.current_page_index, "current_page_index": snapshot.current_page_index,
                    "rolling_layout_history": [item.value for item in snapshot.rolling_layout_history],
                    "rhythm_history": checkpoint.values.get("rhythm_history", []), "debug_mode": True,
                    "debug_last_node": None, "debug_node_input": {}, "debug_node_output": {}, "debug_exchanges": [],
                    "result": None, "blocks": [], "metrics_ledger": [], "options": [], "validation_issues": [],
                    "profile_issues": [], "selection": "", "repair_attempts": 0, "used_fallback": False}
                await graph.ainvoke(state, config)
                return self._snapshot(sid, await graph.aget_state(config))

    async def step(self, sid, *, checkpoint_id, response=None):
        self._enabled()
        service = self.workflow
        async with service._locks[sid]:
            service.repository.load_context(sid)
            async with service._graph(manual_debug=True) as graph:
                config = service._config(sid)
                checkpoint = await graph.aget_state(config)
                snapshot = self._snapshot(sid, checkpoint)
                if snapshot.status != "paused" or snapshot.checkpoint_id != checkpoint_id:
                    raise ValueError("Stale checkpoint or no paused debug run; reload before stepping")
                if snapshot.interrupts:
                    event = snapshot.interrupts[0].event
                    if response is None or not response.strip():
                        raise ValueError("A response is required at this interrupt")
                    if event == "review" and response not in ("option_a", "option_b"):
                        raise ValueError("Select option_a or option_b")
                    value = Command(resume=response)
                else:
                    if response is not None:
                        raise ValueError("No response is accepted at a node boundary")
                    value = None
                await graph.ainvoke(value, config)
                return self._snapshot(sid, await graph.aget_state(config))
