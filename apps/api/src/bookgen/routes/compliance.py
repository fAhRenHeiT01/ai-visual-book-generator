"""Authoritative review of source-versioned metric decisions."""
from fastapi import APIRouter, HTTPException, Request

from bookgen.routes.sessions import load_snapshot, workflow
from bookgen.adapters.db.metric_decisions import MetricDecisionRepository
from bookgen.domain.compliance import compliance_report
from bookgen.schemas.publishing import ComplianceDecision, ComplianceReport

router = APIRouter(prefix="/api/v1/sessions", tags=["compliance"])


@router.get("/{session_id}/compliance", response_model=ComplianceReport)
async def get_compliance(session_id: str, request: Request):
    snapshot = await load_snapshot(request, session_id)
    service = workflow(request)
    decisions = MetricDecisionRepository(service.repository.path).load(session_id)
    return compliance_report(snapshot, decisions=decisions, config=service.settings.compliance)


@router.post("/{session_id}/compliance/decisions", response_model=ComplianceReport)
async def decide_compliance(session_id: str, body: ComplianceDecision, request: Request):
    snapshot = await load_snapshot(request, session_id)
    service = workflow(request)
    repository = MetricDecisionRepository(service.repository.path)
    report = compliance_report(snapshot, decisions=repository.load(session_id), config=service.settings.compliance)
    if not any(item.page_id == body.page_id and item.metric.metric_id == body.metric_id for item in report.ledger):
        raise HTTPException(409, 'Metric source version no longer matches this page')
    repository.save(session_id, body.page_id, body.metric_id, body.action)
    return compliance_report(snapshot, decisions=repository.load(session_id), config=service.settings.compliance)
