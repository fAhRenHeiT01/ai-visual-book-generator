"""Frozen theme routes activate extraction and persist a locked sanitized appearance."""
from test_publishing_interfaces import make_client


def test_extract_failure_is_offline_and_nonfatal(tmp_path, monkeypatch):
    from bookgen.routes import theme
    class FailedFetcher:
        def __init__(self, settings):
            pass
        def fetch(self, url):
            raise ValueError('Blocked destination')
    monkeypatch.setattr(theme, 'ThemeFetcher', FailedFetcher, raising=False)
    with make_client(tmp_path) as api:
        assert api.post('/api/v1/themes/extract', json={'url': 'https://brand.example'}).json() == {'status': 'unavailable', 'tokens': None}


def test_extract_public_fixture(tmp_path, monkeypatch):
    from bookgen.routes import theme
    class FixtureFetcher:
        def __init__(self, settings):
            pass
        def fetch(self, url):
            from bookgen.adapters.http.theme_fetcher import FetchResponse
            return FetchResponse(200, {}, b'<meta name="theme-color" content="#123456">')
    monkeypatch.setattr(theme, 'ThemeFetcher', FixtureFetcher, raising=False)
    with make_client(tmp_path) as api:
        body = api.post('/api/v1/themes/extract', json={'url': 'https://brand.example'}).json()
        assert body['status'] == 'available', 'public website palette must be available'
        assert body['tokens']['color_brand_primary'] == '#123456'


def test_preset_manual_sanitization_save_reload_and_generation_lock(tmp_path):
    from bookgen.schemas import DesignTokens, MasterChromeConfig
    with make_client(tmp_path) as api:
        sid = api.post('/api/v1/sessions', json={}).json()['session_id']
        path = f'/api/v1/sessions/{sid}/appearance'
        appearance = {'tokens': DesignTokens(theme_id='ocean', palette_source='preset').model_dump(), 'chrome': MasterChromeConfig(header_left='Brand').model_dump()}
        preset = api.put(path, json=appearance).json()
        assert preset['tokens']['color_brand_primary'] == '#164E63', 'preset must come from typed YAML settings'
        appearance['tokens'].update(palette_source='manual', color_brand_primary='#FFEE00')
        saved = api.put(path, json=appearance).json()
        assert saved['tokens']['color_brand_primary'] != '#FFEE00'
        assert api.get(path).json() == saved
        assert api.post(f'/api/v1/sessions/{sid}/pages', json={'text': 'A clear annual review.'}).status_code == 201
        assert api.put(path, json=appearance).status_code == 409
    with make_client(tmp_path) as api:
        assert api.get(path).json() == saved
        assert api.put(path, json=appearance).status_code == 409


def test_invalid_manual_color_and_unknown_preset(tmp_path):
    from bookgen.schemas import DesignTokens, MasterChromeConfig
    with make_client(tmp_path) as api:
        sid = api.post('/api/v1/sessions', json={}).json()['session_id']
        appearance = {'tokens': DesignTokens(theme_id='unknown', palette_source='preset').model_dump(), 'chrome': MasterChromeConfig().model_dump()}
        assert api.put(f'/api/v1/sessions/{sid}/appearance', json=appearance).status_code == 422


def test_default_appearance_is_accessible_before_any_edit(tmp_path):
    from bookgen.domain.theme import contrast_ratio
    with make_client(tmp_path) as api:
        sid = api.post('/api/v1/sessions', json={}).json()['session_id']
        appearance = api.get(f'/api/v1/sessions/{sid}/appearance').json()
        assert appearance['status'] == 'available'
        tokens = appearance['tokens']
        assert contrast_ratio(tokens['color_brand_accent'], tokens['color_paper']) >= 4.5
