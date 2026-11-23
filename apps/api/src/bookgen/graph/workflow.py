"""Durable LangGraph page lifecycle with an idempotent session service boundary."""

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from uuid import uuid4

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from bookgen.schemas import BookContext, PageGenerationResult
from bookgen.schemas.sessions import SessionSnapshot

from .nodes import PageNodes
from .state import PageState


def build_page_graph(*, provider, repository, storage, settings, checkpointer):
    nodes = PageNodes(provider=provider, repository=repository, storage=storage, settings=settings)
    builder = StateGraph(PageState)
    for name in ("profile", "generate_candidates", "validate", "repair", "fallback", "build_review", "human_review_interrupt", "commit_page"):
        builder.add_node(name, getattr(nodes, name))
    builder.add_edge(START, "profile")
    builder.add_edge("profile", "generate_candidates")
    builder.add_edge("generate_candidates", "validate")
    builder.add_conditional_edges("validate", nodes.after_validation, {name: name for name in ("repair", "fallback", "build_review")})
    builder.add_edge("repair", "validate")
    builder.add_edge("fallback", "build_review")
    builder.add_edge("build_review", "human_review_interrupt")
    builder.add_edge("human_review_interrupt", "commit_page")
    builder.add_edge("commit_page", END)
    return builder.compile(checkpointer=checkpointer)


class PageWorkflow:
    def __init__(self, *, repository, provider, storage, settings):
        self.repository = repository
        self.provider = provider
        self.storage = storage
        self.settings = settings
        self._locks = defaultdict(asyncio.Lock)

    @asynccontextmanager
    async def _graph(self):
        async with AsyncSqliteSaver.from_conn_string(self.repository.path) as saver:
            yield build_page_graph(provider=self.provider, repository=self.repository, storage=self.storage, settings=self.settings, checkpointer=saver)

    @staticmethod
    def _config(session_id):
        return {"configurable": {"thread_id": session_id}}

    def create_session(self, context=None):
        context = context or BookContext()
        return SessionSnapshot(session_id=self.repository.create_session(context), context=context)

    async def snapshot(self, session_id):
        context = self.repository.load_context(session_id)
        committed = self.repository.load_snapshots(session_id)
        async with self._graph() as graph:
            checkpoint = await graph.aget_state(self._config(session_id))
        values = checkpoint.values
        result = values.get("result")
        pending = PageGenerationResult.model_validate(result) if result and checkpoint.next else None
        return SessionSnapshot(session_id=session_id, context=context, pending_review=pending,
            committed_pages=committed, current_page_index=len(committed) + 1,
            rolling_layout_history=values.get("rolling_layout_history", []), assets=self.repository.load_assets(session_id))

    async def generate(self, session_id, *, text, assets=()):
        async with self._locks[session_id]:
            snapshot = await self.snapshot(session_id)
            if snapshot.pending_review is not None:
                raise ValueError("A pending page requires selection before generating another")
            async with self._graph() as graph:
                checkpoint = await graph.aget_state(self._config(session_id))
                # Refuse to overwrite a checkpoint if an earlier generation failed mid-node.
                if checkpoint.next:
                    raise ValueError("A pending generation must be resumed before creating another page")
                state = {"session_id": session_id, "context": snapshot.context.model_dump(mode="json"), "text": text,
                    "assets": [asset.model_dump(mode="json") for asset in assets], "page_id": uuid4().hex,
                    "page_number": snapshot.current_page_index, "current_page_index": snapshot.current_page_index,
                    "rolling_layout_history": [archetype.value for archetype in snapshot.rolling_layout_history],
                    "rhythm_history": checkpoint.values.get("rhythm_history", [])}
                generated = await graph.ainvoke(state, self._config(session_id))
            return PageGenerationResult.model_validate(generated["result"])

    async def select(self, session_id, page_id, option_id):
        if option_id not in ("option_a", "option_b"):
            raise ValueError("Invalid selection")
        async with self._locks[session_id]:
            snapshot = await self.snapshot(session_id)
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
