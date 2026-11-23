'use client';
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import type { components } from '../../types/generated';
import { sessionApi } from '../../lib/sessionApi';
import { PageCanvas } from '../../engine/PageCanvas';
type S = components['schemas'];
export type ExportActionProps = {
  disabled: boolean;
  sessionId: string;
  pages: S['PageGenerationResult'][];
  context: S['BookContext'];
  appearance: S['AppearanceResponse'];
};
export function ExportAction({ disabled, sessionId, pages, context, appearance }: ExportActionProps) {
  const [eligible, setEligible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [publishable, setPublishable] = useState<S['PageGenerationResult'][] | null>(null);
  const [protectedPrint, setProtectedPrint] = useState(true);
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);
  useEffect(() => {
    let active = true;
    const refresh = () => {
      setEligible(false); setPublishable(null); setProtectedPrint(true);
      sessionApi.compliance(sessionId).then(report => {
        if (!active) return;
        const allowed = report.status === 'available' && Boolean(report.eligible);
        setEligible(allowed);
        // Internal drafts with no redactions can use the existing print canvas.
        setProtectedPrint(!allowed || report.audience_mode === 'client_facing' || Boolean(report.ledger?.some(entry => entry.decision === 'redact')));
      }).catch(() => { if (active) setEligible(false); });
    };
    refresh();
    window.addEventListener('compliance-updated', refresh);
    return () => { active = false; window.removeEventListener('compliance-updated', refresh); };
  }, [sessionId, pages]);
  useEffect(() => {
    if (!publishable) return;
    const frame = requestAnimationFrame(() => { window.print(); setBusy(false); });
    return () => cancelAnimationFrame(frame);
  }, [publishable]);
  async function print() {
    setBusy(true); setError(''); setPublishable(null); setProtectedPrint(true);
    try {
      const report = await sessionApi.compliance(sessionId);
      setEligible(Boolean(report.eligible));
      if (report.status !== 'available' || !report.eligible || !report.publishable_pages?.length) throw new Error('Complete compliance review before exporting.');
      setPublishable(report.publishable_pages);
    } catch (reason) { setError(String(reason)); setEligible(false); setBusy(false); }
  }
  return <>
    <button className="studio-controls" type="button" disabled={disabled || !eligible || busy} onClick={print}>Print draft</button>
    {error && <p className="studio-controls" role="alert">{error}</p>}
    {mounted && createPortal(<>
      <style>{(protectedPrint ? '@media print { body > * { display: none !important; } body > #compliance-print { display: block !important; } }' : '@media print { #compliance-print { display: none !important; } }') + ' @media screen { #compliance-print { display: none; } }'}</style>
      <div id="compliance-print">{publishable?.map(page => <div className="draft-page" key={page.page_id}><PageCanvas result={sessionApi.browserPage(sessionId, page)} tokens={appearance.tokens} pageSize={context.page_size} chrome={{ config: appearance.chrome, pageNumber: page.page_number, totalPages: publishable.length, chapterTitle: context.title, isCover: page.page_number === 1 }} /></div>)}</div>
    </>, document.body)}
  </>;
}
