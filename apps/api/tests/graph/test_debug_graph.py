"""Manual responses exercise the real request builder and durable graph gates."""
from pathlib import Path
import sys
import json

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps/api/src"))


def workflow(tmp_path, enabled=True):
    from bookgen.config import load_settings
    from bookgen.adapters.db.sqlite import SQLiteSessionRepository
    from bookgen.adapters.storage.local_fs import LocalFSStorage
    from bookgen.adapters.llm.mock import MockLLMProvider
    from bookgen.graph.workflow import PageWorkflow
    settings = load_settings()
    settings.app.debug_mode = enabled
    mock = MockLLMProvider(settings=settings)
    repository = SQLiteSessionRepository(tmp_path / "sessions.db")
    return PageWorkflow(repository=repository, provider=mock,
        storage=LocalFSStorage(tmp_path / "uploads"), settings=settings), mock


async def step(service, sid, snapshot, response=None):
    return await service.debugger.step(sid, checkpoint_id=snapshot.checkpoint_id, response=response)


def grouping_reply(pending):
    content = json.loads(pending.request['contents'][0]['parts'][0]['text'])
    spans = content['context']['current_page_payload']['spans']
    from bookgen.domain.grouping import deterministic_grouping
    from bookgen.schemas import SourceSpan
    return deterministic_grouping([SourceSpan.model_validate(s) for s in spans]).model_dump_json()


async def layout_request(service, sid, status):
    while not status.interrupts or status.interrupts[0].option_id == 'group_spans':
        response = grouping_reply(status.interrupts[0]) if status.interrupts else None
        status = await step(service, sid, status, response)
    return status


async def candidates(service, state):
    from bookgen.schemas import AtomicTextBlock, ImageAssetMeta, BookContext
    from bookgen.adapters.llm.context import provider_context
    from bookgen.adapters.llm.mock import MockLLMProvider
    mock = MockLLMProvider(settings=service.settings)
    blocks = [AtomicTextBlock.model_validate(b) for b in state["blocks"]]
    assets = [ImageAssetMeta.model_validate(a) for a in state["assets"]]
    with provider_context(recent_archetypes=tuple(state["rolling_layout_history"])):
        return [await mock.generate_candidate(context=BookContext(), blocks=blocks, assets=assets,
            strategy_tag=service.settings.llm.strategy_families[key]) for key in ("option_a", "option_b")]


async def test_debug_pauses_at_every_node_reopens_and_commits_only_after_approval(tmp_path):
    service, mock = workflow(tmp_path)
    sid = service.create_session().session_id
    status = await service.debugger.start(sid, text="Exact first.\n\nExact second.")
    assert status.next_nodes == ["profile"]
    assert status.state["text"] == "Exact first.\n\nExact second."
    with pytest.raises(ValueError, match="debug"):
        await service.generate(sid, text="Overwrite")
    visited = []
    replies = None
    reopened = False
    while status.status == "paused":
        if status.interrupts:
            pending = status.interrupts[0]
            if pending.event == "llm_request":
                if pending.option_id == 'group_spans':
                    assert 'Group the ordered source spans' in pending.prompt
                    status = await step(service, sid, status, grouping_reply(pending))
                    continue
                request = pending.request
                assert request["system_instruction"]
                assert request["generation_config"]["response_json_schema"]["additionalProperties"] is False
                assert "semantic_token_roles" in request["system_instruction"]
                assert "color_brand_primary" not in request["system_instruction"]
                if replies is None:
                    replies = await candidates(service, status.state)
                if not reopened:
                    checkpoint = status.checkpoint_id
                    service.repository.close()
                    service, mock = workflow(tmp_path)
                    status = await service.debugger.snapshot(sid)
                    assert status.checkpoint_id == checkpoint
                    reopened = True
                status = await step(service, sid, status, replies[int(pending.option_id == "option_b")].model_dump_json())
            else:
                status = await step(service, sid, status, "option_a")
        else:
            if status.last_node:
                visited.append(status.last_node)
            if status.next_nodes == ["commit_page"]:
                assert service.repository.load_snapshots(sid) == []
            status = await step(service, sid, status)
    assert status.last_node == "commit_page"
    assert visited == ["profile", "compliance_metrics_scan", "group_spans", "generate_candidates", "validate", "build_review", "human_review_interrupt"]
    assert status.node_input["selection"] == "option_a"
    assert status.node_output["result"]["selected_option_id"] == "option_a"
    assert [entry.node for entry in status.timeline] == [*visited, "commit_page"]
    assert status.timeline[-1].review.selected_option_id == "option_a"
    assert len(service.repository.load_snapshots(sid)) == 1
    assert mock.calls == []
    assert (await service.snapshot(sid)).pending_review is None
    second = await service.debugger.start(sid, text="Next page")
    assert second.state.get("result") is None
    service.repository.close()


