"""Durable LangGraph page lifecycle with an idempotent session service boundary."""

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from uuid import uuid4

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from bookgen.schemas import BookContext, PageGenerationResult
from bookgen.schemas.sessions import ActivePage, SessionSnapshot

from .nodes import PageNodes
from .state import PageState


def build_page_graph(*, provider, repository, storage, settings, checkpointer, manual_debug=False):
    nodes = PageNodes(provider=provider, repository=repository, storage=storage, settings=settings)
    builder = StateGraph(PageState)
    for name in ("profile", "compliance_metrics_scan", "generate_candidates", "validate", "repair", "fallback", "build_review", "human_review_interrupt", "commit_page"):
        action = getattr(nodes, name)
        if manual_debug:
            from .debug import inspect_node
            action = inspect_node(name, action, provider)
        builder.add_node(name, action)
    builder.add_edge(START, "profile")
    builder.add_edge("profile", "compliance_metrics_scan")
    builder.add_edge("compliance_metrics_scan", "generate_candidates")
    builder.add_edge("generate_candidates", "validate")
    builder.add_conditional_edges("validate", nodes.after_validation, {name: name for name in ("repair", "fallback", "build_review")})
    builder.add_edge("repair", "validate")
    builder.add_edge("fallback", "build_review")
    builder.add_edge("build_review", "human_review_interrupt")
    builder.add_edge("human_review_interrupt", "commit_page")
    builder.add_edge("commit_page", END)
    return builder.compile(checkpointer=checkpointer,
        interrupt_before=["profile"] if manual_debug else None,
        interrupt_after="*" if manual_debug else None)


class PageConflict(ValueError):
    """A different unfinished page owns this session."""


