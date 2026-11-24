"""Manifest-backed examples open as isolated normal review sessions."""

from fastapi import APIRouter, HTTPException, Request

from bookgen.examples import manifest, open_example, scenario
from bookgen.routes.sessions import workflow
from bookgen.schemas.sessions import ExampleCatalog, ExampleSummary, SessionSnapshot

router = APIRouter(prefix="/api/v1/examples", tags=["examples"])


@router.get("", response_model=ExampleCatalog)
async def list_examples():
    return ExampleCatalog(examples=[ExampleSummary(id=case["id"], title=case["title"],
        coverage_tags=case["coverage_tags"], outcome=case["expected"]["outcome"])
        for case in manifest()["scenarios"]])


@router.post("/{example_id}/sessions", response_model=SessionSnapshot, status_code=201)
async def create_example(example_id: str, request: Request):
    case = scenario(example_id)
    if case is None:
        raise HTTPException(404, "Example not found")
    return await open_example(workflow(request), case)
