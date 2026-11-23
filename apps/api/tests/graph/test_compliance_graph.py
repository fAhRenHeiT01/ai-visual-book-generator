"""Privacy spans initial fan-out, repair traces, fallback, and local review."""
from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'apps/api/src'))


@pytest.mark.parametrize('fail_rounds,fallback', [(1, False), (3, True)])
async def test_graph_masks_restricted_claims_before_all_provider_calls(tmp_path, fail_rounds, fallback):
    from bookgen.adapters.db.sqlite import SQLiteSessionRepository
    from bookgen.adapters.storage.local_fs import LocalFSStorage
    from bookgen.adapters.llm.mock import MockLLMProvider
    from bookgen.config import load_settings
    from bookgen.graph.workflow import PageWorkflow
    from bookgen.schemas import BookContext
    from bookgen.domain.validator import deterministic_validator
    provider = MockLLMProvider(fail_rounds=fail_rounds)
    repository = SQLiteSessionRepository(tmp_path / 'privacy.db')
    settings = load_settings()
    workflow = PageWorkflow(provider=provider, repository=repository, storage=LocalFSStorage(tmp_path / 'assets'), settings=settings)
    session = workflow.create_session(BookContext(audience_mode='client_facing'))
    text = '[INTERNAL] $4.2M ARR and 42% YoY\n\n[PUBLIC] 42% YoY'
    result = await workflow.generate(session.session_id, text=text)
    assert result.metrics_ledger, 'deterministic compliance scan must run before fan-out'
    for call in provider.calls:
        assert '$4.2M ARR' not in call['blocks'][0].text
        assert '42% YoY' not in call['blocks'][0].text
        assert call['blocks'][1].text == '[PUBLIC] 42% YoY'
    assert '$4.2M ARR' not in json.dumps(provider.repairs, default=str)
    assert result.input_blocks[0].text == text.split('\n\n')[0]
    assert result.used_fallback is fallback
    assert deterministic_validator([result.option_a, result.option_b], result.input_blocks, [], metrics=result.metrics_ledger, audience_mode=session.context.audience_mode) == []
    repository.close()


@pytest.mark.parametrize('strict_privacy', [True, False])
async def test_rehydrate_exact_excerpt_and_reject_restricted_stat_in_repairs(tmp_path, strict_privacy):
    from bookgen.adapters.db.sqlite import SQLiteSessionRepository
    from bookgen.adapters.storage.local_fs import LocalFSStorage
    from bookgen.adapters.llm.mock import MockLLMProvider
    from bookgen.config import load_settings
    from bookgen.graph.workflow import PageWorkflow
    from bookgen.schemas import BookContext, PlacedComponent
    class CalloutProvider(MockLLMProvider):
        def _candidate(self, **kwargs):
            result = super()._candidate(**kwargs)
            source = kwargs['blocks'][0]
            result.components.append(PlacedComponent(component_id='restricted', component_type='stat_callout', slot_id=result.components[0].slot_id, source_block_ids=[source.block_id], extracted_excerpt=source.text))
            return result
    settings = load_settings()
    settings.compliance.strict_privacy = strict_privacy
    repository = SQLiteSessionRepository(tmp_path / 'callout.db')
    provider = CalloutProvider(settings=settings)
    graph = PageWorkflow(provider=provider, repository=repository, storage=LocalFSStorage(tmp_path / 'assets'), settings=settings)
    result = await graph.generate(graph.create_session(BookContext(audience_mode='client_facing')).session_id, text='[INTERNAL] $4.2M ARR')
    assert result.used_fallback
    assert result.input_blocks[0].text == '[INTERNAL] $4.2M ARR'
    assert all(any(issue.code == 'RESTRICTED_STAT_CALLOUT' for issue in repair['issues']) for repair in provider.repairs)
    if strict_privacy:
        assert '$4.2M ARR' not in json.dumps(provider.repairs, default=str)
    else:
        assert provider.calls[0]['blocks'][0].text == '[INTERNAL] $4.2M ARR'
    repository.close()


async def test_malformed_candidate_still_reaches_bounded_fallback(tmp_path):
    from bookgen.adapters.db.sqlite import SQLiteSessionRepository
    from bookgen.adapters.storage.local_fs import LocalFSStorage
    from bookgen.adapters.llm.mock import MockLLMProvider
    from bookgen.config import load_settings
    from bookgen.graph.workflow import PageWorkflow
    class Malformed(MockLLMProvider):
        async def generate_candidate(self, **kwargs):
            return {'components': 'not a component array'}
        async def repair_candidate(self, **kwargs):
            return {'components': [None]}
    repository = SQLiteSessionRepository(tmp_path / 'malformed.db')
    graph = PageWorkflow(provider=Malformed(), repository=repository, storage=LocalFSStorage(tmp_path / 'assets'), settings=load_settings())
    result = await graph.generate(graph.create_session().session_id, text='[INTERNAL] 42%')
    assert result.used_fallback
    repository.close()
