'use client';
import { useEffect, useRef, useState } from 'react';
import type { components } from '../../types/generated';
import { sessionApi } from '../../lib/sessionApi';
import { ReviewText } from '../../engine/blocks/SemanticBlock';
type S = components['schemas'];
export type ComplianceBannerProps = {
  sessionId?: string;
  pageId?: string;
  snapshot?: components['schemas']['SessionSnapshot'];
  onDecision?: () => Promise<void>;
  onReport?: (report: S['ComplianceReport'] | undefined) => void;
};
export function ComplianceBanner({ sessionId, pageId, snapshot, onDecision, onReport }: ComplianceBannerProps) {
  const [report, setReport] = useState<components['schemas']['ComplianceReport']>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const locked = useRef(false);
  const revision = useRef(0);
  useEffect(() => {
    const current = ++revision.current;
    setReport(undefined); setError(''); onReport?.(undefined);
    if (sessionId) sessionApi.compliance(sessionId).then(value => {
      if (current === revision.current) { setReport(value); onReport?.(value); }
    }).catch(reason => { if (current === revision.current) setError(String(reason)); });
    return () => { revision.current++; };
  }, [sessionId, snapshot, onReport]);
  const metrics = report?.ledger?.filter(item => item.page_id === pageId) ?? [];
  const statements = new Map<string, S['ComplianceMetric'][]>();
  for (const item of metrics) {
    const key = JSON.stringify([item.metric.source_block_id, item.metric.context_snippet]);
    statements.set(key, [...(statements.get(key) ?? []), item]);
  }
  async function decide(items: S['ComplianceMetric'][], action: S['ComplianceDecision']['action']) {
    if (!sessionId || locked.current || !items.length) return;
    locked.current = true; setBusy(true); setError('');
    const current = revision.current;
    let changed = false;
    try {
      for (const { page_id, metric } of items) {
        const updated = await sessionApi.decide(sessionId, { page_id, metric_id: metric.metric_id, action });
        changed = true;
        if (current === revision.current) { setReport(updated); onReport?.(updated); }
      }
    } catch (reason) { if (current === revision.current) setError(String(reason)); }
    finally {
      if (changed) {
        window.dispatchEvent(new CustomEvent('compliance-updated', { detail: sessionId }));
        try { await onDecision?.(); } catch (reason) { setError(String(reason)); }
      }
      locked.current = false; setBusy(false);
    }
  }
  return <aside className="compliance-banner studio-controls" data-session-id={sessionId} data-page-id={pageId} data-feature-state={report?.status ?? 'loading'} aria-label="Compliance review">
    <p>Compliance review · Audience: {report?.audience_mode ?? snapshot?.context.audience_mode ?? '—'}</p>
    <p>{!report ? 'Checking export readiness…' : report.eligible ? 'Export ready' : 'Export locked · Review flagged claims and commit all pages.'}</p>
    {report && <div className="compliance-bulk">
      <button type="button" disabled={busy || !metrics.length} onClick={() => { void decide(metrics, 'approve'); }}>Approve all</button>
      <button type="button" disabled={busy || !metrics.length} onClick={() => { void decide(metrics, 'redact'); }}>Redact all</button>
    </div>}
    {report && !metrics.length && <p>No flagged metrics on this page.</p>}
    {Array.from(statements, ([key, entries]) => <div className="compliance-statement" key={key}>
      <p data-testid="compliance-statement"><ReviewText text={entries[0].metric.context_snippet} metrics={entries} /></p>
      {entries.map((item, index) => <div className="compliance-decision" key={item.metric.metric_id} role="group" aria-label={`Review ${item.metric.raw_value}, occurrence ${index + 1}`}>
        <p>{item.metric.raw_value} · {item.metric.classification} · Source {item.metric.source_block_id} · <span>{item.decision ?? 'Needs review'}</span></p>
        <button type="button" disabled={busy} onClick={() => { void decide([item], 'approve'); }}>Approve</button>
        <button type="button" disabled={busy} onClick={() => { void decide([item], 'redact'); }}>Redact</button>
      </div>)}
    </div>)}
    {error && <p role="alert">{error}</p>}
  </aside>;
}