class PageWorkflow:
    # Services reopened against the same database share the session critical section.
    _session_locks = defaultdict(asyncio.Lock)

    def __init__(self, *, repository, provider, storage, settings):
        self.repository = repository
        self.provider = provider
        self.storage = storage
        self.settings = settings
        self._locks = self._session_locks
        from .debug import PageDebugger
        self.debugger = PageDebugger(self)

    @asynccontextmanager
    async def _page_lock(self, session_id):
        async with self._locks[(self.repository.path, id(asyncio.get_running_loop()), session_id)]:
            acquisition = asyncio.create_task(asyncio.to_thread(self.repository.acquire_page_lock, session_id))
            try:
                handle = await asyncio.shield(acquisition)
            except asyncio.CancelledError:
                # A cancelled waiter must not leave a lock acquired by its thread.
                handle = await acquisition
                handle.close()
                raise
            try:
                yield
            finally:
                handle.close()

    @asynccontextmanager
    async def _graph(self, *, manual_debug=False):
        provider = self.provider
        if manual_debug:
            from bookgen.adapters.llm.manual import ManualLLMProvider
            provider = ManualLLMProvider(storage=self.storage, settings=self.settings)
        async with AsyncSqliteSaver.from_conn_string(self.repository.path) as saver:
            yield build_page_graph(provider=provider, repository=self.repository, storage=self.storage, settings=self.settings,
                checkpointer=saver, manual_debug=manual_debug)

    @staticmethod
    def _config(session_id):
        return {"configurable": {"thread_id": session_id}}

    def create_session(self, context=None):
        context = context or BookContext()
        return SessionSnapshot(session_id=self.repository.create_session(context), context=context,
            debug_enabled=self.settings.app.debug_mode)

    async def snapshot(self, session_id):
        context = self.repository.load_context(session_id)
        committed = self.repository.load_snapshots(session_id)
        async with self._graph() as graph:
            checkpoint = await graph.aget_state(self._config(session_id))
        values = checkpoint.values
        result = values.get("result")
        paused = bool(checkpoint.next or any(task.interrupts for task in checkpoint.tasks))
        uncommitted = values.get("page_id") not in {page.page_id for page in committed}
        pending = PageGenerationResult.model_validate(result) if result and paused and uncommitted and result.get("page_id") == values.get("page_id") and not result.get("selected_option_id") else None
        active = ActivePage(page_id=values["page_id"], page_number=values["page_number"],
            text=values.get("text", ""), asset_ids=[asset["asset_id"] for asset in values.get("assets", [])]) if paused and uncommitted and values.get("page_id") else None
        return SessionSnapshot(session_id=session_id, context=context, pending_review=pending, active_page=active,
            debug_enabled=self.settings.app.debug_mode, debug_active=bool(values.get("debug_mode") and paused),
            committed_pages=committed, current_page_index=len(committed) + 1,
            rolling_layout_history=values.get("rolling_layout_history", []), assets=self.repository.load_assets(session_id))

    async def generate(self, session_id, *, text, assets=(), page_id=None, revise=False):
        async with self._page_lock(session_id):
            snapshot = await self.snapshot(session_id)
            if self.settings.app.debug_mode:
                if snapshot.debug_active:
                    raise PageConflict("A pending debug page must be resumed through the debug endpoint")
                raise ValueError("Use the debug page endpoint while debug mode is enabled")
            committed = next((page for page in snapshot.committed_pages if page.page_id == page_id), None)
            if committed is not None:
                # Finish a commit checkpoint left behind by an interrupted response.
                async with self._graph() as graph:
                    checkpoint = await graph.aget_state(self._config(session_id))
                    if checkpoint.next and checkpoint.values.get("page_id") == page_id:
                        resume = Command(resume=committed.selected_option_id) if "human_review_interrupt" in checkpoint.next else None
                        await graph.ainvoke(resume, self._config(session_id))
                return committed
            async with self._graph() as graph:
                checkpoint = await graph.aget_state(self._config(session_id))
                values = checkpoint.values
                checkpoint_commit = next((page for page in snapshot.committed_pages if page.page_id == values.get("page_id")), None)
                if checkpoint.next and checkpoint_commit is not None:
                    resume = Command(resume=checkpoint_commit.selected_option_id) if "human_review_interrupt" in checkpoint.next else None
                    await graph.ainvoke(resume, self._config(session_id))
                    checkpoint = await graph.aget_state(self._config(session_id))
                    values = checkpoint.values
                    snapshot = await self.snapshot(session_id)
                unfinished = bool(checkpoint.next or any(task.interrupts for task in checkpoint.tasks))
                same_input = values.get("text") == text and [asset["asset_id"] for asset in values.get("assets", [])] == [asset.asset_id for asset in assets]
                if unfinished:
                    if (page_id is not None and page_id != values.get("page_id")) or (page_id is None and not same_input):
                        raise PageConflict("A pending page requires selection or recovery before creating another")
                    if snapshot.debug_active:
                        raise ValueError("Resume this page through the debug step endpoint")
                    if snapshot.pending_review is not None:
                        if not same_input or revise:
                            raise ValueError("Select the saved review before editing another page")
                        return snapshot.pending_review
                    if not same_input and not revise:
                        raise ValueError("Changed input requires an explicit revision")
                    if not revise:
                        generated = await graph.ainvoke(None, self._config(session_id))
                        return PageGenerationResult.model_validate(generated["result"])
                    page_id = values["page_id"]
                state = {"debug_mode": False, "session_id": session_id, "context": snapshot.context.model_dump(mode="json"), "text": text,
                    "assets": [asset.model_dump(mode="json") for asset in assets], "page_id": page_id or uuid4().hex,
                    "page_number": snapshot.current_page_index, "current_page_index": snapshot.current_page_index,
                    "result": None, "options": [], "validation_issues": [],
                    "rolling_layout_history": [archetype.value for archetype in snapshot.rolling_layout_history],
                    "rhythm_history": values.get("rhythm_history", [])}
                generated = await graph.ainvoke(state, self._config(session_id))
            return PageGenerationResult.model_validate(generated["result"])

    async def select(self, session_id, page_id, option_id):
        if option_id not in ("option_a", "option_b"):
            raise ValueError("Invalid selection")
        async with self._page_lock(session_id):
            snapshot = await self.snapshot(session_id)
            if snapshot.debug_active:
                raise ValueError("Resume this page through the debug step endpoint")
            committed = next((page for page in snapshot.committed_pages if page.page_id == page_id), None)
            if committed is not None:
                if committed.selected_option_id != option_id:
                    raise ValueError("Page was already committed with another selection")
                # The snapshot transaction can finish just before a process dies.
                # Replay the unfinished commit node to finish its graph checkpoint;
                # the repository's insert-once write makes this safe.
                async with self._graph() as graph:
                    checkpoint = await graph.aget_state(self._config(session_id))
                    if checkpoint.next and checkpoint.values.get("page_id") == page_id:
                        resume = Command(resume=option_id) if "human_review_interrupt" in checkpoint.next else None
                        await graph.ainvoke(resume, self._config(session_id))
                return committed
            if snapshot.pending_review is None or snapshot.pending_review.page_id != page_id:
                raise KeyError(page_id)
            async with self._graph() as graph:
                selected = await graph.ainvoke(Command(resume=option_id), self._config(session_id))
            return PageGenerationResult.model_validate(selected["result"])
