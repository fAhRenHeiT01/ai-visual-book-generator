'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { components } from '../../types/generated';
import { sessionApi } from '../../lib/sessionApi';
import { BookSetup } from '../setup/BookSetup';
import { ThemeControls } from '../setup/ThemeControls';
import { ComplianceBanner } from '../compliance/ComplianceBanner';
import { DraftViewer } from '../draft/DraftViewer';
import { PageComposer } from './PageComposer';
import { OptionComparison } from './OptionComparison';
type S = components['schemas'];
export function Studio({ sessionId }: { sessionId?: string }) {
  const [session, setSession] = useState<S['SessionSnapshot']>();
  const [appearance, setAppearance] = useState<S['AppearanceResponse']>();
  const [status, setStatus] = useState(sessionId ? 'Loading book…' : '');
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const locked = useRef(false);
  useEffect(() => {
    if (!sessionId) return;
    let active = true;
    Promise.all([sessionApi.load(sessionId), sessionApi.appearance(sessionId)]).then(([snapshot, theme]) => {
      if (active) { setSession(snapshot); setAppearance(theme); setStatus(''); setError(''); }
    }).catch((cause: Error) => { if (active) { setError(cause.message); setStatus(''); } });
    return () => { active = false; };
  }, [sessionId, retry]);
  const refresh = useCallback(async () => {
    if (session) setSession(await sessionApi.load(session.session_id));
  }, [session]);
  const pendingId = session?.pending_review?.page_id;
  useEffect(() => {
    if (session && pendingId) return sessionApi.review(session.session_id, pendingId, () => { void refresh().catch((cause: Error) => setError(cause.message)); });
  }, [session?.session_id, pendingId, refresh]);
  async function run(message: string, action: () => Promise<void>) {
    if (locked.current) return;
    locked.current = true; setStatus(message); setError('');
    try { await action(); } catch (cause) { setError(cause instanceof Error ? cause.message : 'Please retry.'); }
    finally { locked.current = false; setStatus(''); }
  }
  return <main className="studio">
    <header className="studio-controls studio-header"><a href="/">Visual Book Generator</a><h1>{session?.context.title || 'Visual Book Generator'}</h1>{session && <p>Saved automatically · <a href={`/sessions/${session.session_id}`}>Reopen this book</a></p>}</header>
    {status && <p className="studio-controls" role="status">{status}</p>}
    {error && <div className="studio-controls" role="alert">{error}{sessionId && !session && <button onClick={() => { setStatus('Loading book…'); setRetry(value => value + 1); }}>Retry loading book</button>}</div>}
    {!session && !sessionId && <div className="studio-controls"><BookSetup busy={!!status} onCreate={context => { void run('Creating book…', async () => {
      const created = await sessionApi.create(context);
      const theme = await sessionApi.appearance(created.session_id);
      setSession(created); setAppearance(theme); window.history.pushState(null, '', `/sessions/${created.session_id}`);
    }); }} /></div>}
    <ThemeControls sessionId={session?.session_id} appearance={appearance} onAppearanceChange={setAppearance} locked={!!session?.pending_review || !!session?.committed_pages?.length || status === 'Generating options…'} />
    <ComplianceBanner sessionId={session?.session_id} snapshot={session} onDecision={refresh} />
    {session && appearance && <>
      {session.pending_review ? <OptionComparison key={session.pending_review.page_id} result={sessionApi.browserPage(session.session_id, session.pending_review)} appearance={appearance} context={session.context} totalPages={(session.committed_pages ?? []).length + 1} busy={!!status} onConfirm={choice => { void run('Saving selection…', async () => {
        await sessionApi.select(session.session_id, session.pending_review!.page_id, choice);
        await refresh();
      }); }} /> : <PageComposer key={session.current_page_index} pageNumber={session.current_page_index} busy={!!status} onGenerate={async (text, files) => { await run('Generating options…', async () => {
        const assets = files.length ? (await sessionApi.upload(session.session_id, files)).assets : [];
        const page = await sessionApi.generate(session.session_id, text, assets.map(asset => asset.asset_id));
        setSession({ ...session, pending_review: page });
      }); }} />}
      <DraftViewer sessionId={session.session_id} pages={(session.committed_pages ?? []).map(page => sessionApi.browserPage(session.session_id, page))} context={session.context} appearance={appearance} />
    </>}
  </main>;
}