async def test_manual_bad_json_runs_repairs_with_error_trace_then_bounded_fallback(tmp_path):
    service, mock = workflow(tmp_path)
    sid = service.create_session().session_id
    status = await service.debugger.start(sid, text="First.\n\nSecond.")
    requests = []
    while status.next_nodes != ["human_review_interrupt"]:
        response = None
        if status.interrupts:
            request = status.interrupts[0].request
            requests.append(request)
            response = "not JSON"
        status = await step(service, sid, status, response)
    assert len(requests) == 1 + 2 * (service.settings.llm.max_repair_retries + 1)
    assert status.state["grouping_used_fallback"]
    assert 'repair_directive' in requests[3]['contents'][0]['parts'][0]['text']
    assert 'issues' in requests[3]['contents'][0]['parts'][0]['text']
    assert status.state["repair_attempts"] == service.settings.llm.max_repair_retries
    assert status.state["used_fallback"]
    assert status.state["result"]["input_blocks"][1]["text"] == "Second."
    assert len([entry for entry in status.timeline if entry.node == "repair" and entry.status == "completed"]) == service.settings.llm.max_repair_retries
    assert any(entry.node == "validate" and entry.validation_issues for entry in status.timeline)
    assert mock.calls == []
    service.repository.close()


async def test_stale_and_wrong_resume_cannot_advance_or_overwrite(tmp_path):
    service, _ = workflow(tmp_path)
    sid = service.create_session().session_id
    first = await service.debugger.start(sid, text="Original")
    with pytest.raises(ValueError, match="response"):
        await step(service, sid, first, "unexpected")
    await step(service, sid, first)
    with pytest.raises(ValueError, match="checkpoint"):
        await step(service, sid, first)
    with pytest.raises(ValueError, match="pending"):
        await service.debugger.start(sid, text="Replacement")
    service.repository.close()


async def test_manual_identity_uses_durable_page_lock_and_timeline_survives_restart(tmp_path):
    from contextlib import asynccontextmanager
    service, mock = workflow(tmp_path)
    sid = service.create_session().session_id
    acquisitions = []
    original_lock = service._page_lock

    @asynccontextmanager
    async def tracked_lock(session_id):
        acquisitions.append(session_id)
        async with original_lock(session_id):
            yield

    service._page_lock = tracked_lock
    status = await service.debugger.start(sid, text='Original', page_id='manual-page')
    status = await step(service, sid, status)
    status = await step(service, sid, status)
    assert acquisitions == [sid, sid, sid]
    assert [entry.node for entry in status.timeline] == ['profile', 'compliance_metrics_scan', 'group_spans']
    assert status.timeline[-1].status == 'paused'
    assert status.timeline[0].node_input['text'] == 'Original'
    assert status.timeline[0].node_output['blocks'][0]['text'] == 'Original'
    assert status.state['page_id'] == 'manual-page'
    with pytest.raises(ValueError, match='pending'):
        await service.debugger.start(sid, text='Competing', page_id='different')
    assert (await service.debugger.start(sid, text='Original', page_id='manual-page')).checkpoint_id == status.checkpoint_id
    service.repository.close()
    service, _ = workflow(tmp_path)
    reopened = await service.debugger.snapshot(sid)
    assert reopened.timeline == status.timeline
    assert reopened.checkpoint_id == status.checkpoint_id
    assert mock.calls == []
    service.repository.close()


