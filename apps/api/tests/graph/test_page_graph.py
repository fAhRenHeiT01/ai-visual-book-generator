"""Durable human review, bounded repair and concurrent provider behavior."""

import asyncio
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "apps/api/src"))


def implementation():
    assert importlib.util.find_spec("bookgen.graph") is not None, "page graph must be implemented"
    from bookgen.graph.workflow import PageWorkflow
    from bookgen.adapters.db.sqlite import SQLiteSessionRepository
    from bookgen.adapters.llm.mock import MockLLMProvider
    from bookgen.adapters.storage.local_fs import LocalFSStorage
    from bookgen.config import load_settings
    return PageWorkflow, SQLiteSessionRepository, MockLLMProvider, LocalFSStorage, load_settings


def workflow(tmp_path, provider=None):
    Graph, Repository, Mock, Storage, settings = implementation()
    repository = Repository(tmp_path / "sessions.db")
    graph = Graph(repository=repository, provider=provider or Mock(), storage=Storage(tmp_path / "uploads"), settings=settings())
    return graph, repository


async def test_parallel_review_resume_and_idempotent_commit(tmp_path):
    _, _, Mock, _, _ = implementation()
    arrived = set()
    rendezvous = asyncio.Event()

    async def meet(strategy):
        arrived.add(strategy)
        if len(arrived) == 2:
            rendezvous.set()
        await asyncio.wait_for(rendezvous.wait(), timeout=2)

    graph, repository = workflow(tmp_path, Mock(rendezvous=meet))
    session = graph.create_session()
    result = await graph.generate(session.session_id, text="First paragraph.\n\nSecond paragraph.")
    snapshot = await graph.snapshot(session.session_id)
    assert arrived == {"editorial_visual", "executive_structured"}
    assert snapshot.pending_review == result
    assert snapshot.committed_pages == []
    assert snapshot.current_page_index == 1
    assert repository.load_snapshots(session.session_id) == []
    with pytest.raises(ValueError, match="selection"):
        await graph.select(session.session_id, result.page_id, "unknown")
    committed = await graph.select(session.session_id, result.page_id, "option_a")
    assert committed.selected_option_id == "option_a"
    assert await graph.select(session.session_id, result.page_id, "option_a") == committed
    with pytest.raises(ValueError, match="already"):
        await graph.select(session.session_id, result.page_id, "option_b")
    assert len(repository.load_snapshots(session.session_id)) == 1
    assert (await graph.snapshot(session.session_id)).current_page_index == 2
    repository.close()


async def test_reopen_exact_pending_page_and_three_selection_history(tmp_path):
    graph, repository = workflow(tmp_path)
    session = graph.create_session()
    choices = []
    for index in range(4):
        result = await graph.generate(session.session_id, text=f"Page {index} source.")
        choices.append(result.option_a.archetype)
        await graph.select(session.session_id, result.page_id, "option_a")
    pending = await graph.generate(session.session_id, text="Pending fifth page.")
    repository.close()
    fresh, fresh_repository = workflow(tmp_path)
    state = await fresh.snapshot(session.session_id)
    assert state.current_page_index == 5
    assert state.pending_review == pending
    assert state.rolling_layout_history == choices[-3:]
    await fresh.select(session.session_id, pending.page_id, "option_b")
    assert len(fresh_repository.load_snapshots(session.session_id)) == 5
    assert (await fresh.snapshot(session.session_id)).current_page_index == 6
    fresh_repository.close()


async def test_missing_block_repair_receives_exact_errors(tmp_path):
    _, _, Mock, _, _ = implementation()
    provider = Mock(fail_rounds=1)
    graph, repository = workflow(tmp_path, provider)
    result = await graph.generate(graph.create_session().session_id, text="First.\n\nSecond.")
    assert result.repair_attempts == 1
    assert not result.used_fallback
    assert provider.repairs
    assert any(issue.code == "MISSING_BLOCK_ID" and "blk_02" in issue.message for issue in provider.repairs[0]["issues"])
    assert result.validation_issues == []
    repository.close()


async def test_three_invalid_rounds_use_validated_fallback(tmp_path):
    _, _, Mock, _, _ = implementation()
    provider = Mock(fail_rounds=3)
    graph, repository = workflow(tmp_path, provider)
    result = await graph.generate(graph.create_session().session_id, text="First.\n\nSecond.")
    assert result.repair_attempts == 2
    assert result.used_fallback
    assert len(provider.repairs) == 4
    from bookgen.domain.validator import deterministic_validator
    assert deterministic_validator([result.option_a, result.option_b], result.input_blocks, result.input_assets) == []
    repository.close()


async def test_pending_page_cannot_be_overwritten_and_sessions_are_isolated(tmp_path):
    graph, repository = workflow(tmp_path)
    one, two = graph.create_session(), graph.create_session()
    pending = await graph.generate(one.session_id, text="Private first session.")
    with pytest.raises(ValueError, match="pending"):
        await graph.generate(one.session_id, text="Replacement.")
    with pytest.raises(KeyError):
        await graph.select(two.session_id, pending.page_id, "option_a")
    with pytest.raises(KeyError):
        await graph.snapshot("missing")
    repository.close()


