"""Standalone real Chromium/Next fixture; no web E2E process is required."""
import asyncio
from contextlib import ExitStack
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
from PIL import Image, ImageDraw
from pypdf import PdfReader
import pytest

from test_publishing_interfaces import make_client

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope='module')
def print_server(tmp_path_factory):
    def port():
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]
    api_port, web_port = port(), port()
    temporary = tmp_path_factory.mktemp('pdf-servers')
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'apps/api/src'), 'BOOKGEN__LLM__PROVIDER': 'mock',
        'BOOKGEN__APP__SQLITE_URI': f'sqlite:///{temporary / "sessions.db"}',
        'BOOKGEN__APP__STORAGE_ROOT': str(temporary / 'assets'),
        'NEXT_PUBLIC_API_ORIGIN': f'http://127.0.0.1:{api_port}', 'NEXT_TELEMETRY_DISABLED': '1',
        'NODE_ENV': 'development', 'TURBOPACK': '1', '__NEXT_DEV_SERVER': '1'}
    env.pop('NO_COLOR', None)
    server_script = temporary / 'print-server.cjs'
    server_script.write_text("require(" + json.dumps(str(ROOT / 'apps/web/node_modules/next/dist/server/lib/start-server.js')) + ").startServer({dir:" +
        json.dumps(str(ROOT / 'apps/web')) + ",isDev:true,hostname:'127.0.0.1',port:" + str(web_port) + "})", encoding='utf-8')
    commands = [([sys.executable, '-m', 'uvicorn', 'bookgen.main:create_app', '--factory', '--port', str(api_port)], ROOT),
        (['node', str(server_script)], ROOT / 'apps/web')]
    processes = []
    with ExitStack() as stack:
        try:
            for index, (command, cwd) in enumerate(commands):
                log = stack.enter_context((temporary / f'{index}.log').open('w'))
                processes.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log))
            for url in (f'http://127.0.0.1:{api_port}/openapi.json', f'http://127.0.0.1:{web_port}'):
                deadline = time.monotonic() + 90
                while True:
                    try:
                        if httpx.get(url, timeout=3).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() > deadline:
                        pytest.fail('Print fixture server failed: ' + '\n'.join(p.read_text()[-4000:] for p in temporary.glob('*.log')))
                    time.sleep(.2)
            with httpx.Client(base_url=f'http://127.0.0.1:{api_port}') as api:
                sid = api.post('/api/v1/sessions', json={}).json()['session_id']
                image = Image.new('RGB', (360, 200), 'white')
                draw = ImageDraw.Draw(image)
                for index, height in enumerate((40, 90, 140)):
                    draw.rectangle((40 + index * 90, 180 - height, 90 + index * 90, 180), fill='navy')
                encoded = BytesIO()
                image.save(encoded, format='PNG')
                uploaded = api.post(f'/api/v1/sessions/{sid}/assets', files={'files': ('chart.png', encoded.getvalue(), 'image/png')})
                assert uploaded.status_code == 201
                yield f'http://127.0.0.1:{web_port}', sid, uploaded.json()['assets'][0]
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                process.wait(timeout=20)


def manifest(server):
    from bookgen.domain.assembler import assemble_book
    from bookgen.schemas.export import AssemblyOptions
    from bookgen.schemas.sessions import SessionSnapshot
    from bookgen.schemas import AtomicTextBlock, BookContext, ImageAssetMeta, PageGenerationResult
    from bookgen.domain.fallback import safe_fallback_builder
    pages = []
    for index in range(8):
        text = f'Publishable original block {index + 1}.'
        blocks = [AtomicTextBlock(block_id=f'b{index}', kind='paragraph', text=text, word_count=5, char_count=len(text))]
        assets = [ImageAssetMeta.model_validate({**server[2], 'asset_kind': 'chart'})] if index == 3 else []
        a, b = safe_fallback_builder(blocks, assets)
        pages.append(PageGenerationResult(page_id=f'p{index}', page_number=index + 1, input_blocks=blocks,
            input_assets=assets, metrics_ledger=[], option_a=a, option_b=b, selected_option_id='option_a'))
    return assemble_book(SessionSnapshot(session_id=server[1], context=BookContext(title='Export fixture'), committed_pages=pages),
        options=AssemblyOptions(imprint='Licensed local assets', closing_cover=True))


