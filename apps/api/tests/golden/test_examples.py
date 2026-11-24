"""Scripted fixture runs exercise the real isolated session and graph boundaries."""

import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from bookgen.adapters.llm.mock import MockLLMProvider
from bookgen.config import load_settings
from bookgen.main import create_app

CORPUS = json.loads((ROOT / "apps/api/src/bookgen/examples/manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def evaluation():
    rows = []
    yield rows
    if not rows:
        return
    ordinary = [row for row in rows if row["outcome"] in {"normal", "export-blocked"}]
    rate = sum(row["repair_attempts"] == 0 and not row["used_fallback"] for row in ordinary) / len(ordinary) if ordinary else None
    if rate is not None:
        assert rate >= .9
    output = ROOT / "apps/api/tests/golden/artifacts/test-results"
    output.mkdir(parents=True, exist_ok=True)
    (output / "scripted-fixture-report.json").write_text(json.dumps({
        "label": "Scripted fixture runs; not a live-model quality estimate",
        "ordinary_first_pass_validity": rate,
        "ordinary_cases": len(ordinary),
        "deliberate_repair_cases": [row for row in rows if row["outcome"] == "repair"],
        "deliberate_fallback_cases": [row for row in rows if row["outcome"] == "fallback"],
        "cases": rows,
    }, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def api(tmp_path):
    settings = load_settings()
    settings.app.sqlite_uri = f"sqlite:///{tmp_path / 'sessions.db'}"
    settings.app.storage_root = tmp_path / "assets"
    provider = MockLLMProvider(settings=settings)
    with TestClient(create_app(settings=settings, provider=provider)) as client:
        yield client
    assert provider.calls == [], "Example sessions must never invoke the configured provider"
    assert provider.grouping_calls == []


def open_example(api, case_id):
    response = api.post(f"/api/v1/examples/{case_id}/sessions")
    assert response.status_code == 201, response.text
    return response.json()


def test_same_example_opens_independently_reviewable_sessions(api):
    first = open_example(api, "portrait-testimonial")
    second = open_example(api, "portrait-testimonial")
    assert first["session_id"] != second["session_id"]
    assert first["pending_review"]["page_id"] != second["pending_review"]["page_id"]
    assert first["example_id"] == second["example_id"] == "portrait-testimonial"
    assert {asset["asset_id"] for asset in first["assets"]}.isdisjoint(asset["asset_id"] for asset in second["assets"])
    assert {asset["storage_key"] for asset in first["assets"]}.isdisjoint(asset["storage_key"] for asset in second["assets"])
    sid = first["session_id"]
    selected = api.post(f"/api/v1/sessions/{sid}/pages/{first['pending_review']['page_id']}/selection", json={"option_id": "option_a"})
    assert selected.status_code == 200
    edited = api.post(f"/api/v1/sessions/{sid}/pages", json={"text": "Independent source edit."})
    assert edited.status_code == 201
    assert api.get(f"/api/v1/sessions/{second['session_id']}").json() == second
    assert api.get(f"/api/v1/sessions/{sid}/assets/{second['assets'][0]['asset_id']}").status_code == 404


@pytest.mark.parametrize("case", CORPUS["scenarios"], ids=lambda case: case["id"])
def test_manifest_drives_offline_generation_review_and_compliance(api, case, evaluation, monkeypatch):
    from bookgen.graph.nodes import PageNodes
    from bookgen.domain.validator import deterministic_validator
    from bookgen.schemas.sessions import SessionSnapshot

    seen_codes = []
    validate = PageNodes.validate

    def record_validation(self, state):
        result = validate(self, state)
        seen_codes.extend(issue["code"] for issue in result["validation_issues"])
        return result

    monkeypatch.setattr(PageNodes, "validate", record_validation)
    raw = open_example(api, case["id"])
    session = SessionSnapshot.model_validate(raw)
    page = session.pending_review
    assert page is not None
    assert page.used_fallback == (case["expected"]["outcome"] == "fallback")
    expected_repairs = (api.app.state.settings.llm.max_repair_retries if page.used_fallback else int(case["expected"]["outcome"] == "repair"))
    assert page.repair_attempts == expected_repairs
    assert len(page.input_assets) == len(case["assets"])
    for asset, key in zip(page.input_assets, case["assets"]):
        entry = CORPUS["assets"][key]
        assert asset.asset_kind.value == entry["kind"]
        assert (asset.width_px, asset.height_px, asset.mime_type) == (entry["width_px"], entry["height_px"], entry["mime_type"])
    probe = case["expected"].get("failure_probe")
    if probe:
        assert probe["issue_code"] in seen_codes
    assert all(block.text in case["copy"] for block in page.input_blocks)
    from bookgen.domain.profiler import profile_content
    original = profile_content(case["copy"], storage=api.app.state.get_workflow().storage, settings=api.app.state.settings.profiling)
    assert "".join(block.text for block in page.input_blocks) == "".join(block.text for block in original.blocks)
    settings = api.app.state.settings
    assert not deterministic_validator([page.option_a, page.option_b], page.input_blocks, page.input_assets,
        grammar=settings.grammar, metrics=page.metrics_ledger,
        audience_mode=session.context.audience_mode, compliance=settings.compliance)
    for option in (page.option_a, page.option_b):
        assert {id for component in option.components for id in component.source_block_ids} == {block.block_id for block in page.input_blocks}
        assert {component.source_asset_id for component in option.components if component.source_asset_id} == {asset.asset_id for asset in page.input_assets}
        for component in option.components:
            if component.extracted_excerpt:
                assert any(component.extracted_excerpt in block.text for block in page.input_blocks if block.block_id in component.source_block_ids)
            if component.source_asset_id:
                asset = next(asset for asset in page.input_assets if asset.asset_id == component.source_asset_id)
                if asset.asset_kind in settings.grammar.protected_asset_kinds:
                    assert component.object_fit == settings.grammar.protected_object_fit
    from io import BytesIO
    from PIL import Image
    for asset in page.input_assets:
        response = api.get(f"/api/v1/sessions/{session.session_id}/assets/{asset.asset_id}?thumbnail=true")
        with Image.open(BytesIO(response.content)) as image:
            assert max(image.size) <= settings.profiling.thumbnail_max_px
    prefix = f"/api/v1/sessions/{session.session_id}"
    assert api.post(f"{prefix}/pages/{page.page_id}/selection", json={"option_id": "option_a"}).status_code == 200
    assert api.get(prefix + "/compliance").status_code == 200
    manifest = api.get(prefix + "/print-data")
    assert manifest.status_code == (409 if case["expected"]["export_blocked"] else 200), manifest.text
    if case["expected"]["export_blocked"]:
        assert api.post(prefix + "/export", json={}).status_code == 409
    evaluation.append({"case_id": case["id"], "direction": session.context.resolved_direction,
        "outcome": case["expected"]["outcome"], "repair_attempts": page.repair_attempts,
        "used_fallback": page.used_fallback, "source_coverage": 1, "asset_coverage": 1,
        "excerpt_fidelity": 1, "protected_media": True,
        "compliance_gate": manifest.status_code, "observed_validation_codes": seen_codes})


def test_catalog_uses_manifest_and_rejects_unknown_id(api):
    response = api.get("/api/v1/examples")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["examples"]] == [case["id"] for case in CORPUS["scenarios"]]
    assert api.post("/api/v1/examples/not-a-case/sessions").status_code == 404


def test_twenty_page_sequence_has_no_repeated_neighbor(api, monkeypatch):
    from bookgen.adapters.llm.context import request_context
    from bookgen.adapters.llm.examples import ExampleLLMProvider

    candidate = ExampleLLMProvider._candidate
    contexts = []

    def capture(self, **kwargs):
        contexts.append(request_context.get())
        assert len(contexts[-1].rhythm_history) <= self.settings.llm.rhythm_window
        assert len(contexts[-1].recent_archetypes) <= self.settings.llm.rhythm_window
        assert all(not isinstance(getattr(asset, field), bytes) for asset in kwargs["assets"] for field in type(asset).model_fields)
        return candidate(self, **kwargs)

    monkeypatch.setattr(ExampleLLMProvider, "_candidate", capture)
    session = open_example(api, "chapter-opener")
    prefix = f"/api/v1/sessions/{session['session_id']}"
    page = session["pending_review"]
    archetypes = []
    for number in range(20):
        archetypes.append(page["option_a"]["archetype"])
        assert api.post(f"{prefix}/pages/{page['page_id']}/selection", json={"option_id": "option_a"}).status_code == 200
        if number < 19:
            response = api.post(prefix + "/pages", json={"text": CORPUS["scenarios"][1]["copy"], "asset_ids": session["active_page"]["asset_ids"]})
            assert response.status_code == 201, response.text
            page = response.json()
    assert all(left != right for left, right in zip(archetypes, archetypes[1:]))
    assert len(api.get(prefix).json()["committed_pages"]) == 20
    assert contexts
    output = ROOT / "apps/api/tests/golden/artifacts/test-results"
    output.mkdir(parents=True, exist_ok=True)
    (output / "twenty-page-rhythm.json").write_text(json.dumps({
        "label": "Scripted fixture run", "page_count": len(archetypes),
        "archetypes": archetypes, "consecutive_repeats": 0,
        "maximum_rhythm_history": max(len(context.rhythm_history) for context in contexts),
        "configured_rhythm_window": api.app.state.settings.llm.rhythm_window,
    }, indent=2) + "\n", encoding="utf-8")


def test_example_binding_survives_restart_without_a_provider_key(tmp_path, monkeypatch):
    from bookgen.adapters.llm.gemini import GeminiProvider

    async def forbidden(*args, **kwargs):
        pytest.fail("A local example attempted to call the live provider")

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(GeminiProvider, "generate_candidate", forbidden)
    monkeypatch.setattr(GeminiProvider, "group_spans", forbidden)
    settings = load_settings()
    settings.llm.provider = "gemini"
    settings.app.sqlite_uri = f"sqlite:///{tmp_path / 'restart.db'}"
    settings.app.storage_root = tmp_path / "assets"
    with TestClient(create_app(settings=settings)) as client:
        opened = open_example(client, "chapter-opener")
        sid = opened["session_id"]
    with TestClient(create_app(settings=settings)) as client:
        assert client.get(f"/api/v1/sessions/{sid}").json() == opened
        page = opened["pending_review"]
        assert client.post(f"/api/v1/sessions/{sid}/pages/{page['page_id']}/selection", json={"option_id": "option_b"}).status_code == 200
        assert client.post(f"/api/v1/sessions/{sid}/pages", json={"text": "Verbatim independent edit."}).status_code == 201


@pytest.mark.asyncio
async def test_snapshot_does_not_block_checkpoint_progress_behind_repository_lock(tmp_path):
    import asyncio
    from threading import Event
    from bookgen.adapters.db.sqlite import SQLiteSessionRepository
    from bookgen.adapters.storage.local_fs import LocalFSStorage
    from bookgen.graph.workflow import PageWorkflow

    settings = load_settings()
    repository = SQLiteSessionRepository(tmp_path / "lock-inversion.db")
    service = PageWorkflow(repository=repository, provider=MockLLMProvider(settings=settings),
        storage=LocalFSStorage(tmp_path / "assets"), settings=settings)
    session = service.create_session()
    acquired, checkpoint_ready = Event(), Event()

    def commit_waiting_for_checkpoint():
        # Model the snapshot writer holding its repository lock while SQLite's
        # async checkpoint transaction needs the event loop in order to finish.
        with repository._lock:
            acquired.set()
            return checkpoint_ready.wait(timeout=2)

    loop = asyncio.get_running_loop()
    writer = loop.run_in_executor(None, commit_waiting_for_checkpoint)
    await asyncio.to_thread(acquired.wait)
    loop.call_later(.02, checkpoint_ready.set)
    try:
        await service.snapshot(session.session_id)
        assert await writer, "Snapshot blocked the event loop behind the committing repository writer"
    finally:
        checkpoint_ready.set()
        await writer
        repository.close()