async def test_retry_recovers_crash_after_snapshot_before_graph_checkpoint(tmp_path):
    graph, repository = workflow(tmp_path)
    session = graph.create_session()
    result = await graph.generate(session.session_id, text="A durable selection.")
    save = repository.save_snapshot

    def save_then_crash(session_id, page):
        save(session_id, page)
        raise RuntimeError("Process stopped before checkpoint")

    repository.save_snapshot = save_then_crash
    with pytest.raises(RuntimeError, match="before checkpoint"):
        await graph.select(session.session_id, result.page_id, "option_a")
    repository.close()
    fresh, fresh_repository = workflow(tmp_path)
    repeated = await fresh.select(session.session_id, result.page_id, "option_a")
    assert repeated.selected_option_id == "option_a"
    next_page = await fresh.generate(session.session_id, text="The following page.")
    assert next_page.page_number == 2
    assert len(fresh_repository.load_snapshots(session.session_id)) == 1
    fresh_repository.close()


async def test_invalid_structured_provider_responses_follow_bounded_fallback(tmp_path):
    _, _, Mock, _, _ = implementation()

    class InvalidProvider(Mock):
        async def generate_candidate(self, **kwargs):
            raise ValueError("Response did not match PageLayoutAST")

        async def repair_candidate(self, **kwargs):
            raise ValueError("Repair did not match PageLayoutAST")

    graph, repository = workflow(tmp_path, InvalidProvider())
    page = await graph.generate(graph.create_session().session_id, text="Original body.")
    assert page.used_fallback
    assert page.repair_attempts == 2
    assert page.input_blocks[0].text == "Original body."
    repository.close()

async def test_failed_checkpoint_can_be_reopened_and_retried(tmp_path):
    _, _, Mock, _, _ = implementation()

    class Unavailable(Mock):
        async def generate_candidate(self, **kwargs):
            raise RuntimeError("upstream unavailable")

    graph, repository = workflow(tmp_path, Unavailable())
    session = graph.create_session()
    with pytest.raises(RuntimeError, match="upstream unavailable"):
        await graph.generate(session.session_id, text="Recover this exact input.")
    repository.close()
    fresh, fresh_repository = workflow(tmp_path)
    page = await fresh.generate(session.session_id, text="Recover this exact input.")
    assert page.page_number == 1
    assert (await fresh.snapshot(session.session_id)).pending_review == page
    fresh_repository.close()

async def test_retry_identity_revision_duplicates_and_lost_response(tmp_path):
    _, _, Mock, _, _ = implementation()

    class Unavailable(Mock):
        async def generate_candidate(self, **kwargs):
            raise RuntimeError("upstream unavailable")

    graph, repository = workflow(tmp_path, Unavailable())
    session = graph.create_session().session_id
    with pytest.raises(RuntimeError):
        await graph.generate(session, page_id="durable-page", text="Original.")
    active = (await graph.snapshot(session)).active_page
    assert (active.page_id, active.text, active.asset_ids, active.page_number) == ("durable-page", "Original.", [], 1)
    graph.provider = Mock()
    with pytest.raises(ValueError, match="pending"):
        await graph.generate(session, page_id="competing-page", text="New.")
    with pytest.raises(ValueError, match="revision"):
        await graph.generate(session, page_id="durable-page", text="Edited.")
    page = await graph.generate(session, page_id="durable-page", text="Edited.", revise=True)
    assert page.page_id == "durable-page" and page.page_number == 1
    assert page.input_blocks[0].text == "Edited."
    assert await graph.generate(session, page_id="durable-page", text="Edited.") == page
    committed = await graph.select(session, page.page_id, "option_a")
    assert await graph.generate(session, page_id="durable-page", text="Edited.") == committed
    other, other_repository = workflow(tmp_path)
    duplicates = await asyncio.gather(
        graph.generate(session, page_id="second-page", text="Next."),
        other.generate(session, page_id="second-page", text="Next."),
    )
    assert duplicates[0] == duplicates[1]
    assert duplicates[0].page_number == 2
    assert len(repository.load_snapshots(session)) == 1
    other_repository.close()
    repository.close()

async def test_new_page_after_lost_commit_response_recovers_checkpoint(tmp_path):
    graph, repository = workflow(tmp_path)
    session = graph.create_session().session_id
    page = await graph.generate(session, page_id='first', text='First page.')
    save = repository.save_snapshot

    def interrupted(session_id, selected):
        save(session_id, selected)
        raise RuntimeError('lost commit response')

    repository.save_snapshot = interrupted
    with pytest.raises(RuntimeError):
        await graph.select(session, page.page_id, 'option_a')
    repository.close()
    fresh, fresh_repository = workflow(tmp_path)
    snapshot = await fresh.snapshot(session)
    assert snapshot.pending_review is None and snapshot.active_page is None
    next_page = await fresh.generate(session, page_id='second', text='Second page.')
    assert next_page.page_number == 2
    assert len(fresh_repository.load_snapshots(session)) == 1
    fresh_repository.close()
