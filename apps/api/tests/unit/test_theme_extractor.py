"""Theme extraction never contacts unverified destinations; fixtures are offline."""
import importlib.util
import io

import pytest
from PIL import Image


def implementation():
    assert importlib.util.find_spec('bookgen.domain.theme'), 'theme extraction must be implemented'
    from bookgen.domain import theme
    from bookgen.adapters.http.theme_fetcher import ThemeFetcher, FetchResponse
    from bookgen.config import load_settings
    return theme, ThemeFetcher, FetchResponse, load_settings().theme


@pytest.mark.parametrize('address', ['127.0.0.1', '169.254.169.254', '10.0.0.1', '::1', 'fd00::1', 'fe80::1', '::ffff:127.0.0.1', '224.0.0.1'])
def test_blocked_dns_never_contacts_http(address):
    _, Fetcher, _, settings = implementation()
    calls = []
    fetcher = Fetcher(settings, resolver=lambda host, port: [address], http=lambda *args: calls.append(args))
    with pytest.raises(ValueError):
        fetcher.fetch('https://brand.example')
    assert calls == []


def test_redirect_rechecks_dns_and_pins_verified_address():
    _, Fetcher, Response, settings = implementation()
    calls = []
    def http(url, address, limit, timeout):
        calls.append((url, address))
        return Response(302, {'location': 'https://internal.example/secret'}, b'')
    fetcher = Fetcher(settings, resolver=lambda host, port: ['10.0.0.1' if host == 'internal.example' else '93.184.216.34'], http=http)
    with pytest.raises(ValueError):
        fetcher.fetch('https://brand.example')
    assert calls == [('https://brand.example', '93.184.216.34')]


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'ftp://brand.example', 'https://user:pass@brand.example'])
def test_invalid_url_is_rejected_before_dns(url):
    _, Fetcher, _, settings = implementation()
    def resolver(*args):
        pytest.fail('Invalid URL must not resolve')
    with pytest.raises(ValueError):
        Fetcher(settings, resolver=resolver).fetch(url)


def test_rejects_mixed_dns_redirect_loop_oversize_and_http_errors():
    _, Fetcher, Response, settings = implementation()
    for addresses, response in [(['93.184.216.34', '127.0.0.1'], Response(200, {}, b'')),
                                 (['93.184.216.34'], Response(302, {'location': '/'}, b'')),
                                 (['93.184.216.34'], Response(200, {}, b'x' * (settings.max_response_bytes + 1))),
                                 (['93.184.216.34'], Response(500, {}, b''))]:
        with pytest.raises(ValueError):
            Fetcher(settings, resolver=lambda *args: addresses, http=lambda *args: response).fetch('https://brand.example')


@pytest.mark.parametrize('html', ['<meta name="theme-color" content="#FFEE00">',
    '<style>:root { --brand-primary: #FFEE00; --brand-accent: #123456; }</style>',
    '<header style="background-color:#FFEE00">Brand</header>'])
def test_extracts_meta_css_header_and_sanitizes_low_contrast(html):
    theme, Fetcher, Response, settings = implementation()
    fetcher = Fetcher(settings, resolver=lambda *args: ['93.184.216.34'], http=lambda *args: Response(200, {'content-type': 'text/html'}, html.encode()))
    tokens = theme.extract_theme('https://brand.example', fetcher=fetcher, settings=settings)
    assert tokens.palette_source == 'website_extracted'
    assert theme.contrast_ratio(tokens.color_brand_primary, tokens.color_paper) >= settings.contrast_min_ratio
    assert tokens.color_brand_primary != '#FFEE00'


def test_logo_color_and_passing_pair_preserved():
    theme, Fetcher, Response, settings = implementation()
    image = io.BytesIO()
    Image.new('RGB', (4, 4), '#123456').save(image, format='PNG')
    def http(url, *args):
        return Response(200, {}, image.getvalue() if url.endswith('logo.png') else b'<img alt="Company logo" src="/logo.png">')
    tokens = theme.extract_theme('https://brand.example', fetcher=Fetcher(settings, resolver=lambda *args: ['93.184.216.34'], http=http), settings=settings)
    assert tokens.color_brand_primary == '#123456'
    assert theme.sanitize_contrast('#123456', '#FFFFFF', settings.contrast_min_ratio) == '#123456'
    assert theme.contrast_ratio(theme.sanitize_contrast('#EEEEEE', '#000000', settings.contrast_min_ratio), '#000000') >= settings.contrast_min_ratio


