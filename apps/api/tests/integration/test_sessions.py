"""FastAPI session lifecycle using the explicit mock provider only."""

from io import BytesIO
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "apps/api/src"))


def client(tmp_path):
    from bookgen.main import create_app
    from bookgen.config import load_settings
    from bookgen.adapters.llm.mock import MockLLMProvider
    settings = load_settings()
    settings.app.sqlite_uri = f"sqlite:///{tmp_path / 'sessions.db'}"
    settings.app.storage_root = tmp_path / "uploads"
    return TestClient(create_app(settings=settings, provider=MockLLMProvider()))


def test_sessions_route_is_registered():
    from bookgen.main import create_app
    assert "/api/v1/sessions" in create_app().openapi()["paths"], "sessions route must be registered"


def test_saved_session_summaries_are_lightweight_and_resume_durably(tmp_path):
    with client(tmp_path) as api:
        untitled = api.post('/api/v1/sessions', json={}).json()['session_id']
        session = api.post('/api/v1/sessions', json={'context': {'title': 'Saved book'}}).json()['session_id']
        prefix = f'/api/v1/sessions/{session}'
        page = api.post(prefix + '/pages', json={'text': 'Exact saved copy.'}).json()
        api.post(prefix + f"/pages/{page['page_id']}/selection", json={'option_id': 'option_a'})
        response = api.get('/api/v1/sessions')
        assert response.status_code == 200
        summaries = {item['session_id']: item for item in response.json()['sessions']}
        assert summaries[session] == {'session_id': session, 'title': 'Saved book', 'committed_page_count': 1, 'current_page_index': 2}
        assert summaries[untitled]['title'] == 'Untitled book'
        assert 'committed_pages' not in response.text and 'Exact saved copy.' not in response.text
    with client(tmp_path) as api:
        assert api.get(prefix).json()['committed_pages'][0]['input_blocks'][0]['text'] == 'Exact saved copy.'


def test_delete_removes_all_session_data_and_exclusive_assets_only(tmp_path):
    from bookgen.adapters.db.metric_decisions import MetricDecisionRepository
    from bookgen.schemas.publishing import ThemeLibraryEntry
    from bookgen.examples import manifest

    with client(tmp_path) as api:
        session, other = [api.post('/api/v1/sessions', json={}).json()['session_id'] for _ in range(2)]
        service = api.app.state.get_workflow()
        shared, exclusive = BytesIO(), BytesIO()
        Image.new('RGB', (1200, 800), 'red').save(shared, 'PNG')
        Image.new('RGB', (1200, 800), 'blue').save(exclusive, 'PNG')
        def upload(owner, data):
            return api.post(f'/api/v1/sessions/{owner}/assets', files={'files': ('photo.png', data, 'image/png')}).json()['assets'][0]
        shared_asset = upload(session, shared.getvalue())
        exclusive_asset = upload(session, exclusive.getvalue())
        upload(other, shared.getvalue())
        for owner in (session, other):
            prefix = f'/api/v1/sessions/{owner}'
            page = api.post(prefix + '/pages', json={'text': 'Saved source.'}).json()
            api.post(prefix + f"/pages/{page['page_id']}/selection", json={'option_id': 'option_a'})
            service.repository.save_appearance(owner, service.repository.load_appearance(owner))
            service.examples.save(owner, manifest()['scenarios'][0]['id'])
            MetricDecisionRepository(service.repository.path).save(owner, page['page_id'], 'metric', 'approve')
        connection = service.repository._connection
        theme = ThemeLibraryEntry(theme_id='shared', name='Shared', tokens=service.repository.load_appearance(session).tokens)
        service.repository.save_theme(theme)
        assert api.delete(f'/api/v1/sessions/{session}').status_code == 204
        assert api.get(f'/api/v1/sessions/{session}').status_code == 404
        assert api.delete(f'/api/v1/sessions/{session}').status_code == 404
        assert api.delete('/api/v1/sessions/missing').status_code == 404
        for table, column in [('sessions', 'session_id'), ('session_assets', 'session_id'), ('session_appearance', 'session_id'), ('page_snapshots', 'session_id'), ('example_sessions', 'session_id'), ('metric_decisions', 'session_id'), ('checkpoints', 'thread_id'), ('writes', 'thread_id')]:
            assert connection.execute(f'SELECT COUNT(*) FROM {table} WHERE {column}=?', (session,)).fetchone()[0] == 0
            assert connection.execute(f'SELECT COUNT(*) FROM {table} WHERE {column}=?', (other,)).fetchone()[0] > 0
        assert service.repository.load_theme('shared') == theme
        for field in ('storage_key', 'thumbnail_key'):
            assert Path(shared_asset[field]).is_file()
            assert not Path(exclusive_asset[field]).exists()
        assert api.get(f'/api/v1/sessions/{other}').status_code == 200
    with client(tmp_path) as api:
        assert [item['session_id'] for item in api.get('/api/v1/sessions').json()['sessions']] == [other]


