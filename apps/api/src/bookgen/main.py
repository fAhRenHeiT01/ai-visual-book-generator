"""FastAPI application factory and deterministic export of its v1 contract."""

import argparse
from contextlib import asynccontextmanager
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from pydantic.json_schema import models_json_schema

from bookgen.config import load_settings
from bookgen.schemas import CONTRACT_MODELS
from bookgen.routes.sessions import router as sessions_router
from bookgen.routes.compliance import router as compliance_router
from bookgen.routes.theme import router as theme_router
from bookgen.routes.export import router as export_router
from bookgen.routes.debug import router as debug_router
from bookgen.routes.examples import router as examples_router


def create_app(*, settings=None, provider=None, repository=None, storage=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application):
        yield
        if application.state.workflow is not None:
            application.state.workflow.repository.close()
            adapter = application.state.workflow.provider
            if hasattr(adapter, "close"):
                await adapter.close()

    application = FastAPI(title="Visual Book Generator", version="1.0.0", lifespan=lifespan)
    application.state.settings = settings or load_settings()
    application.state.workflow = None

    def get_workflow():
        if application.state.workflow is None:
            from bookgen.adapters.db.sqlite import SQLiteSessionRepository
            from bookgen.adapters.llm.gemini import GeminiProvider
            from bookgen.adapters.llm.mock import MockLLMProvider
            from bookgen.adapters.storage.local_fs import LocalFSStorage
            from bookgen.graph.workflow import PageWorkflow

            config = application.state.settings
            if not config.app.sqlite_uri.startswith("sqlite:///"):
                raise ValueError("This runtime requires a SQLite URI")
            snapshots = repository or SQLiteSessionRepository(config.app.sqlite_uri.removeprefix("sqlite:///"))
            asset_storage = storage or LocalFSStorage(config.app.storage_root)
            adapter = provider or (MockLLMProvider(settings=config) if config.llm.provider == "mock" else GeminiProvider(storage=asset_storage, settings=config))
            application.state.workflow = PageWorkflow(repository=snapshots, provider=adapter, storage=asset_storage, settings=config)
        return application.state.workflow

    application.state.get_workflow = get_workflow
    application.add_middleware(CORSMiddleware, allow_origins=application.state.settings.app.cors_origins,
                               allow_methods=["GET", "POST", "PUT"], allow_headers=["Content-Type"])
    application.include_router(sessions_router)
    application.include_router(compliance_router)
    application.include_router(theme_router)
    application.include_router(export_router)
    application.include_router(debug_router)
    application.include_router(examples_router)

    def openapi():
        if application.openapi_schema is None:
            document = get_openapi(
                title=application.title, version=application.version, routes=application.routes
            )
            _, contracts = models_json_schema(
                [(model, "validation") for model in CONTRACT_MODELS],
                ref_template="#/components/schemas/{model}",
            )
            document.setdefault("components", {}).setdefault("schemas", {}).update(contracts["$defs"])
            application.openapi_schema = document
        return application.openapi_schema

    application.openapi = openapi
    return application


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the runtime application's OpenAPI document")
    parser.add_argument("--export-openapi", required=True, type=Path)
    arguments = parser.parse_args()
    arguments.export_openapi.parent.mkdir(parents=True, exist_ok=True)
    arguments.export_openapi.write_text(
        json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
