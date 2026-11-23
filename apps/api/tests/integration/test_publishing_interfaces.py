"""Frozen publishing contracts and durable appearance; all generation uses the mock."""
from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps/api/src"))


def make_client(tmp_path):
    from bookgen.main import create_app
    from bookgen.config import load_settings
    from bookgen.adapters.llm.mock import MockLLMProvider
    settings = load_settings()
    settings.app.sqlite_uri = f"sqlite:///{tmp_path / 'publishing.db'}"
    settings.app.storage_root = tmp_path / "assets"
    return TestClient(create_app(settings=settings, provider=MockLLMProvider()))


def test_publishing_interfaces_are_registered_and_strict(tmp_path):
    with make_client(tmp_path) as api:
        paths = api.get('/openapi.json').json()['paths']
        assert '/api/v1/sessions/{session_id}/appearance' in paths, 'appearance endpoint must be registered'
        assert '/api/v1/sessions/{session_id}/compliance' in paths
        assert '/api/v1/sessions/{session_id}/compliance/decisions' in paths
        assert '/api/v1/themes/extract' in paths
        sid = api.post('/api/v1/sessions', json={}).json()['session_id']
        prefix = f'/api/v1/sessions/{sid}'
        assert api.get(prefix + '/compliance').json() == {'status': 'unavailable', 'ledger': [], 'eligible': False, 'audience_mode': 'internal', 'publishable_pages': []}
        decision = {'page_id': 'p1', 'metric_id': 'm1', 'action': 'approve'}
        assert api.post(prefix + '/compliance/decisions', json=decision).json()['status'] == 'unavailable'
        assert api.post(prefix + '/compliance/decisions', json={**decision, 'action': 'invent'}).status_code == 422
        assert api.post('/api/v1/themes/extract', json={'url': 'https://example.com'}).json() == {'status': 'unavailable', 'tokens': None}
        assert api.post('/api/v1/themes/extract', json={'url': 'https://example.com', 'extra': True}).status_code == 422
        assert api.get('/api/v1/sessions/missing/compliance').status_code == 404
        assert api.get('/api/v1/sessions/missing/appearance').status_code == 404


def test_context_and_appearance_survive_reload(tmp_path):
    from bookgen.schemas import DesignTokens, MasterChromeConfig
    context = {'title': 'Annual review', 'objective': 'Share results', 'tone_keywords': ['clear'], 'audience_mode': 'client_facing', 'page_size': 'LETTER', 'source_website_url': None}
    with make_client(tmp_path) as api:
        sid = api.post('/api/v1/sessions', json={'context': context}).json()['session_id']
        prefix = f'/api/v1/sessions/{sid}'
        original = api.get(prefix + '/appearance')
        assert original.status_code == 200, 'session appearance must be available independently of theme extraction'
        appearance = {'tokens': DesignTokens(theme_id='custom', palette_source='manual', font_heading='Georgia').model_dump(), 'chrome': MasterChromeConfig(header_left='Annual review').model_dump()}
        response = api.put(prefix + '/appearance', json=appearance)
        assert response.status_code == 200
        assert response.json() == {**appearance, 'status': 'unavailable'}
        assert api.put(prefix + '/appearance', json={**appearance, 'extra': True}).status_code == 422
    with make_client(tmp_path) as api:
        assert api.get(prefix).json()['context'] == context
        assert api.get(prefix + '/appearance').json() == {**appearance, 'status': 'unavailable'}
