"""Versioned session endpoints backed by durable page graph checkpoints."""

import asyncio
import json
from io import BytesIO
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from PIL import Image

from bookgen.graph.workflow import PageConflict
from bookgen.domain.profiler import ImageInput, infer_page_title, normalize_page_input, profile_content
from bookgen.schemas import PageGenerationResult
from bookgen.schemas.sessions import AssetUploadResponse, CreateSessionRequest, GeneratePageRequest, SelectOptionRequest, SessionListResponse, SessionSnapshot


router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


def workflow(request):
    return request.app.state.get_workflow()


async def load_snapshot(request, session_id):
    try:
        return await workflow(request).snapshot(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc


@router.post("", response_model=SessionSnapshot, status_code=201)
async def create_session(body: CreateSessionRequest, request: Request):
    return workflow(request).create_session(body.context)


@router.get("", response_model=SessionListResponse)
async def list_sessions(request: Request):
    return SessionListResponse(sessions=await asyncio.to_thread(workflow(request).repository.list_sessions))


@router.delete("/{session_id}", status_code=204, response_class=Response)
async def delete_session(session_id: str, request: Request):
    try:
        await workflow(request).delete_session(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc
    except OSError as exc:
        raise HTTPException(503, "Book could not be deleted. Retry deleting this book.") from exc
    return Response(status_code=204)


@router.get("/{session_id}", response_model=SessionSnapshot)
async def get_session(session_id: str, request: Request):
    return await load_snapshot(request, session_id)


@router.post("/{session_id}/assets", response_model=AssetUploadResponse, status_code=201)
async def upload_assets(session_id: str, request: Request, files: list[UploadFile] = File(...)):
    service = workflow(request)
    try:
        async with service._page_lock(session_id), service._page_lock('asset-storage'):
            await load_snapshot(request, session_id)
            images = [ImageInput(data=await file.read(), filename=file.filename or "") for file in files]
            profile = profile_content("", images, storage=service.storage, settings=service.settings.profiling)
            assets = [asset.model_copy(update={"asset_id": uuid4().hex}) for asset in profile.assets]
            service.repository.save_assets(session_id, assets)
            return AssetUploadResponse(assets=assets)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        for file in files:
            await file.close()


@router.get("/{session_id}/assets/{asset_id}", response_class=Response)
async def get_asset(session_id: str, asset_id: str, request: Request, thumbnail: bool = False):
    snapshot = await load_snapshot(request, session_id)
    asset = next((asset for asset in snapshot.assets if asset.asset_id == asset_id), None)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    key = asset.thumbnail_key if thumbnail and asset.thumbnail_key else asset.storage_key
    data = workflow(request).storage.get(key)
    with Image.open(BytesIO(data)) as image:
        mime_type = Image.MIME[image.format]
    return Response(data, media_type=mime_type)


@router.post("/{session_id}/pages", response_model=PageGenerationResult, status_code=201)
async def generate_page(session_id: str, body: GeneratePageRequest, request: Request):
    snapshot = await load_snapshot(request, session_id)
    assets = {asset.asset_id: asset for asset in snapshot.assets}
    if any(asset_id not in assets for asset_id in body.asset_ids):
        raise HTTPException(422, "Unknown uploaded asset ID")
    try:
        service = workflow(request)
        return await service.generate(session_id, text=normalize_page_input(body.text), title=body.title,
            inferred_title=infer_page_title(body.text, title=body.title, settings=service.settings.profiling),
            assets=[assets[key] for key in body.asset_ids], page_id=body.page_id, revise=body.revise)
    except PageConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        if getattr(exc, "code", None) == 400:
            raise HTTPException(502, "Provider rejected the generation schema") from exc
        raise HTTPException(503, "Generation temporarily unavailable. Retry this page.") from exc


@router.get("/{session_id}/pages/{page_id}/events", response_class=StreamingResponse,
            responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}})
async def page_events(session_id: str, page_id: str, request: Request):
    snapshot = await load_snapshot(request, session_id)
    pages = snapshot.committed_pages + ([snapshot.pending_review] if snapshot.pending_review else [])
    page = next((page for page in pages if page.page_id == page_id), None)
    if page is None:
        raise HTTPException(404, "Page not found")

    async def events():
        kind = "committed" if page.selected_option_id else "review"
        yield f"event: {kind}\ndata: {page.model_dump_json()}\n\n"
        yield "event: terminal\ndata: " + json.dumps({"page_id": page_id, "status": kind}) + "\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{session_id}/pages/{page_id}/selection", response_model=PageGenerationResult)
async def select_page(session_id: str, page_id: str, body: SelectOptionRequest, request: Request):
    await load_snapshot(request, session_id)
    try:
        return await workflow(request).select(session_id, page_id, body.option_id)
    except KeyError as exc:
        raise HTTPException(404, "Page not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