def test_cross_origin_delete_preflight_is_allowed(tmp_path):
    with client(tmp_path) as api:
        origin = api.app.state.settings.app.cors_origins[0]
        response = api.options('/api/v1/sessions/missing', headers={'Origin': origin, 'Access-Control-Request-Method': 'DELETE'})
        assert response.status_code == 200


def test_delete_empty_session_without_checkpoint_tables(tmp_path):
    with client(tmp_path) as api:
        session = api.post('/api/v1/sessions', json={}).json()['session_id']
        assert api.delete(f'/api/v1/sessions/{session}').status_code == 204
        assert api.get('/api/v1/sessions').json() == {'sessions': []}


def test_failed_asset_cleanup_preserves_session_for_retry(tmp_path, monkeypatch):
    with client(tmp_path) as api:
        session = api.post('/api/v1/sessions', json={}).json()['session_id']
        raw = BytesIO()
        Image.new('RGB', (100, 100)).save(raw, 'PNG')
        prefix = f'/api/v1/sessions/{session}'
        api.post(prefix + '/assets', files={'files': ('photo.png', raw.getvalue(), 'image/png')})
        storage = api.app.state.get_workflow().storage
        original = storage.delete
        def fail_cleanup(key):
            raise PermissionError('Object is in use')
        monkeypatch.setattr(storage, 'delete', fail_cleanup)
        assert api.delete(prefix).status_code == 503
        assert api.get('/api/v1/sessions').json()['sessions'][0]['session_id'] == session
        monkeypatch.setattr(storage, 'delete', original)
        assert api.delete(prefix).status_code == 204


def test_stale_metric_save_cannot_recreate_deleted_session_records(tmp_path):
    from bookgen.adapters.db.metric_decisions import MetricDecisionRepository
    with client(tmp_path) as api:
        session = api.post('/api/v1/sessions', json={}).json()['session_id']
        decisions = MetricDecisionRepository(api.app.state.get_workflow().repository.path)
        assert api.delete(f'/api/v1/sessions/{session}').status_code == 204
        # A request that read its snapshot before deletion must not leave an orphan.
        decisions.save(session, 'page', 'metric', 'approve')
        assert decisions.load(session) == {}


def test_original_jpeg_preview_and_optional_thumbnail_survive_reload(tmp_path):
    from bookgen.schemas import ImageAssetMeta

    raw = BytesIO()
    Image.new("RGB", (320, 480)).save(raw, "JPEG")
    with client(tmp_path) as api:
        session = api.post("/api/v1/sessions", json={}).json()["session_id"]
        prefix = f"/api/v1/sessions/{session}"
        asset = api.post(prefix + "/assets", files={"files": ("portrait.jpg", raw.getvalue(), "image/jpeg")}).json()["assets"][0]
        assert asset.get("thumbnail_key") is None
        # Persist a canonical record with the optional key entirely absent.
        del asset["thumbnail_key"]
        assert ImageAssetMeta.model_validate(asset).thumbnail_key is None
        connection = api.app.state.get_workflow().repository._connection
        with connection:
            connection.execute("UPDATE session_assets SET payload=? WHERE session_id=? AND asset_id=?",
                               (json.dumps(asset), session, asset["asset_id"]))
    with client(tmp_path) as api:
        for suffix in ("", "?thumbnail=true"):
            response = api.get(prefix + f"/assets/{asset['asset_id']}" + suffix)
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/jpeg"
            assert response.content == raw.getvalue()
        generated = api.post(prefix + "/pages", json={"text": "Exact source copy.", "asset_ids": [asset["asset_id"]]})
        assert generated.status_code == 201
        assert generated.json()["input_assets"][0]["thumbnail_key"] is None