async def test_disabled_debug_is_rejected_and_environment_switch_is_supported(tmp_path, monkeypatch):
    from bookgen.config import load_settings
    service, _ = workflow(tmp_path, False)
    with pytest.raises(PermissionError):
        await service.debugger.snapshot(service.create_session().session_id)
    monkeypatch.setenv("BOOKGEN__APP__DEBUG_MODE", "true")
    assert load_settings().app.debug_mode is True
    service.repository.close()


async def test_private_request_is_masked_metadata_only_and_resume_bound_to_current_request(tmp_path):
    import json
    from io import BytesIO
    from PIL import Image
    from bookgen.domain.profiler import ImageInput, profile_content
    service, mock = workflow(tmp_path)
    service.settings.compliance.strict_privacy = True
    sid = service.create_session().session_id
    raw = BytesIO()
    Image.new('RGB', (2000, 1200)).save(raw, 'PNG')
    profile = profile_content('', [ImageInput(raw.getvalue(), filename='chart.png', alt_caption='Revenue is $4.2M ARR.')], storage=service.storage, settings=service.settings.profiling)
    def no_reads(key):
        pytest.fail(f'Layout debug must not read image storage: {key}')
    service.storage.get = no_reads
    status = await service.debugger.start(sid, text='[INTERNAL] Revenue is $4.2M ARR.', assets=profile.assets)
    status = await layout_request(service, sid, status)
    request = status.interrupts[0].request
    assert status.interrupts[0].prompt
    assert '$4.2M' not in status.interrupts[0].prompt
    assert '[METRIC_' in status.interrupts[0].prompt
    assert 'inline_data' not in status.interrupts[0].prompt
    assert 'IMAGE ATTACHMENTS' not in status.interrupts[0].prompt
    assert '$4.2M' not in json.dumps(request)
    assert '[METRIC_' in json.dumps(request)
    assert 'storage_key' not in json.dumps(request)
    assert len(request['contents'][0]['parts']) == 1
    asset = json.loads(request['contents'][0]['parts'][0]['text'])['context']['current_page_payload']['assets'][0]
    assert asset['asset_kind'] == 'chart'
    assert (asset['width_px'], asset['height_px']) == (2000, 1200)
    old = status
    status = await step(service, sid, status, '{}')
    assert status.interrupts[0].option_id == 'option_b'
    assert status.checkpoint_id != old.checkpoint_id
    with pytest.raises(ValueError, match='checkpoint'):
        await step(service, sid, old, '{}')
    # Disabling debug must never allow the regular API to overwrite a manual pause.
    service.settings.app.debug_mode = False
    with pytest.raises(ValueError, match='pending'):
        await service.generate(sid, text='Overwrite')
    assert mock.calls == []
    service.repository.close()


async def test_semantically_invalid_manual_layout_reaches_validator_and_repair(tmp_path):
    import json
    service, _ = workflow(tmp_path)
    sid = service.create_session().session_id
    status = await service.debugger.start(sid, text='First.\n\nSecond.')
    replies = None
    while status.next_nodes != ['repair']:
        response = None
        if status.interrupts:
            if status.interrupts[0].option_id == 'group_spans':
                status = await step(service, sid, status, grouping_reply(status.interrupts[0]))
                continue
            replies = replies or await candidates(service, status.state)
            index = int(status.interrupts[0].option_id == 'option_b')
            raw = replies[index].model_dump(mode='json')
            raw['components'] = [c for c in raw['components'] if 'blk_02' not in c['source_block_ids']]
            response = json.dumps(raw)
        status = await step(service, sid, status, response)
    assert any(issue['code'] == 'MISSING_BLOCK_ID' for issue in status.state['validation_issues'])
    status = await step(service, sid, status)
    assert 'MISSING_BLOCK_ID' in json.dumps(status.interrupts[0].request)
    from bookgen.config.llm import load_prompts
    assert load_prompts()['critic_repair'].text.strip() in status.interrupts[0].prompt
    assert 'MISSING_BLOCK_ID' in status.interrupts[0].prompt
    service.repository.close()