@pytest.mark.asyncio
async def test_real_twelve_page_chunks_text_destinations_and_visual_parity(print_server):
    from bookgen.adapters.pdf.playwright_exporter import PlaywrightChunkExporter
    from bookgen.config import load_settings
    settings = load_settings().export.model_copy(update={'chunk_pages': 5, 'print_origin': print_server[0]})
    exporter = PlaywrightChunkExporter(settings)
    book = manifest(print_server)
    pdf = await exporter.export(book)
    assert exporter.chunk_sizes == [5, 5, 2]
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 12
    assert reader.metadata.title == 'Export fixture'
    assert reader.outline
    for index, page in enumerate(book.pages):
        text = ' '.join(reader.pages[index].extract_text().split())
        for expected in page.expected_text:
            assert ' '.join(expected.split()) in text
    annotations = reader.pages[2]['/Annots']
    assert any(reader.get_page_number(annotation.get_object()['/Dest'][0].get_object()) >= 5 for annotation in annotations)
    assert min(exporter.ssim_scores) >= settings.min_ssim


@pytest.mark.asyncio
@pytest.mark.parametrize('persistent', [False, True])
async def test_only_drifting_chunk_retries_once_and_no_partial_download(print_server, persistent):
    from bookgen.adapters.pdf.playwright_exporter import PlaywrightChunkExporter, ExportDriftError
    from bookgen.config import load_settings
    exporter = PlaywrightChunkExporter(load_settings().export.model_copy(update={'chunk_pages': 5, 'print_origin': print_server[0]}))
    original = exporter._check_bounds
    calls = []
    async def bounds(page, start, compact):
        calls.append((start, compact))
        if start == 5 and (persistent or not compact):
            await page.add_style_tag(content='[data-page-number="6"] .page-content { overflow: visible; } [data-page-number="6"] .semantic-block { height: 2000mm !important; }')
        return await original(page, start, compact)
    exporter._check_bounds = bounds
    if persistent:
        with pytest.raises(ExportDriftError, match='chunk 2.*page 6'):
            await exporter.export(manifest(print_server))
    else:
        assert len(PdfReader(BytesIO(await exporter.export(manifest(print_server)))).pages) == 12
        assert calls.count((0, False)) == calls.count((10, False)) == 1
    assert calls.count((5, False)) == calls.count((5, True)) == 1


def test_export_and_print_data_gate_before_browser_and_redact_consistently(tmp_path, monkeypatch):
    from bookgen.adapters.pdf.playwright_exporter import PlaywrightChunkExporter
    async def forbidden(*args):
        raise AssertionError('Browser must not launch')
    monkeypatch.setattr(PlaywrightChunkExporter, 'export', forbidden)
    with make_client(tmp_path) as api:
        sid = api.post('/api/v1/sessions', json={'context': {'title': 'Protected', 'audience_mode': 'client_facing'}}).json()['session_id']
        path = f'/api/v1/sessions/{sid}'
        page = api.post(path + '/pages', json={'text': '[INTERNAL] $4.2M ARR'}).json()
        assert api.get(path + '/print-data').status_code == api.post(path + '/export', json={}).status_code == 409
        api.post(path + f"/pages/{page['page_id']}/selection", json={'option_id': 'option_a'})
        assert api.get(path + '/print-data').status_code == api.post(path + '/export', json={}).status_code == 409
        metric = api.get(path + '/compliance').json()['ledger'][0]['metric']['metric_id']
        api.post(path + '/compliance/decisions', json={'page_id': page['page_id'], 'metric_id': metric, 'action': 'redact'})
        data = api.get(path + '/print-data')
        assert data.status_code == 200
        assert '$4.2M ARR' not in data.text and '[REDACTED]' in data.text
        from bookgen.adapters.pdf.playwright_exporter import ExportDriftError
        async def drift(self, manifest):
            assert '$4.2M ARR' not in manifest.model_dump_json()
            raise ExportDriftError('chunk 1: page 3 persistent drift')
        monkeypatch.setattr(PlaywrightChunkExporter, 'export', drift)
        blocked = api.post(path + '/export', json={})
        assert blocked.status_code == 422 and 'chunk 1: page 3' in blocked.json()['detail']
        assert 'content-disposition' not in blocked.headers and blocked.headers['content-type'] == 'application/json'
        assert api.post(path + '/export', json={'unknown': True}).status_code == 422
