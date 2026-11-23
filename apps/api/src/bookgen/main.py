"""FastAPI application factory and deterministic export of its v1 contract."""

import argparse
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic.json_schema import models_json_schema

from bookgen.config import load_settings
from bookgen.schemas import CONTRACT_MODELS


def create_app() -> FastAPI:
    application = FastAPI(title="Visual Book Generator", version="1.0.0")
    application.state.settings = load_settings()

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
