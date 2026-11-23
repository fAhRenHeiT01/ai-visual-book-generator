"""Opt-in manual graph API; all actions remain checkpoint-bound."""
from fastapi import APIRouter, HTTPException, Request

from bookgen.routes.sessions import workflow
from bookgen.schemas.debug import DebugSnapshot, DebugStepRequest
from bookgen.schemas.sessions import GeneratePageRequest

router = APIRouter(prefix="/api/v1/sessions/{session_id}/debug", tags=["debug"])


async def execute(action):
    try:
        return await action()
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("", response_model=DebugSnapshot)
async def inspect_debug(session_id: str, request: Request):
    return await execute(lambda: workflow(request).debugger.snapshot(session_id))


@router.post("/pages", response_model=DebugSnapshot, status_code=201)
async def start_debug(session_id: str, body: GeneratePageRequest, request: Request):
    service = workflow(request)

    async def start():
        service.debugger._enabled()
        assets = {asset.asset_id: asset for asset in service.repository.load_assets(session_id)}
        if any(key not in assets for key in body.asset_ids):
            raise HTTPException(422, "Unknown uploaded asset ID")
        return await service.debugger.start(session_id, text=body.text, assets=[assets[key] for key in body.asset_ids],
            page_id=body.page_id, revise=body.revise)

    return await execute(start)


@router.post("/step", response_model=DebugSnapshot)
async def step_debug(session_id: str, body: DebugStepRequest, request: Request):
    return await execute(lambda: workflow(request).debugger.step(session_id, **body.model_dump()))
