"""Frozen theme extraction and persisted session appearance interfaces."""
from fastapi import APIRouter, Request

from bookgen.routes.sessions import load_snapshot, workflow
from bookgen.schemas.publishing import AppearanceResponse, SessionAppearance, ThemeExtractRequest, ThemeExtractResponse

router = APIRouter(tags=["appearance"])


@router.post("/api/v1/themes/extract", response_model=ThemeExtractResponse)
async def extract_theme(body: ThemeExtractRequest):
    return ThemeExtractResponse()


@router.get("/api/v1/sessions/{session_id}/appearance", response_model=AppearanceResponse)
async def get_appearance(session_id: str, request: Request):
    await load_snapshot(request, session_id)
    return AppearanceResponse(**workflow(request).repository.load_appearance(session_id).model_dump())


@router.put("/api/v1/sessions/{session_id}/appearance", response_model=AppearanceResponse)
async def update_appearance(session_id: str, body: SessionAppearance, request: Request):
    await load_snapshot(request, session_id)
    workflow(request).repository.save_appearance(session_id, body)
    return AppearanceResponse(**body.model_dump())
