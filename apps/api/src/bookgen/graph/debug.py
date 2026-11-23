"""Durable node inspection using static boundaries and typed dynamic interrupts."""
import inspect
import json
from hashlib import sha256
from uuid import uuid4

from langgraph.types import Command

from bookgen.domain.theme import sanitize_tokens
from bookgen.schemas.debug import DebugSnapshot, DebugTimelineEntry
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
        # Hash the original interrupt above, then project its presentation. Resume
        # identity must still refer to the checkpoint stored before this upgrade.
        from bookgen.adapters.llm.manual import ManualLLMProvider
        provider = ManualLLMProvider(storage=self.workflow.storage, settings=self.workflow.settings)
        assets = values.get("assets", [])
        interrupts = [provider.present_exchange(item, assets) if item["event"] == "llm_request" else item for item in interrupts]
        exchanges = [provider.present_exchange(item, assets) for item in values.get("debug_exchanges", [])]
        appearance = self.workflow.repository.load_appearance(sid)
        appearance = appearance.model_copy(update={"tokens": sanitize_tokens(appearance.tokens, self.workflow.settings.theme)})
        return DebugSnapshot(session_id=sid,
            studio_active=not active and bool(next_nodes) and values.get("page_id") not in {page.page_id for page in self.workflow.repository.load_snapshots(sid)},
            checkpoint_id=revision,
            status="paused" if active and next_nodes else "completed" if active else "idle",
            next_nodes=next_nodes if active else [], last_node=values.get("debug_last_node") if active else None,
            state=public_state(values) if active else {}, node_input=values.get("debug_node_input", {}) if active else {},
            node_output={**values.get("debug_node_output", {}), **({"llm_exchanges": exchanges} if exchanges else {})} if active else {},
            interrupts=interrupts,
            appearance=AppearanceResponse(status="available", **appearance.model_dump()))

    async def _inspect(self, sid, graph):
        checkpoint = await graph.aget_state(self.workflow._config(sid))
        snapshot = self._snapshot(sid, checkpoint)
        if snapshot.status == "idle":
            return snapshot
        # Derive the timeline from durable checkpoints, including runs saved by
        # earlier versions. Stop at this page's boundary; never include book history.
        history = []
        async for saved in graph.aget_state_history(self.workflow._config(sid)):
            if saved.values.get("page_id") != checkpoint.values.get("page_id"):
                break
            history.append(saved)
        previous = None
        for saved in reversed(history):
            values = saved.values
            marker = [values.get("debug_last_node"), values.get("debug_node_input"), values.get("debug_node_output")]
            if not marker[0] or marker == previous:
                continue
            previous = marker
            view = self._snapshot(sid, saved)
            snapshot.timeline.append(DebugTimelineEntry(node=view.last_node, status="completed",
                node_input=view.node_input, node_output=view.node_output,
                validation_issues=values.get("validation_issues", []),
                review=values.get("result") if view.last_node in ("build_review", "human_review_interrupt", "commit_page") else None))
        if snapshot.status == "paused":
            review = next((item.page for item in snapshot.interrupts if item.event == "review"), None)
            snapshot.timeline.append(DebugTimelineEntry(node=snapshot.next_nodes[0], status="paused",
                node_input=snapshot.state, validation_issues=snapshot.state.get("validation_issues", []), review=review))
        return snapshot

    async def snapshot(self, sid):
        self._enabled()
        self.workflow.repository.load_context(sid)
        async with self.workflow._graph(manual_debug=True) as graph:
            return await self._inspect(sid, graph)

    async def start(self, sid, *, text, assets=(), page_id=None, revise=False):
        self._enabled()
        service = self.workflow
        async with service._page_lock(sid):
            snapshot = await service.snapshot(sid)
            async with service._graph(manual_debug=True) as graph:
                config = service._config(sid)
                checkpoint = await graph.aget_state(config)
                values = checkpoint.values
                if checkpoint.next or any(task.interrupts for task in checkpoint.tasks):
                    if values.get("debug_mode") and page_id is not None and page_id == values.get("page_id") and not revise and values.get("text") == text and [asset["asset_id"] for asset in values.get("assets", [])] == [asset.asset_id for asset in assets]:
                        return await self._inspect(sid, graph)
                    raise ValueError("A pending generation must finish before starting another")
                if any(page.page_id == page_id for page in snapshot.committed_pages):
                    if values.get("debug_mode") and values.get("page_id") == page_id:
                        return await self._inspect(sid, graph)
                    raise ValueError("Page was already committed")
                if revise:
                    raise ValueError("A manual run must resume its saved checkpoint")
                state = {"session_id": sid, "context": snapshot.context.model_dump(mode="json"), "text": text,
                    "assets": [asset.model_dump(mode="json") for asset in assets], "page_id": page_id or uuid4().hex,
                    "page_number": snapshot.current_page_index, "current_page_index": snapshot.current_page_index,
                    "rolling_layout_history": [item.value for item in snapshot.rolling_layout_history],
                    "rhythm_history": checkpoint.values.get("rhythm_history", []), "debug_mode": True,
                    "debug_last_node": None, "debug_node_input": {}, "debug_node_output": {}, "debug_exchanges": [],
                    "result": None, "blocks": [], "metrics_ledger": [], "options": [], "validation_issues": [],
                    "profile_issues": [], "selection": "", "repair_attempts": 0, "used_fallback": False}
                await graph.ainvoke(state, config)
                return await self._inspect(sid, graph)

    async def step(self, sid, *, checkpoint_id, response=None):
        self._enabled()
        service = self.workflow
        async with service._page_lock(sid):
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
                    # Nodes replay after an interrupt. Preserve the effective
                    # request the user saw even if prompts/settings changed
                    # between the pause and this resume (or a process restart).
                    resume = {"response": response, "request": snapshot.interrupts[0].request,
                        "prompt": snapshot.interrupts[0].prompt} if event == "llm_request" else response
                    value = Command(resume=resume)
                else:
                    if response is not None:
                        raise ValueError("No response is accepted at a node boundary")
                    value = None
                await graph.ainvoke(value, config)
                return await self._inspect(sid, graph)
