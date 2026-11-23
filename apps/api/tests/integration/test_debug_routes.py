"""Debug endpoints are opt-in and reject malformed or stale actions."""
from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps/api/src"))


def client(tmp_path, enabled=True):
    from bookgen.main import create_app
    from bookgen.config import load_settings
    from bookgen.adapters.llm.mock import MockLLMProvider
    config = load_settings()
    config.app.debug_mode = enabled
    config.app.sqlite_uri = f"sqlite:///{tmp_path / 'sessions.db'}"
    config.app.storage_root = tmp_path / 'assets'
    return TestClient(create_app(settings=config, provider=MockLLMProvider(settings=config)))


def test_debug_api_start_inspect_step_and_conflicts(tmp_path):
    with client(tmp_path) as api:
        created = api.post('/api/v1/sessions', json={}).json()
        assert created['debug_enabled'] is True
        sid = created['session_id']
        prefix = f'/api/v1/sessions/{sid}'
        assert api.get(prefix).json()['debug_enabled'] is True
        assert api.get(prefix + '/debug').json()['status'] == 'idle'
        assert api.post(prefix + '/debug/pages', json={'text': 'Body', 'asset_ids': ['unknown']}).status_code == 422
        started = api.post(prefix + '/debug/pages', json={'text': 'Body'})
        assert started.status_code == 201
        status = started.json()
        assert status['appearance']['tokens']['color_brand_primary']
        assert status['appearance'] == api.get(prefix + '/appearance').json()
        assert api.post(prefix + '/pages', json={'text': 'Body'}).status_code == 409
        assert api.post(prefix + '/debug/step', json={'checkpoint_id': status['checkpoint_id'], 'extra': 1}).status_code == 422
        body = {'checkpoint_id': status['checkpoint_id']}
        assert api.post(prefix + '/debug/step', json=body).json()['last_node'] == 'profile'
        assert api.post(prefix + '/debug/step', json=body).status_code == 409
        assert api.get('/api/v1/sessions/missing/debug').status_code == 404
        status = api.get(prefix + '/debug').json()
        while not status['interrupts']:
            status = api.post(prefix + '/debug/step', json={'checkpoint_id': status['checkpoint_id']}).json()
        pending = status['interrupts'][0]
        assert 'You are the book\'s art director' in pending['prompt']
        assert 'Body' in pending['prompt']
        assert 'semantic_token_roles' in pending['prompt']
        assert pending['images'] == []


def test_debug_api_disabled_by_default(tmp_path):
    with client(tmp_path, False) as api:
        sid = api.post('/api/v1/sessions', json={}).json()['session_id']
        prefix = f'/api/v1/sessions/{sid}/debug'
        assert api.get(prefix).status_code == 403
        assert api.post(prefix + '/pages', json={'text': 'Body'}).status_code == 403
        assert api.post(prefix + '/step', json={'checkpoint_id': 'stale'}).status_code == 403