@pytest.mark.parametrize("preview_format,preview_mime", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
def test_legacy_stored_thumbnail_is_served_with_actual_mime(tmp_path, preview_format, preview_mime):
    from bookgen.schemas import ImageAssetMeta

    original, preview = BytesIO(), BytesIO()
    Image.new("RGB", (320, 200)).save(original, "JPEG")
    Image.new("RGB", (160, 100)).save(preview, preview_format)
    with client(tmp_path) as api:
        session = api.post("/api/v1/sessions", json={}).json()["session_id"]
        service = api.app.state.get_workflow()
        asset = ImageAssetMeta(asset_id="old", storage_key=service.storage.put("legacy/original", original.getvalue()),
                               thumbnail_key=service.storage.put("legacy/preview", preview.getvalue()),
                               mime_type="image/jpeg", width_px=320, height_px=200, aspect_ratio=1.6)
        service.repository.save_assets(session, [asset])
    with client(tmp_path) as api:
        response = api.get(f"/api/v1/sessions/{session}/assets/old?thumbnail=true")
        assert response.status_code == 200
        assert response.headers["content-type"] == preview_mime
        assert response.content == preview.getvalue()
        assert api.get(f"/api/v1/sessions/{session}/assets/old").content == original.getvalue()


def test_create_upload_generate_events_select_and_reload(tmp_path):
    with client(tmp_path) as api:
        response = api.post("/api/v1/sessions", json={"context": {"title": "A book"}})
        assert response.status_code == 201
        session = response.json()["session_id"]
        prefix = f"/api/v1/sessions/{session}"
        raw = BytesIO()
        Image.new("RGB", (1200, 800)).save(raw, "PNG")
        upload = api.post(prefix + "/assets", files={"files": ("chart.png", raw.getvalue(), "image/png")})
        assert upload.status_code == 201
        asset = upload.json()["assets"][0]
        assert api.get(prefix + f"/assets/{asset['asset_id']}").content == raw.getvalue()
        thumbnail = api.get(prefix + f"/assets/{asset['asset_id']}?thumbnail=true")
        with Image.open(BytesIO(thumbnail.content)) as preview:
            assert max(preview.size) <= 768
        generated = api.post(prefix + "/pages", json={"text": "First paragraph.\n\nSecond paragraph.", "asset_ids": [asset["asset_id"]]})
        assert generated.status_code == 201
        page = generated.json()
        assert page["input_assets"][0]["asset_kind"] == "chart"
        events = api.get(prefix + f"/pages/{page['page_id']}/events")
        assert events.headers["content-type"].startswith("text/event-stream")
        assert "event: review" in events.text
        assert "event: terminal" in events.text
        assert api.get(prefix).json()["pending_review"]["page_id"] == page["page_id"]
        selection = prefix + f"/pages/{page['page_id']}/selection"
        assert api.post(selection, json={"option_id": "invalid"}).status_code == 422
        assert api.post(selection, json={"option_id": "option_a"}).status_code == 200
        assert api.post(selection, json={"option_id": "option_b"}).status_code == 409
        assert api.post(selection, json={"option_id": "option_a"}).status_code == 200
        assert "event: committed" in api.get(prefix + f"/pages/{page['page_id']}/events").text
    with client(tmp_path) as reopened:
        state = reopened.get(prefix).json()
        assert state["pending_review"] is None
        assert len(state["committed_pages"]) == 1
        assert state["current_page_index"] == 2


def test_unknown_and_invalid_requests(tmp_path):
    with client(tmp_path) as api:
        assert api.get("/api/v1/sessions/missing").status_code == 404
        assert api.post("/api/v1/sessions", json={"unexpected": True}).status_code == 422
        session = api.post("/api/v1/sessions", json={}).json()["session_id"]
        prefix = f"/api/v1/sessions/{session}"
        assert api.post(prefix + "/pages", json={"text": "Body", "asset_ids": ["unknown"]}).status_code == 422
        assert api.post(prefix + "/pages", json={"text": "", "asset_ids": []}).status_code == 422
        assert api.post(prefix + "/pages", json={"text": "Body", "asset_ids": ["duplicate", "duplicate"]}).status_code == 422
        assert api.get(prefix + "/assets/missing").status_code == 404
        assert api.post(prefix + "/assets", files={"files": ("bad.png", b"not an image", "image/png")}).status_code == 422
        page = api.post(prefix + "/pages", json={"text": "First."}).json()
        assert api.post(prefix + "/pages", json={"text": "Second."}).status_code == 409
        assert api.get(prefix + "/pages/missing/events").status_code == 404
        assert api.post(prefix + "/pages/missing/selection", json={"option_id": "option_a"}).status_code == 404
        assert page["page_number"] == 1


def test_generation_recovery_identity_errors_and_saved_review(tmp_path):
    from bookgen.adapters.llm.mock import MockLLMProvider
    from google.genai.errors import ClientError, ServerError

    class Failing(MockLLMProvider):
        failure = RuntimeError("connection lost")

        async def generate_candidate(self, **kwargs):
            raise self.failure

    with client(tmp_path) as api:
        provider = Failing()
        api.app.state.get_workflow().provider = provider
        session = api.post("/api/v1/sessions", json={}).json()["session_id"]
        prefix = f"/api/v1/sessions/{session}"
        body = {"page_id": "stable", "text": "Saved original."}
        assert api.post(prefix + "/pages", json=body).status_code == 503
        assert api.get(prefix).json()["active_page"]["page_id"] == "stable"
        assert api.post(prefix + "/pages", json={**body, "text": "Edited."}).status_code == 422
        assert api.post(prefix + "/pages", json={**body, "page_id": "other"}).status_code == 409
        provider.failure = ClientError(400, {"error": {"message": "Invalid response_json_schema"}})
        assert api.post(prefix + "/pages", json=body).status_code == 502
        provider.failure = ServerError(503, {"error": {"message": "Unavailable"}})
        assert api.post(prefix + "/pages", json=body).status_code == 503
        api.app.state.get_workflow().provider = MockLLMProvider()
        review = api.post(prefix + "/pages", json=body)
        assert review.status_code == 201
        api.app.state.get_workflow().provider = provider
        assert api.post(prefix + "/pages", json=body).json() == review.json()
        assert api.post(prefix + "/pages/stable/selection", json={"option_id": "option_a"}).status_code == 200
        assert api.post(prefix + "/pages", json=body).json()["selected_option_id"] == "option_a"
        assert api.get(prefix).json()["current_page_index"] == 2

def test_concurrent_workers_return_one_page_for_duplicate_requests(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    with client(tmp_path) as api:
        session = api.post('/api/v1/sessions', json={}).json()['session_id']
    rendezvous = Barrier(2)
    from bookgen.adapters.llm.mock import MockLLMProvider
    import asyncio
    calls = []

    class Counting(MockLLMProvider):
        async def generate_candidate(self, **kwargs):
            calls.append(kwargs['strategy_tag'])
            await asyncio.sleep(0.1)
            return await super().generate_candidate(**kwargs)

    def worker():
        with client(tmp_path) as api:
            api.app.state.get_workflow().provider = Counting()
            rendezvous.wait()
            return api.post(f'/api/v1/sessions/{session}/pages', json={'page_id': 'duplicate', 'text': 'One durable page.'})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: worker(), range(2)))
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    assert len(calls) == 2
    with client(tmp_path) as api:
        prefix = f'/api/v1/sessions/{session}'
        assert api.post(prefix + '/pages/duplicate/selection', json={'option_id': 'option_a'}).status_code == 200
        assert len(api.get(prefix).json()['committed_pages']) == 1
        next_page = api.post(prefix + '/pages', json={'page_id': 'next', 'text': 'Next page.'}).json()
        assert next_page['page_number'] == 2
