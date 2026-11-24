"""Authoritative sign-off, reversible redaction, and durable source versions."""
from test_publishing_interfaces import make_client


def test_current_page_bulk_decisions_are_durable_and_leave_other_page_untouched(tmp_path):
    with make_client(tmp_path) as api:
        sid = api.post('/api/v1/sessions', json={'context': {'audience_mode': 'client_facing'}}).json()['session_id']
        prefix = f'/api/v1/sessions/{sid}'
        pages = []
        for text in ('[INTERNAL] 42% YoY and 12 employees', '[INTERNAL] 27% growth'):
            page = api.post(prefix + '/pages', json={'text': text}).json()
            api.post(prefix + f"/pages/{page['page_id']}/selection", json={'option_id': 'option_a'})
            pages.append(page)
        report = api.get(prefix + '/compliance').json()
        current = [item for item in report['ledger'] if item['page_id'] == pages[0]['page_id']]
        assert len(current) == 2
        assert all(item['source_start'] < item['source_end'] for item in current)
        for action in ('approve', 'redact'):
            for item in current:
                response = api.post(prefix + '/compliance/decisions', json={
                    'page_id': item['page_id'], 'metric_id': item['metric']['metric_id'], 'action': action})
                assert response.status_code == 200
            report = response.json()
            assert [item['decision'] for item in report['ledger']] == [action, action, None]
            assert not report['eligible']
    with make_client(tmp_path) as api:
        reopened = api.get(prefix + '/compliance').json()
        assert [item['decision'] for item in reopened['ledger']] == ['redact', 'redact', None]
        assert not reopened['eligible']


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
