"""Manual responses exercise the real request builder and durable graph gates."""
from pathlib import Path
import sys

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
    assert visited == ["profile", "compliance_metrics_scan", "generate_candidates", "validate", "build_review", "human_review_interrupt"]
    assert status.node_input["selection"] == "option_a"
    assert status.node_output["result"]["selected_option_id"] == "option_a"
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
    assert len(requests) == 2 * (service.settings.llm.max_repair_retries + 1)
    assert 'repair_directive' in requests[2]['contents'][0]['parts'][0]['text']
    assert 'issues' in requests[2]['contents'][0]['parts'][0]['text']
    assert status.state["repair_attempts"] == service.settings.llm.max_repair_retries
    assert status.state["used_fallback"]
    assert status.state["result"]["input_blocks"][1]["text"] == "Second."
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


async def test_disabled_debug_is_rejected_and_environment_switch_is_supported(tmp_path, monkeypatch):
    from bookgen.config import load_settings
    service, _ = workflow(tmp_path, False)
    with pytest.raises(PermissionError):
        await service.debugger.snapshot(service.create_session().session_id)
    monkeypatch.setenv("BOOKGEN__APP__DEBUG_MODE", "true")
    assert load_settings().app.debug_mode is True
    service.repository.close()


async def test_private_request_is_masked_thumbnails_bounded_and_resume_bound_to_current_request(tmp_path):
    import base64
    import json
    from io import BytesIO
    from PIL import Image
    from bookgen.domain.profiler import ImageInput, profile_content
    service, mock = workflow(tmp_path)
    service.settings.compliance.strict_privacy = True
    sid = service.create_session().session_id
    raw = BytesIO()
    Image.new('RGB', (2000, 1200)).save(raw, 'PNG')
    profile = profile_content('', [ImageInput(raw.getvalue(), filename='chart.png')], storage=service.storage, settings=service.settings.profiling)
    status = await service.debugger.start(sid, text='[INTERNAL] Revenue is $4.2M ARR.', assets=profile.assets)
    while not status.interrupts:
        status = await step(service, sid, status)
    request = status.interrupts[0].request
    assert status.interrupts[0].prompt
    assert '$4.2M' not in status.interrupts[0].prompt
    assert '[METRIC_' in status.interrupts[0].prompt
    attachment = status.interrupts[0].images[0]
    assert attachment.asset_id == profile.assets[0].asset_id
    assert attachment.data not in status.interrupts[0].prompt
    assert 'inline_data' not in status.interrupts[0].prompt
    with Image.open(BytesIO(base64.b64decode(attachment.data))) as preview:
        assert max(preview.size) <= 768
    assert '$4.2M' not in json.dumps(request)
    assert '[METRIC_' in json.dumps(request)
    assert 'storage_key' not in json.dumps(request)
    inline = request['contents'][0]['parts'][1]['inline_data']
    with Image.open(BytesIO(base64.b64decode(inline['data']))) as image:
        assert max(image.size) <= 768
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
    while not status.interrupts:
        status = await step(service, sid, status)
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
    assert pending.images == []
    assert mock.calls == []
    original = pending.prompt
    service.repository.close()
    service, _ = workflow(tmp_path)
    assert (await service.debugger.snapshot(sid)).interrupts[0].prompt == original
    service.repository.close()


async def test_existing_sdk_only_interrupt_is_presented_as_chat_prompt_after_upgrade(tmp_path, monkeypatch):
    from langgraph.types import interrupt
    from bookgen.adapters.llm.manual import ManualLLMProvider
    service, _ = workflow(tmp_path)
    sid = service.create_session().session_id

    async def old_transport(self, request):
        return interrupt({'event': 'llm_request', 'option_id': 'option_a', 'request': self.api_payload(request)})

    with monkeypatch.context() as patch:
        patch.setattr(ManualLLMProvider, '_manual_transport', old_transport)
        status = await service.debugger.start(sid, text='Existing paused source.')
        while not status.interrupts:
            status = await step(service, sid, status)
    service.repository.close()
    service, _ = workflow(tmp_path)
    status = await service.debugger.snapshot(sid)
    assert status.interrupts[0].prompt
    assert 'Existing paused source.' in status.interrupts[0].prompt
    resumed = await step(service, sid, status, '{}')
    assert resumed.interrupts[0].option_id == 'option_b'
    assert resumed.interrupts[0].prompt
    service.repository.close()
