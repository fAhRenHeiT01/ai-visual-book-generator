'use client';
import { useEffect, useState } from 'react';
import type { components } from '../../types/generated';
import { sessionApi } from '../../lib/sessionApi';
export type ComplianceBannerProps = {
  sessionId?: string;
  snapshot?: components['schemas']['SessionSnapshot'];
  onDecision?: () => Promise<void>;
};
export function ComplianceBanner({ sessionId, snapshot, onDecision }: ComplianceBannerProps) {
  const [report, setReport] = useState<components['schemas']['ComplianceReport']>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    setReport(undefined); setError('');
    if (sessionId) sessionApi.compliance(sessionId).then(value => { if (active) setReport(value); }).catch(reason => { if (active) setError(String(reason)); });
    return () => { active = false; };
  }, [sessionId, snapshot]);
  async function decide(decision: components['schemas']['ComplianceDecision']) {
    if (!sessionId) return;
    setBusy(true); setError('');
    try {
      setReport(await sessionApi.decide(sessionId, decision));
      window.dispatchEvent(new CustomEvent('compliance-updated', { detail: sessionId }));
      await onDecision?.();
    } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  return <aside className="compliance-banner studio-controls" data-session-id={sessionId} data-feature-state={report?.status ?? 'loading'} aria-label="Compliance review">
    <p>Compliance review · Audience: {report?.audience_mode ?? snapshot?.context.audience_mode ?? '—'}</p>
    <p>{!report ? 'Checking export readiness…' : report.eligible ? 'Export ready' : 'Export locked · Review flagged claims and commit all pages.'}</p>
    {report?.ledger?.map(({ page_id, metric, decision }) => <div key={`${page_id}-${metric.metric_id}`}>
      <p>{metric.context_snippet}</p>
      <p>{metric.classification} · Source {metric.source_block_id} · <span>{decision ?? 'Needs review'}</span></p>
      <button type="button" disabled={busy} onClick={() => decide({ page_id, metric_id: metric.metric_id, action: 'approve' })}>Approve</button>
      <button type="button" disabled={busy} onClick={() => decide({ page_id, metric_id: metric.metric_id, action: 'redact' })}>Redact</button>
    </div>)}
    {error && <p role="alert">{error}</p>}
  </aside>;
}
