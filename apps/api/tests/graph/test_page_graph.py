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


async def test_source_grouping_is_shared_exact_role_slices_before_both_options(tmp_path):
    _, _, Mock, _, _ = implementation()

    class SemanticGrouping(Mock):
        async def group_spans(self, *, spans):
            self.grouping_calls.append(spans)
            return {"groups": [
                {"span_ids": [spans[0].span_id], "role": "quote"},
                {"span_ids": [spans[1].span_id], "role": "metric"},
            ]}

    provider = SemanticGrouping()
    graph, repository = workflow(tmp_path, provider)
    graph.settings.compliance.strict_privacy = False
    text = 'Our customers say \u201cIt changed our work.\u201d Revenue increased 42%.'
    page = await graph.generate(graph.create_session().session_id, text=text)
    assert [(b.kind, b.text) for b in page.input_blocks] == [
        ('quote', 'Our customers say \u201cIt changed our work.\u201d '),
        ('metric', 'Revenue increased 42%.'),
    ]
    assert len(provider.grouping_calls) == 1
    assert provider.calls[0]['blocks'] == provider.calls[1]['blocks'] == page.input_blocks
    assert ''.join(b.text for b in page.input_blocks) == text
    for option in (page.option_a, page.option_b):
        assert {i for c in option.components for i in c.source_block_ids} == {b.block_id for b in page.input_blocks}
    repository.close()


@pytest.mark.parametrize('invalid', ['not JSON', {'groups': []}, RuntimeError('grouping unavailable')])
async def test_unusable_grouping_falls_back_once_and_repairs_share_blocks(tmp_path, invalid):
    _, _, Mock, _, _ = implementation()

    class InvalidGrouping(Mock):
        async def group_spans(self, *, spans):
            self.grouping_calls.append(spans)
            if isinstance(invalid, Exception):
                raise invalid
            return invalid

    provider = InvalidGrouping(fail_rounds=1)
    graph, repository = workflow(tmp_path, provider)
    page = await graph.generate(graph.create_session().session_id, text='First.\n\nSecond.')
    assert len(provider.grouping_calls) == 1
    assert page.repair_attempts == 1
    assert [b.text for b in page.input_blocks] == ['First.', 'Second.']
    assert all(call['blocks'] == page.input_blocks for call in provider.calls)
    repository.close()


async def test_completed_grouping_survives_candidate_failure_restart_and_legacy_page(tmp_path):
    _, _, Mock, _, _ = implementation()

    class Interrupted(Mock):
        async def generate_candidate(self, **kwargs):
            raise RuntimeError('interrupted after grouping')

    original = Interrupted()
    graph, repository = workflow(tmp_path, original)
    sid = graph.create_session().session_id
    with pytest.raises(RuntimeError, match='after grouping'):
        await graph.generate(sid, page_id='stable', text='Repeated. Repeated.')
    async with graph._graph() as compiled:
        before = (await compiled.aget_state(graph._config(sid))).values
    assert before['source_grouping']
    assert len(original.grouping_calls) == 1
    repository.close()
    provider = Mock()
    fresh, repository = workflow(tmp_path, provider)
    page = await fresh.generate(sid, page_id='stable', text='Repeated. Repeated.')
    assert provider.grouping_calls == []
    assert page.input_blocks[0].source_span_ids == ['span_0001', 'span_0002']
    # Old snapshots retain arbitrary previously assigned pointer IDs.
    legacy = page.model_copy(deep=True)
    legacy.page_id = 'legacy'
    legacy.input_blocks[0].block_id = 'original_saved_pointer'
    for option in (legacy.option_a, legacy.option_b):
        option.components[0].source_block_ids = ['original_saved_pointer']
    legacy.selected_option_id = 'option_a'
    repository.save_snapshot(sid, legacy)
    restored = repository.load_snapshots(sid)[0]
    assert restored.input_blocks[0].block_id == restored.option_a.components[0].source_block_ids[0]
    repository.close()


