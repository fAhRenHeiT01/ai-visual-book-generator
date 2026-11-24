'use client';
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import type { components } from '../../types/generated';
import { sessionApi } from '../../lib/sessionApi';
import { PageCanvas } from '../../engine/PageCanvas';
import { apiOrigin } from '../../config/env';
import { pageChapterTitles } from '../../engine/MasterChrome';
type S = components['schemas'];

function downloadFilename(title: string) {
  let name = Array.from(title).filter(character => {
    const code = character.charCodeAt(0);
    return code >= 32 && code !== 127 && !'<>:"/\\|?*'.includes(character);
  }).join('').trim();
  while (name.startsWith('.')) name = name.slice(1).trimStart();
  while (name.endsWith('.')) name = name.slice(0, -1).trimEnd();
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  const date = `${String(now.getFullYear()).padStart(4, '0')}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}${pad(now.getMinutes())}`;
  return `${name || 'book'}_${date}-${time}.pdf`;
}

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
  const chapters = pageChapterTitles(publishable ?? []);
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
  async function download() {
    setBusy(true); setError('');
    try {
      const response = await fetch(`${apiOrigin}/api/v1/sessions/${encodeURIComponent(sessionId)}/export`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? 'The PDF could not be verified. Please retry.');
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url; link.download = downloadFilename(context.title); link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  return <>
    <div className="export-actions studio-controls" aria-label="Export draft"><button className="studio-controls" type="button" disabled={disabled || !eligible || busy} onClick={download}>Download PDF</button>
    <button className="studio-controls" type="button" disabled={disabled || !eligible || busy} onClick={print}>Print draft</button>{busy && <p role="status">Preparing verified export…</p>}{!disabled && !eligible && <p className="field-help">Complete compliance review to unlock export.</p>}</div>
    {error && <p className="studio-controls" role="alert">{error}</p>}
    {mounted && createPortal(<>
      <style>{(protectedPrint ? '@media print { body > * { display: none !important; } body > #compliance-print { display: block !important; } }' : '@media print { #compliance-print { display: none !important; } }') + ' @media screen { #compliance-print { display: none; } }'}</style>
      <div id="compliance-print">{publishable?.map((page, index) => <div className="draft-page" key={page.page_id}><PageCanvas result={sessionApi.browserPage(sessionId, page)} tokens={appearance.tokens} pageSize={context.page_size} chrome={{ config: appearance.chrome, pageNumber: page.page_number, totalPages: publishable.length, chapterTitle: chapters[index] }} /></div>)}</div>
    </>, document.body)}
  </>;
}
