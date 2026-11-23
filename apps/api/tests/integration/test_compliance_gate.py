"""Authoritative sign-off, reversible redaction, and durable source versions."""
from test_publishing_interfaces import make_client


def test_locked_approved_redacted_reopened_and_source_preserved(tmp_path):
    from bookgen.domain.compliance import require_export_approval
    from bookgen.routes.sessions import workflow
    import pytest
    with make_client(tmp_path) as api:
        sid = api.post('/api/v1/sessions', json={'context': {'audience_mode': 'client_facing'}}).json()['session_id']
        prefix = f'/api/v1/sessions/{sid}'
        page = api.post(prefix + '/pages', json={'text': '[INTERNAL] $4.2M ARR'}).json()
        api.post(prefix + f"/pages/{page['page_id']}/selection", json={'option_id': 'option_a'})
        report = api.get(prefix + '/compliance').json()
        assert report['status'] == 'available'
        assert not report['eligible']
        service = api.app.state.get_workflow()
        snapshot = api.portal.call(service.snapshot, sid)
        with pytest.raises(PermissionError):
            require_export_approval(snapshot, decisions={}, config=service.settings.compliance)
        decision = {'page_id': page['page_id'], 'metric_id': report['ledger'][0]['metric']['metric_id'], 'action': 'approve'}
        approved = api.post(prefix + '/compliance/decisions', json=decision).json()
        assert approved['eligible']
        assert approved['ledger'][0]['metric']['approved_for_export']
        assert '$4.2M ARR' in approved['publishable_pages'][0]['input_blocks'][0]['text']
        redacted = api.post(prefix + '/compliance/decisions', json={**decision, 'action': 'redact'}).json()
        assert redacted['eligible']
        assert '$4.2M ARR' not in str(redacted['publishable_pages'])
        assert api.get(prefix).json()['committed_pages'][0]['input_blocks'][0]['text'] == '[INTERNAL] $4.2M ARR'
        changed = api.post(prefix + '/pages', json={'text': '[INTERNAL] Changed $4.2M ARR'}).json()
        api.post(prefix + f"/pages/{changed['page_id']}/selection", json={'option_id': 'option_a'})
        assert not api.get(prefix + '/compliance').json()['eligible']
        assert api.post(prefix + '/compliance/decisions', json={**decision, 'page_id': changed['page_id']}).status_code == 409
    with make_client(tmp_path) as api:
        report = api.get(prefix + '/compliance').json()
        assert report['ledger'][0]['decision'] == 'redact'
        assert not report['eligible']


def test_internal_policy_and_unknown_decisions(tmp_path):
    with make_client(tmp_path) as api:
        sid = api.post('/api/v1/sessions', json={}).json()['session_id']
        prefix = f'/api/v1/sessions/{sid}'
        page = api.post(prefix + '/pages', json={'text': '[DRAFT] 42% YoY'}).json()
        assert not api.get(prefix + '/compliance').json()['eligible']
        api.post(prefix + f"/pages/{page['page_id']}/selection", json={'option_id': 'option_a'})
        assert api.get(prefix + '/compliance').json()['eligible']
        assert api.post(prefix + '/compliance/decisions', json={'page_id': 'missing', 'metric_id': 'missing', 'action': 'approve'}).status_code == 409
