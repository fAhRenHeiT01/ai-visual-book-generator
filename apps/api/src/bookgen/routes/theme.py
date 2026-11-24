"""Frozen theme extraction and persisted session appearance interfaces."""
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from uuid import uuid4

from bookgen.adapters.http.theme_fetcher import ThemeFetcher
from bookgen.domain.theme import extract_theme as extract_brand, sanitize_tokens

from bookgen.routes.sessions import load_snapshot, workflow
from bookgen.schemas.publishing import (
    AppearanceResponse, SessionAppearance, ThemeApplyRequest, ThemeExtractRequest,
    ThemeExtractResponse, ThemeLibraryEntry, ThemeListResponse,
)

router = APIRouter(tags=["appearance"])


@router.post("/api/v1/themes/extract", response_model=ThemeExtractResponse, response_model_exclude_unset=True)
async def extract_theme(body: ThemeExtractRequest, request: Request):
    service = workflow(request)
    settings = service.settings.theme
    try:
        tokens = await run_in_threadpool(extract_brand, str(body.url), fetcher=ThemeFetcher(settings), settings=settings)
    except (ValueError, OSError):
        return ThemeExtractResponse(status='unavailable', tokens=None)
    saved = ThemeLibraryEntry(theme_id=uuid4().hex, name=body.name or body.url.host,
                              source_url=body.url, tokens=tokens)
    service.repository.save_theme(saved)
    return ThemeExtractResponse(status='available', tokens=tokens, theme_id=saved.theme_id)


@router.get("/api/v1/themes", response_model=ThemeListResponse)
async def list_themes(request: Request):
    service = workflow(request)
    settings = service.settings.theme.require_complete()
    presets = [ThemeLibraryEntry(theme_id=key, name=key.replace('_', ' ').title(),
                                tokens=sanitize_tokens(tokens, settings))
               for key, tokens in settings.preset_palettes.items()]
    saved = [entry.model_copy(update={'tokens': sanitize_tokens(entry.tokens, settings)})
             for entry in service.repository.load_themes()]
    return ThemeListResponse(themes=presets + saved)


async def require_editable_appearance(request: Request, session_id: str):
    """Caller must hold the workflow's page lock through its appearance write."""
    service = workflow(request)
    snapshot = await load_snapshot(request, session_id)
    async with service._graph() as graph:
        checkpoint = await graph.aget_state(service._config(session_id))
    if snapshot.pending_review or snapshot.committed_pages or checkpoint.values or checkpoint.next:
        raise HTTPException(409, 'Appearance is locked after generation starts')


@router.post("/api/v1/sessions/{session_id}/appearance/theme", response_model=AppearanceResponse)
async def apply_theme(session_id: str, body: ThemeApplyRequest, request: Request):
    service = workflow(request)
    async with service._page_lock(session_id):
        await require_editable_appearance(request, session_id)
        settings = service.settings.theme
        try:
            tokens = settings.preset_palettes.get(body.theme_id)
            if tokens is None:
                tokens = service.repository.load_theme(body.theme_id).tokens
        except KeyError as exc:
            raise HTTPException(404, 'Theme not found') from exc
        appearance = service.repository.load_appearance(session_id).model_copy(
            update={'tokens': sanitize_tokens(tokens, settings)})
        service.repository.save_appearance(session_id, appearance)
        return AppearanceResponse(status='available', **appearance.model_dump())


@router.get("/api/v1/sessions/{session_id}/appearance", response_model=AppearanceResponse)
async def get_appearance(session_id: str, request: Request):
    service = workflow(request)
    async with service._page_lock(session_id):
        await load_snapshot(request, session_id)
        appearance = service.repository.load_appearance(session_id)
        tokens = sanitize_tokens(appearance.tokens, service.settings.theme)
        if tokens != appearance.tokens:
            appearance = appearance.model_copy(update={'tokens': tokens})
            service.repository.save_appearance(session_id, appearance)
        return AppearanceResponse(status='available', **appearance.model_dump())


@router.put("/api/v1/sessions/{session_id}/appearance", response_model=AppearanceResponse)
async def update_appearance(session_id: str, body: SessionAppearance, request: Request):
    service = workflow(request)
    # Share generation's lock, including serialization across API workers.
    async with service._page_lock(session_id):
        await require_editable_appearance(request, session_id)
        settings = service.settings.theme
        try:
            tokens = body.tokens
            if tokens.palette_source == 'preset':
                tokens = settings.preset_palettes[tokens.theme_id]
            elif tokens.palette_source not in ('manual', 'website_extracted'):
                raise ValueError('Unknown palette source')
            body = body.model_copy(update={'tokens': sanitize_tokens(tokens, settings)})
        except (KeyError, ValueError) as exc:
            raise HTTPException(422, 'Choose a configured preset or valid accessible colors') from exc
        service.repository.save_appearance(session_id, body)
        return AppearanceResponse(status='available', **body.model_dump())