def test_manual_tokens_validate_and_sanitize_all_semantic_colors():
    theme, _, _, settings = implementation()
    from bookgen.schemas import DesignTokens
    tokens = theme.sanitize_tokens(DesignTokens(theme_id='custom', palette_source='manual', color_brand_primary='#FFEE00'), settings)
    assert theme.contrast_ratio(tokens.color_brand_primary, tokens.color_paper) >= settings.contrast_min_ratio
    with pytest.raises(ValueError):
        theme.sanitize_tokens(tokens.model_copy(update={'color_paper': 'url(evil)'}), settings)


def test_dark_surface_correction_and_impossible_contrast_are_explicit():
    theme, _, _, settings = implementation()
    corrected = theme.sanitize_contrast('#111111', '#000000', settings.contrast_min_ratio)
    assert theme.contrast_ratio(corrected, '#000000') >= settings.contrast_min_ratio
    with pytest.raises(ValueError):
        theme.sanitize_contrast('#777777', '#777777', 21)
    from bookgen.schemas import DesignTokens
    with pytest.raises(ValueError):
        theme.sanitize_tokens(DesignTokens(theme_id='incompatible', palette_source='manual', color_surface_tint='#111111'), settings)


@pytest.mark.parametrize('html', [b'<p>No colors</p>', b'<img alt="logo" src="/missing.png">', b'<img class="logo" src="/transparent.png">'])
def test_missing_and_invalid_logo_fails_without_inventing_a_brand(html):
    theme, Fetcher, Response, settings = implementation()
    image = io.BytesIO()
    Image.new('RGBA', (2, 2), (0, 0, 0, 0)).save(image, format='PNG')
    def http(url, *args):
        return Response(200, {}, image.getvalue() if url.endswith('transparent.png') else b'invalid image' if url.endswith('missing.png') else html)
    with pytest.raises(ValueError, match='No brand colors'):
        theme.extract_theme('https://brand.example', fetcher=Fetcher(settings, resolver=lambda *args: ['93.184.216.34'], http=http), settings=settings)


def test_shorthand_css_accent_and_inline_style_metadata_case():
    theme, Fetcher, Response, settings = implementation()
    html = b'<style>:root{--brand-primary:#123;--brand-accent:#234}</style>'
    tokens = theme.extract_theme('https://brand.example', fetcher=Fetcher(settings, resolver=lambda *args: ['93.184.216.34'], http=lambda *args: Response(200, {}, html)), settings=settings)
    assert tokens.color_brand_primary == '#112233'
    assert tokens.color_brand_accent == '#223344'


def test_transport_connects_to_checked_ip_and_verifies_original_tls_hostname(monkeypatch):
    from bookgen.adapters.http import theme_fetcher as adapter
    calls = []
    class Socket:
        def settimeout(self, timeout): calls.append(('timeout', timeout))
        def connect(self, destination): calls.append(('connect', destination))
        def close(self): calls.append(('socket_close',))
    class Response:
        status = 200
        def getheaders(self): return [('Content-Length', '2')]
        def read(self, limit):
            assert limit == 11
            return b'ok'
    class Connection:
        def __init__(self, host, port, timeout): calls.append(('host', host, port))
        def request(self, method, path, headers): calls.append(('request', path))
        def getresponse(self): return Response()
        def close(self): calls.append(('connection_close',))
    class TLS:
        def wrap_socket(self, sock, server_hostname):
            calls.append(('tls', server_hostname))
            return sock
    monkeypatch.setattr(adapter.socket, 'socket', lambda *args: Socket())
    monkeypatch.setattr(adapter.http.client, 'HTTPConnection', Connection)
    monkeypatch.setattr(adapter.ssl, 'create_default_context', TLS)
    response = adapter.request_pinned('https://brand.example/path?q=1', '93.184.216.34', 10, 2)
    assert response.body == b'ok'
    assert ('connect', ('93.184.216.34', 443)) in calls
    assert ('tls', 'brand.example') in calls
    assert ('request', '/path?q=1') in calls
    assert ('socket_close',) in calls


def test_config_empty_compatibility_and_strict_settings():
    from bookgen.config.theme import ThemeConfig
    from pydantic import ValidationError
    with pytest.raises(ValueError):
        ThemeConfig().require_complete()
    with pytest.raises(ValidationError):
        ThemeConfig(color_pattern='[')
    with pytest.raises(ValidationError):
        ThemeConfig(max_redirects=-1)
    with pytest.raises(ValidationError):
        ThemeConfig(preset_palettes={'x': {'theme_id': 'x', 'palette_source': 'preset'}}, default_preset='missing')


def test_malformed_remote_http_is_a_recoverable_extraction_failure():
    import http.client
    _, Fetcher, _, settings = implementation()
    def malformed(*args):
        raise http.client.BadStatusLine('broken response')
    with pytest.raises(ValueError, match='Website could not be fetched'):
        Fetcher(settings, resolver=lambda *args: ['93.184.216.34'], http=malformed).fetch('https://brand.example')
