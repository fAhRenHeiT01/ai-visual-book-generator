"""One locked persisted snapshot supplies compliance, appearance, and export inputs."""
from fastapi import APIRouter, HTTPException, Request, Response
from bookgen.adapters.db.metric_decisions import MetricDecisionRepository
from bookgen.adapters.pdf.playwright_exporter import PlaywrightChunkExporter, ExportDriftError
from bookgen.domain.assembler import assemble_book
from bookgen.domain.compliance import require_export_approval
from bookgen.routes.sessions import load_snapshot, workflow
from bookgen.schemas.export import AssemblyOptions, PrintManifest

router = APIRouter(prefix='/api/v1/sessions', tags=['export'])


async def manifest_for(request, session_id, options):
    service = workflow(request)
    async with service._locks[session_id]:
        snapshot = await load_snapshot(request, session_id)
        decisions = MetricDecisionRepository(service.repository.path).load(session_id)
        try:
            pages = require_export_approval(snapshot, decisions=decisions, config=service.settings.compliance)
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc
        try:
            return assemble_book(snapshot, options=options, appearance=service.repository.load_appearance(session_id),
                publishable_pages=pages, settings=service.settings)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc


@router.get('/{session_id}/print-data', response_model=PrintManifest)
async def print_data(session_id: str, request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return await manifest_for(request, session_id, AssemblyOptions())


@router.post('/{session_id}/export', response_class=Response, responses={200: {'content': {'application/pdf': {}}}, 409: {'description': 'Compliance review required'}, 422: {'description': 'Print drift or invalid assembly'}})
async def export_pdf(session_id: str, body: AssemblyOptions, request: Request):
    manifest = await manifest_for(request, session_id, body)
    try:
        data = await PlaywrightChunkExporter(workflow(request).settings.export).export(manifest)
    except ExportDriftError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(data, media_type='application/pdf', headers={'Content-Disposition': 'attachment; filename="book.pdf"', 'Cache-Control': 'no-store'})