@pytest.mark.parametrize('limit', ['max_spans', 'max_input_chars'])
async def test_grouping_limits_keep_provider_context_bounded(tmp_path, limit):
    _, _, Mock, _, _ = implementation()
    provider = Mock()
    graph, repository = workflow(tmp_path, provider)
    setattr(graph.settings.profiling.grouping, limit, 1)
    page = await graph.generate(graph.create_session().session_id, text='First. Second.')
    assert provider.grouping_calls == []
    assert page.input_blocks[0].text == 'First. Second.'
    repository.close()


async def test_private_grouping_keeps_restricted_metrics_and_exact_excerpts(tmp_path):
    from bookgen.schemas import BookContext, AudienceMode, ComponentType, MetricClassification
    from bookgen.domain.compliance import compliance_report
    _, _, Mock, _, _ = implementation()

    class SplitAndPromote(Mock):
        async def group_spans(self, *, spans):
            self.grouping_calls.append(spans)
            return {'groups': [{'span_ids': [s.span_id], 'role': 'quote' if i == 0 else 'metric'} for i, s in enumerate(spans)]}

        def _candidate(self, **kwargs):
            page = super()._candidate(**kwargs)
            quote = page.components[0].model_copy(deep=True)
            quote.component_id = 'quote'
            quote.component_type = ComponentType.PULL_QUOTE
            quote.extracted_excerpt = 'caf\u00e9 works invented' if not self.repairs else 'caf\u00e9 works.'
            page.components.append(quote)
            # Split metric is still forbidden as a client-facing callout.
            if not self.repairs:
                metric = page.components[1].model_copy(deep=True)
                metric.component_id = 'metric'
                metric.component_type = ComponentType.STAT_CALLOUT
                metric.extracted_excerpt = kwargs['blocks'][1].text.strip()
                page.components.append(metric)
            return page

    provider = SplitAndPromote()
    graph, repository = workflow(tmp_path, provider)
    sid = graph.create_session(BookContext(audience_mode=AudienceMode.CLIENT_FACING)).session_id
    text = '[INTERNAL] Customers say caf\u00e9 works. Revenue grew 42%.'
    page = await graph.generate(sid, text=text)
    assert '42%' not in str(provider.grouping_calls[0])
    assert '[METRIC_' in str(provider.grouping_calls[0])
    assert page.metrics_ledger[0].classification == MetricClassification.INTERNAL
    assert any(i.code == 'HALLUCINATED_EXCERPT' for repair in provider.repairs for i in repair['issues'])
    assert any(i.code == 'RESTRICTED_STAT_CALLOUT' for repair in provider.repairs for i in repair['issues'])
    assert page.option_a.components[-1].extracted_excerpt == 'caf\u00e9 works.'
    assert page.option_a.components[-1].extracted_excerpt in page.input_blocks[0].text
    await graph.select(sid, page.page_id, 'option_a')
    report = compliance_report(await graph.snapshot(sid), config=graph.settings.compliance)
    assert report.ledger[0].metric.classification == MetricClassification.INTERNAL
    assert not report.eligible
    repository.close()

@pytest.mark.parametrize('objective,tone,audience,expected', [
    ('Launch a campaign', [], 'internal', 'campaign_presentation'),
    ('Financial analysis', [], 'internal', 'consulting_report'),
    ('Tell our story', [], 'client_facing', 'brand_led_editorial'),
    ('', ['bold'], 'internal', 'campaign_presentation'),
    ('', [], 'client_facing', 'consulting_report'),
    ('', [], 'internal', 'brand_led_editorial'),
])
def test_auto_direction_uses_yaml_intent_rules_once(objective, tone, audience, expected):
    from bookgen.domain.direction import resolve_direction
    from bookgen.schemas import BookContext
    context = resolve_direction(BookContext(objective=objective, tone_keywords=tone, audience_mode=audience))
    assert context.direction == 'auto'
    assert context.resolved_direction == expected
    changed = context.model_copy(update={'objective': 'Launch campaign', 'tone_keywords': []})
    assert resolve_direction(changed).resolved_direction == expected