async def test_chat_prompt_contains_actual_instructions_context_and_schema_without_sdk_envelope(tmp_path):
    import json
    from bookgen.config.llm import load_prompts
    service, mock = workflow(tmp_path)
    sid = service.create_session().session_id
    text = 'Exact source with {theme_role} and café.'
    status = await service.debugger.start(sid, text=text)
    status = await layout_request(service, sid, status)
    pending = status.interrupts[0]
    assert pending.prompt, 'The LLM interrupt must expose a directly copyable chat prompt'
    prompts = load_prompts()
    assert prompts['system_art_director'].text.strip() in pending.prompt
    assert prompts['strategy_option_a'].text.strip() in pending.prompt
    assert text in pending.prompt
    assert 'semantic_token_roles' in pending.prompt
    assert json.dumps(pending.request['generation_config']['response_json_schema'], indent=2, ensure_ascii=False) in pending.prompt
    assert 'system_instruction' not in pending.prompt
    assert 'transport_mode' not in pending.prompt
    assert 'images' not in pending.model_dump()
    assert mock.calls == []
    original = pending.prompt
    service.repository.close()
    service, _ = workflow(tmp_path)
    assert (await service.debugger.snapshot(sid)).interrupts[0].prompt == original
    service.repository.close()


@pytest.mark.parametrize('has_prompt', [False, True])
async def test_existing_sdk_only_interrupt_is_presented_as_chat_prompt_after_upgrade(tmp_path, monkeypatch, has_prompt):
    import json
    from hashlib import sha256
    from io import BytesIO
    from PIL import Image
    from langgraph.types import interrupt
    from bookgen.adapters.llm.manual import ManualLLMProvider
    from bookgen.domain.profiler import ImageInput, profile_content
    service, _ = workflow(tmp_path)
    sid = service.create_session().session_id

    async def old_transport(self, request):
        if request.get('operation') == 'group_spans':
            from bookgen.domain.grouping import deterministic_grouping
            from bookgen.schemas import SourceSpan
            return deterministic_grouping([SourceSpan.model_validate(s) for s in request['context']['current_page_payload']['spans']])
        payload = self.api_payload(request)
        content = json.loads(payload['contents'][0]['parts'][0]['text'])
        asset = content['context']['current_page_payload']['assets'][0]
        asset.update(storage_key='C:/private/LEGACY_BINARY_SENTINEL.png', thumbnail_key='https://private/LEGACY_BINARY_SENTINEL.png',
            inline_data={'data': 'LEGACY_BINARY_SENTINEL'})
        for field in ('width_px', 'height_px', 'estimated_dpi'):
            asset.pop(field, None)
        payload['contents'][0]['parts'][0]['text'] = json.dumps(content)
        payload['contents'][0]['parts'].append({'inline_data': {'mime_type': 'image/png', 'data': 'LEGACY_BINARY_SENTINEL'}})
        payload['contents'][0]['parts'].append({'file_data': {'file_uri': 'https://private/LEGACY_BINARY_SENTINEL.png'}})
        pending = {'event': 'llm_request', 'option_id': 'option_a', 'request': payload,
            'prompt': 'IMAGE ATTACHMENTS: attach LEGACY_BINARY_SENTINEL',
            'images': [{'asset_id': 'img_01', 'mime_type': 'image/png', 'data': 'LEGACY_BINARY_SENTINEL'}]}
        if not has_prompt:
            pending.pop('prompt')
        return interrupt(pending)

    raw = BytesIO()
    Image.new('RGB', (2000, 1200)).save(raw, 'PNG')
    assets = profile_content('', [ImageInput(raw.getvalue(), filename='chart.png')], storage=service.storage).assets
    with monkeypatch.context() as patch:
        patch.setattr(ManualLLMProvider, '_manual_transport', old_transport)
        status = await service.debugger.start(sid, text='Existing paused source.', assets=assets)
        status = await layout_request(service, sid, status)
    async with service._graph(manual_debug=True) as graph:
        checkpoint = await graph.aget_state(service._config(sid))
        original_interrupts = [item.value for task in checkpoint.tasks for item in task.interrupts]
        identity = sha256(json.dumps([checkpoint.config['configurable']['checkpoint_id'], original_interrupts], sort_keys=True).encode()).hexdigest()
        assert 'LEGACY_BINARY_SENTINEL' in json.dumps(original_interrupts)
    service.repository.close()
    service, _ = workflow(tmp_path)
    status = await service.debugger.snapshot(sid)
    assert status.checkpoint_id == identity
    assert 'LEGACY_BINARY_SENTINEL' not in status.model_dump_json()
    assert 'IMAGE ATTACHMENTS' not in status.interrupts[0].prompt
    assert '"width_px": 2000' in status.interrupts[0].prompt
    assert status.interrupts[0].prompt
    assert 'Existing paused source.' in status.interrupts[0].prompt
    resumed = await step(service, sid, status, '{}')
    assert resumed.interrupts[0].option_id == 'option_b'
    assert resumed.interrupts[0].prompt
    with pytest.raises(ValueError, match='checkpoint'):
        await step(service, sid, status, '{}')
    resumed = await step(service, sid, resumed, '{}')
    assert resumed.last_node == 'generate_candidates'
    assert len(resumed.node_output['llm_exchanges']) == 2
    assert 'LEGACY_BINARY_SENTINEL' not in resumed.model_dump_json()
    # Completed older nodes can contain recorded exchanges as well as paused
    # interrupts. Presentation must project those without rewriting persistence.
    exchange = {**original_interrupts[0], 'response': '{}'}
    exchange.pop('event')
    async with service._graph(manual_debug=True) as graph:
        await graph.aupdate_state(service._config(sid), {'debug_exchanges': [exchange]})
    recorded = await service.debugger.snapshot(sid)
    assert 'LEGACY_BINARY_SENTINEL' not in recorded.model_dump_json()
    assert '"width_px": 2000' in recorded.node_output['llm_exchanges'][0]['prompt']
    async with service._graph(manual_debug=True) as graph:
        assert 'LEGACY_BINARY_SENTINEL' in json.dumps((await graph.aget_state(service._config(sid))).values['debug_exchanges'])
    service.repository.close()


