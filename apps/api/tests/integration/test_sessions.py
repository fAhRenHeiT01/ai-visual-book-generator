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