@pytest.mark.parametrize('direction', ['brand_led_editorial', 'consulting_report', 'campaign_presentation'])
async def test_explicit_direction_persists_apart_from_appearance_and_page_size(tmp_path, direction):
    from bookgen.schemas import BookContext, PageSize
    graph, repository = workflow(tmp_path)
    session = graph.create_session(BookContext(direction=direction, objective='Launch campaign', page_size=PageSize.US_LETTER))
    assert session.context.resolved_direction == direction
    appearance = repository.load_appearance(session.session_id)
    repository.save_appearance(session.session_id, appearance.model_copy(update={'tokens': appearance.tokens.model_copy(update={'theme_id': 'another'})}))
    context = repository.load_context(session.session_id)
    assert context.direction == context.resolved_direction == direction
    assert context.page_size == PageSize.US_LETTER
    page = await graph.generate(session.session_id, text='# Heading\n\n- One.\n- Two.')
    assert page.option_a.surface_treatment != page.option_b.surface_treatment
    assert any(c.component_type == 'heading' for c in page.option_a.components)
    assert any(c.component_type == 'bullet_list' for c in page.option_b.components)
    repository.close()


async def test_protected_chart_is_checked_on_initial_and_repaired_candidates(tmp_path):
    from bookgen.schemas import ImageAssetMeta
    _, _, Mock, _, _ = implementation()
    class Cropping(Mock):
        def _candidate(self, **kwargs):
            page = super()._candidate(**kwargs)
            for component in page.components:
                if component.source_asset_id:
                    component.object_fit = 'cover'
            return page
    provider = Cropping()
    graph, repository = workflow(tmp_path, provider)
    chart = ImageAssetMeta(asset_id='chart', storage_key='local', mime_type='image/png', width_px=900, height_px=450, aspect_ratio=2, asset_kind='chart')
    page = await graph.generate(graph.create_session().session_id, text='# Evidence\n\nOriginal copy.', assets=[chart])
    assert page.used_fallback and page.repair_attempts == 2
    assert len(provider.repairs) == 4
    assert all(any(i.code == 'CHART_CROP_FORBIDDEN' for i in repair['issues']) for repair in provider.repairs)
    assert all(c.object_fit == 'contain' for p in (page.option_a, page.option_b) for c in p.components if c.source_asset_id)
    repository.close()

async def test_generation_manual_and_repair_share_named_vocabulary_and_bounded_facts():
    from bookgen.adapters.llm.gemini import GeminiProvider
    from bookgen.adapters.llm.manual import ManualLLMProvider
    from bookgen.adapters.llm.context import provider_context
    from bookgen.config import load_settings
    from bookgen.domain.fallback import safe_fallback_builder
    from bookgen.schemas import AtomicTextBlock, BookContext
    settings = load_settings()
    blocks = [AtomicTextBlock(block_id='heading', kind='heading', text='Original heading', word_count=2, char_count=16)]
    pair = safe_fallback_builder(blocks, [])
    requests = []
    async def transport(request):
        requests.append(request)
        return pair[0]
    provider = GeminiProvider(storage=None, settings=settings, transport=transport)
    manual = ManualLLMProvider(storage=None, settings=settings)
    history = tuple({'page_num': n, 'archetype': 'minimalist_swiss', 'density_class': 'normal', 'has_callout': False, 'unbounded_text': 'Never send this'} for n in range(500))
    kwargs = dict(context=BookContext(direction='campaign_presentation'), blocks=blocks, assets=[], strategy_tag=settings.llm.strategy_families['option_a'])
    with provider_context(page_number=501, rhythm_history=history):
        await provider.generate_candidate(**kwargs)
        await provider.repair_candidate(**kwargs, candidate=pair[0], issues=[])
        manual_request = manual._request(**kwargs)
    for request in [*requests, manual_request]:
        page = request['context']['current_page_payload']
        assert page['art_direction']['direction'] == 'campaign_presentation'
        assert page['art_direction']['semantic_groups'] == [{'block_id': 'heading', 'role': 'heading', 'word_count': 2, 'char_count': 16}]
        assert page['art_direction']['eligible_treatments']
        assert 'unbounded_text' not in str(request)
        assert len(request['context']['sliding_rhythm_window']['pages']) == settings.llm.rhythm_window
        assert 'composition' in request['response_schema'].model_fields
    assert requests[0]['context'] == requests[1]['context'] == manual_request['context']
    chat = manual.chat_input(manual.api_payload(manual_request))['prompt']
    assert 'surface_treatment' in chat and 'semantic_groups' in chat
    assert 'named treatments' in requests[1]['repair_directive']