async def test_checkpoint_with_an_older_string_resume_can_finish_the_node(tmp_path):
    from langgraph.types import Command

    service, mock = workflow(tmp_path)
    sid = service.create_session().session_id
    status = await service.debugger.start(sid, text='Previously submitted source.')
    status = await layout_request(service, sid, status)
    # Earlier releases persisted just the raw reply as the resume value for A.
    async with service._graph(manual_debug=True) as graph:
        await graph.ainvoke(Command(resume='{}'), service._config(sid))
    service.repository.close()
    service, mock = workflow(tmp_path)
    status = await service.debugger.snapshot(sid)
    assert status.interrupts[0].option_id == 'option_b'
    status = await step(service, sid, status, '{}')
    assert status.last_node == 'generate_candidates'
    assert [item['response'] for item in status.node_output['llm_exchanges']] == ['{}', '{}']
    assert mock.calls == []
    service.repository.close()


async def test_resumed_response_keeps_the_prompt_and_payload_the_user_copied(tmp_path, monkeypatch):
    """Node replay must not relabel an earlier reply with changed instructions."""
    from bookgen.adapters.llm import gemini

    service, mock = workflow(tmp_path)
    sid = service.create_session().session_id
    status = await service.debugger.start(sid, text='Exact source with {braces} and caf\u00e9.')
    status = await layout_request(service, sid, status)
    original = status.interrupts[0]
    service.repository.close()

    load_prompts = gemini.load_prompts

    def revised_prompts():
        prompts = load_prompts()
        prompts['system_art_director'] = prompts['system_art_director'].model_copy(
            update={'text': prompts['system_art_director'].text + '\nUpdated after restart.'})
        return prompts

    monkeypatch.setattr(gemini, 'load_prompts', revised_prompts)
    service, mock = workflow(tmp_path)
    status = await service.debugger.snapshot(sid)
    assert status.interrupts[0].prompt == original.prompt
    assert status.interrupts[0].request == original.request
    status = await step(service, sid, status, '{}')
    second = status.interrupts[0]
    assert 'Updated after restart.' in second.prompt
    status = await step(service, sid, status, '{}')
    exchanges = status.node_output['llm_exchanges']
    assert exchanges[0]['request'] == original.request
    assert exchanges[0]['prompt'] == original.prompt
    assert exchanges[0]['response'] == '{}'
    assert exchanges[1]['request'] == second.request
    assert exchanges[1]['prompt'] == second.prompt
    assert mock.calls == []
    service.repository.close()


