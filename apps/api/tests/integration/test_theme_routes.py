"""Frozen theme routes activate extraction and persist a locked sanitized appearance."""
from test_publishing_interfaces import make_client


def test_extracted_theme_survives_restart_and_applies_to_another_book(tmp_path, monkeypatch):
    from bookgen.adapters.http.theme_fetcher import FetchResponse
    from bookgen.routes import theme

    calls = []

    class FixtureFetcher:
        def __init__(self, settings):
            pass

        def fetch(self, url):
            calls.append(url)
            return FetchResponse(200, {}, b'<meta name="theme-color" content="#FFEE00">')

    monkeypatch.setattr(theme, 'ThemeFetcher', FixtureFetcher)
    with make_client(tmp_path) as api:
        first = api.post('/api/v1/sessions', json={}).json()['session_id']
        first_path = f'/api/v1/sessions/{first}/appearance'
        original = api.get(first_path).json()
        extracted = api.post('/api/v1/themes/extract', json={'url': 'https://brand.example'}).json()
        assert extracted['status'] == 'available'
        assert api.get(first_path).json() == original, 'extraction must not apply a theme'

    with make_client(tmp_path) as api:
        response = api.get('/api/v1/themes')
        assert response.status_code == 200, 'saved themes must be listed after API restart'
        saved = next(entry for entry in response.json()['themes'] if entry['source_url'])
        assert saved['theme_id'] == extracted['theme_id']
        assert saved['name'] == 'brand.example'
        assert saved['source_url'] == 'https://brand.example/'
        assert saved['tokens'] == extracted['tokens']
        from bookgen.domain.theme import contrast_ratio
        assert saved['tokens']['color_brand_primary'] != '#FFEE00'
        assert contrast_ratio(saved['tokens']['color_brand_primary'], saved['tokens']['color_paper']) >= 4.5
        second = api.post('/api/v1/sessions', json={}).json()['session_id']
        second_path = f'/api/v1/sessions/{second}/appearance'
        applied = api.post(second_path + '/theme', json={'theme_id': saved['theme_id']})
        assert applied.status_code == 200
        assert applied.json()['tokens'] == saved['tokens']
        assert api.get(first_path).json() == original
        assert calls == ['https://brand.example/'], 'listing and applying must not fetch again'


def test_extract_failure_is_offline_and_nonfatal(tmp_path, monkeypatch):
    from bookgen.routes import theme
    class FailedFetcher:
        def __init__(self, settings):
            pass
        def fetch(self, url):
            raise ValueError('Blocked destination')
    monkeypatch.setattr(theme, 'ThemeFetcher', FailedFetcher, raising=False)
    with make_client(tmp_path) as api:
        before = api.get('/api/v1/themes').json()
        assert api.post('/api/v1/themes/extract', json={'url': 'https://brand.example'}).json() == {'status': 'unavailable', 'tokens': None}
        assert api.get('/api/v1/themes').json() == before


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


def test_named_saved_themes_presets_and_appearance_snapshots_are_independent(tmp_path, monkeypatch):
    from bookgen.adapters.http.theme_fetcher import FetchResponse
    from bookgen.domain.theme import sanitize_tokens
    from bookgen.routes import theme
    from unittest.mock import Mock

    fetcher = Mock()
    fetcher.return_value.fetch.return_value = FetchResponse(200, {}, b'<meta name="theme-color" content="#123456">')
    monkeypatch.setattr(theme, 'ThemeFetcher', fetcher)
    with make_client(tmp_path) as api:
        settings = api.app.state.settings.theme
        # Discovery must use the injected application settings, including new presets.
        settings.preset_palettes['forest'] = settings.preset_palettes['ocean'].model_copy(update={'theme_id': 'forest'})
        entries = api.get('/api/v1/themes').json()['themes']
        assert {entry['theme_id'] for entry in entries} == set(settings.preset_palettes)
        for entry in entries:
            assert entry['name'] and entry['source_url'] is None
            assert entry['tokens'] == sanitize_tokens(settings.preset_palettes[entry['theme_id']], settings).model_dump()
        first = api.post('/api/v1/sessions', json={}).json()['session_id']
        path = f'/api/v1/sessions/{first}/appearance'
        original = api.get(path).json()
        original['chrome']['header_left'] = 'Keep this header'
        assert api.put(path, json={key: original[key] for key in ('tokens', 'chrome')}).status_code == 200
        extracted = api.post('/api/v1/themes/extract', json={'url': 'https://brand.example', 'name': '  Brand annual review  '}).json()
        saved = next(entry for entry in api.get('/api/v1/themes').json()['themes'] if entry['theme_id'] == extracted['theme_id'])
        assert saved['name'] == 'Brand annual review'
        applied = api.post(path + '/theme', json={'theme_id': saved['theme_id']}).json()
        assert applied['tokens'] == extracted['tokens']
        assert applied['chrome'] == original['chrome']
        generated = api.post(f'/api/v1/sessions/{first}/pages', json={'text': 'A clear annual review.'})
        assert generated.status_code == 201
        page_id = generated.json()['page_id']
        assert api.post(path + '/theme', json={'theme_id': 'forest'}).status_code == 409
        selected = api.post(f'/api/v1/sessions/{first}/pages/{page_id}/selection', json={'option_id': 'option_a'})
        assert selected.status_code == 200
        snapshot = api.get(f'/api/v1/sessions/{first}').json()
        second = api.post('/api/v1/sessions', json={}).json()['session_id']
        other = f'/api/v1/sessions/{second}/appearance'
        assert api.post(other + '/theme', json={'theme_id': saved['theme_id']}).status_code == 200
        preset = api.post(other + '/theme', json={'theme_id': 'forest'})
        assert preset.status_code == 200
        assert preset.json()['tokens']['theme_id'] == 'forest'
        assert api.get(path).json() == applied
        assert api.get(f'/api/v1/sessions/{first}').json() == snapshot
        assert api.post(other + '/theme', json={'theme_id': 'missing'}).status_code == 404
        assert api.post(other + '/theme', json={'theme_id': 'forest', 'extra': True}).status_code == 422
        assert api.post('/api/v1/sessions/missing/appearance/theme', json={'theme_id': 'forest'}).status_code == 404
        assert fetcher.return_value.fetch.call_count == 1
    with make_client(tmp_path) as api:
        assert api.get(path).json() == applied
        assert api.post(path + '/theme', json={'theme_id': saved['theme_id']}).status_code == 409


def test_empty_or_invalid_extraction_does_not_save_theme(tmp_path, monkeypatch):
    from bookgen.adapters.http.theme_fetcher import FetchResponse
    from bookgen.routes import theme
    from unittest.mock import Mock

    fetcher = Mock()
    monkeypatch.setattr(theme, 'ThemeFetcher', fetcher)
    with make_client(tmp_path) as api:
        before = api.get('/api/v1/themes').json()
        for document in (b'<html></html>', b'<meta name="theme-color" content="invalid">'):
            fetcher.return_value.fetch.return_value = FetchResponse(200, {}, document)
            assert api.post('/api/v1/themes/extract', json={'url': 'https://brand.example'}).json() == {'status': 'unavailable', 'tokens': None}
        assert api.post('/api/v1/themes/extract', json={'url': 'https://brand.example', 'name': '  '}).status_code == 422
        assert api.get('/api/v1/themes').json() == before


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
