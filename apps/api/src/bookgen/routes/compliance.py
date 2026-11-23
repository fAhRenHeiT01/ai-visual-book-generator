"""Independent compliance integration point; the MVP has no export eligibility gate."""
from fastapi import APIRouter, Request

from bookgen.routes.sessions import load_snapshot
from bookgen.schemas.publishing import ComplianceDecision, ComplianceReport

router = APIRouter(prefix="/api/v1/sessions", tags=["compliance"])


@router.get("/{session_id}/compliance", response_model=ComplianceReport)
async def get_compliance(session_id: str, request: Request):
    await load_snapshot(request, session_id)
    return ComplianceReport()


@router.post("/{session_id}/compliance/decisions", response_model=ComplianceReport)
async def decide_compliance(session_id: str, body: ComplianceDecision, request: Request):
    await load_snapshot(request, session_id)
    return ComplianceReport()
