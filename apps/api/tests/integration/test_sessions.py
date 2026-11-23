"""FastAPI session lifecycle using the explicit mock provider only."""

from io import BytesIO
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from PIL import Image

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