async def test_manual_grouping_interrupt_reopens_and_persists_before_a_b(tmp_path):
    service, mock = workflow(tmp_path)
    sid = service.create_session().session_id
    text = '[INTERNAL] Customers say \u201cCaf\u00e9 works.\u201d Revenue grew 42%.'
    status = await service.debugger.start(sid, text=text)
    assert status.next_nodes == ['profile']
    status = await step(service, sid, status)
    status = await step(service, sid, status)
    assert status.next_nodes == ['group_spans']
    assert status.state.get('source_grouping') is None
    status = await step(service, sid, status)
    pending = status.interrupts[0]
    assert pending.option_id == 'group_spans'
    assert '42%' not in pending.prompt
    assert '[METRIC_' in pending.prompt
    content = json.loads(pending.request['contents'][0]['parts'][0]['text'])
    assert content['context']['current_page_payload']['assets'] == []
    spans = content['context']['current_page_payload']['spans']
    assert [s['span_id'] for s in spans] == ['span_0001', 'span_0002']
    assert pending.request['generation_config']['response_json_schema']['title'] == 'SourceGrouping'
    service.repository.close()
    service, mock = workflow(tmp_path)
    reopened = await service.debugger.snapshot(sid)
    assert reopened.checkpoint_id == status.checkpoint_id
    assert reopened.interrupts[0] == pending
    response = json.dumps({'groups': [
        {'span_ids': ['span_0001'], 'role': 'quote'},
        {'span_ids': ['span_0002'], 'role': 'metric'},
    ]})
    status = await step(service, sid, reopened, response)
    assert status.last_node == 'group_spans'
    assert status.next_nodes == ['generate_candidates']
    assert not status.state['grouping_used_fallback']
    assert [b['kind'] for b in status.state['blocks']] == ['quote', 'metric']
    assert ''.join(b['text'] for b in status.state['blocks']) == text
    assert status.state['metrics_ledger'][0]['classification'] == 'internal'
    assert status.node_output['llm_exchanges'][0]['request'] == pending.request
    assert status.node_output['llm_exchanges'][0]['response'] == response
    with pytest.raises(ValueError, match='checkpoint'):
        await step(service, sid, reopened, response)
    replies = await candidates(service, status.state)
    status = await step(service, sid, status)
    for index in range(2):
        assert status.interrupts[0].option_id == ('option_a' if index == 0 else 'option_b')
        layout = json.loads(status.interrupts[0].request['contents'][0]['parts'][0]['text'])
        assert [b['kind'] for b in layout['context']['current_page_payload']['blocks']] == ['quote', 'metric']
        status = await step(service, sid, status, replies[index].model_dump_json())
    assert status.last_node == 'generate_candidates'
    assert status.state['source_grouping'] == json.loads(response)
    assert mock.calls == []
    service.repository.close()
