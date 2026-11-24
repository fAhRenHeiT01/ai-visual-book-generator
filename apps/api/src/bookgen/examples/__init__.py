"""Local manifest catalog and durable session bindings for scripted fixture runs."""

from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from bookgen.domain.profiler import ImageInput, profile_content
from bookgen.schemas import AssetKind, BookContext

ROOT = Path(__file__).resolve().parent


def manifest():
    return json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def scenario(example_id):
    return next((case for case in manifest()["scenarios"] if case["id"] == example_id), None)


class ExampleBindings:
    """Persist identity separately from book context, including across API restarts."""

    def __init__(self, database):
        self.database = database
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("CREATE TABLE IF NOT EXISTS example_sessions (session_id TEXT PRIMARY KEY REFERENCES sessions(session_id), example_id TEXT NOT NULL)")

    def get(self, session_id):
        with closing(sqlite3.connect(self.database)) as connection:
            row = connection.execute("SELECT example_id FROM example_sessions WHERE session_id=?", (session_id,)).fetchone()
        return row[0] if row else None

    def save(self, session_id, example_id):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("INSERT INTO example_sessions VALUES (?, ?)", (session_id, example_id))


async def open_example(service, case):
    catalog = manifest()["assets"]
    created = service.create_session(BookContext.model_validate(case["book_context"]))
    session_id = created.session_id
    service.examples.save(session_id, case["id"])
    inputs = []
    for key in case["assets"]:
        entry = catalog[key]
        path = (ROOT / entry["path"]).resolve()
        if not path.is_relative_to(ROOT.resolve()):
            raise ValueError("Example asset must remain in the local catalog")
        inputs.append(ImageInput(path.read_bytes(), filename=path.name,
            kind=AssetKind(entry["kind"]), alt_caption=entry["alt_caption"]))
    profiled = profile_content("", inputs, storage=service.storage, settings=service.settings.profiling)
    # Each session owns independent asset identities and storage objects.
    assets = []
    for original in profiled.assets:
        asset_id = uuid4().hex
        updates = {"asset_id": asset_id}
        for field in ("storage_key", "thumbnail_key"):
            key = getattr(original, field)
            if key:
                updates[field] = service.storage.put(f"examples/{session_id}/{asset_id}/{Path(key).name}", service.storage.get(key))
        assets.append(original.model_copy(update=updates))
    service.repository.save_assets(session_id, assets)
    await service.generate(session_id, text=case["copy"], assets=assets)
    return await service.snapshot(session_id)


def apply_probe(page, case, blocks, assets, *, protected_kinds):
    """Apply only the declarative failure specified by the checked-in fixture."""
    probe = case["expected"].get("failure_probe")
    if not probe:
        return page
    raw = deepcopy(page.model_dump(mode="json"))
    if probe["mutation"] == "cover_protected":
        protected = {asset.asset_id for asset in assets if asset.asset_kind in protected_kinds}
        next(component for component in raw["components"] if component.get("source_asset_id") in protected)["object_fit"] = "cover"
    elif probe["mutation"] == "drop_source":
        raw["components"] = [component for component in raw["components"] if blocks[-1].block_id not in component["source_block_ids"]]
    elif probe["mutation"] == "invent_excerpt":
        next(component for component in raw["components"] if component.get("extracted_excerpt"))["extracted_excerpt"] = probe["invalid_excerpt"]
    else:
        raise ValueError("Unsupported example failure probe")
    return raw
