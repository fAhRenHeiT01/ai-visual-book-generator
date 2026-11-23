'use client';
import { Component, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import type { components } from '../../types/generated';
import { sessionApi } from '../../lib/sessionApi';
import { BookSetup } from '../setup/BookSetup';
import { ThemeControls } from '../setup/ThemeControls';
import { ComplianceBanner } from '../compliance/ComplianceBanner';
import { DraftViewer } from '../draft/DraftViewer';
import { PageComposer } from './PageComposer';
import { OptionComparison } from './OptionComparison';
import { DebugPanel } from './DebugPanel';
type S = components['schemas'];
class ReviewBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <div className="studio-controls" role="alert">The saved review could not be displayed. <button onClick={() => this.setState({ failed: false })}>Reopen saved review</button></div>;
    return this.props.children;
  }
}
export function Studio({ sessionId }: { sessionId?: string }) {
  const [session, setSession] = useState<S['SessionSnapshot']>();
  const [appearance, setAppearance] = useState<S['AppearanceResponse']>();
  const [debug, setDebug] = useState<S['DebugSnapshot']>();
  const [status, setStatus] = useState(sessionId ? 'Loading book…' : '');
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const locked = useRef(false);
  useEffect(() => {
    if (!sessionId) return;
    let active = true;
    Promise.all([sessionApi.load(sessionId), sessionApi.appearance(sessionId)]).then(async ([snapshot, theme]) => {
      const checkpoint = snapshot.debug_enabled ? await sessionApi.debug(sessionId) : undefined;
      if (active) { setSession(snapshot); setAppearance(theme); setDebug(checkpoint); setStatus(''); setError(''); }
    }).catch((cause: Error) => { if (active) { setError(cause.message); setStatus(''); } });
    return () => { active = false; };
  }, [sessionId, retry]);
  const refresh = useCallback(async () => {
    if (session) {
      const snapshot = await sessionApi.load(session.session_id);
      const checkpoint = snapshot.debug_enabled ? await sessionApi.debug(session.session_id) : undefined;
      setSession(snapshot); setDebug(checkpoint);
    }
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
  function debugStep(response?: string) {
    if (!session || !debug?.checkpoint_id) return;
    void run('Advancing graph…', async () => {
      const checkpoint = await sessionApi.debugStep(session.session_id, debug.checkpoint_id!, response);
      setDebug(checkpoint);
      setSession(await sessionApi.load(session.session_id));
    });
  }
  const debugging = debug?.status === 'paused';
  const debugReview = debugging && debug.interrupts?.[0]?.event === 'review';
  return <main className="studio">
    <header className="studio-controls studio-header"><a href="/">Visual Book Generator</a><h1>{session?.context.title || 'Visual Book Generator'}</h1>{session && <p>Saved automatically · <a href={`/sessions/${session.session_id}`}>Reopen this book</a></p>}</header>
    {status && <p className="studio-controls" role="status">{status}</p>}
    {error && <div className="studio-controls" role="alert">{error}{sessionId && !session && <button onClick={() => { setStatus('Loading book…'); setRetry(value => value + 1); }}>Retry loading book</button>}</div>}
    {!session && !sessionId && <div className="studio-controls"><BookSetup busy={!!status} onCreate={context => { void run('Creating book…', async () => {
      const created = await sessionApi.create(context);
      const theme = await sessionApi.appearance(created.session_id);
      const checkpoint = created.debug_enabled ? await sessionApi.debug(created.session_id) : undefined;
      setSession(created); setAppearance(theme); setDebug(checkpoint); window.history.pushState(null, '', `/sessions/${created.session_id}`);
    }); }} /></div>}
    <ThemeControls sessionId={session?.session_id} appearance={appearance} onAppearanceChange={setAppearance} locked={!!session?.debug_active || !!session?.pending_review || !!session?.committed_pages?.length || status === 'Generating options…'} />
    <ComplianceBanner sessionId={session?.session_id} snapshot={session} onDecision={refresh} />
    {session && appearance && <>
      {session.debug_enabled && debug && <DebugPanel key={debug.checkpoint_id} snapshot={{ ...debug, appearance }} busy={!!status} onStep={debugStep} onReload={() => { void run('Reloading checkpoint…', refresh); }} />}
      {debugging && !debugReview ? null : session.pending_review ? <ReviewBoundary key={session.pending_review.page_id}><OptionComparison key={session.pending_review.page_id} result={sessionApi.browserPage(session.session_id, session.pending_review)} appearance={appearance} context={session.context} totalPages={(session.committed_pages ?? []).length + 1} busy={!!status} onConfirm={choice => { if (debugReview) { debugStep(choice); return; } void run('Saving selection…', async () => {
        await sessionApi.select(session.session_id, session.pending_review!.page_id, choice);
        await refresh();
      }); }} /></ReviewBoundary> : <PageComposer key={session.active_page?.page_id ?? session.current_page_index} activePage={session.active_page} pageNumber={session.current_page_index} busy={!!status} onGenerate={async (text, files, revise) => { await run('Generating options…', async () => {
        const assetIds = files.length ? (await sessionApi.upload(session.session_id, files)).assets.map(asset => asset.asset_id) : session.active_page?.asset_ids ?? [];
        if (session.debug_enabled) {
          setDebug(await sessionApi.debugStart(session.session_id, text, assetIds));
          setSession(await sessionApi.load(session.session_id));
          return;
        }
        const activePage = { page_id: session.active_page?.page_id ?? crypto.randomUUID(), page_number: session.current_page_index, text, asset_ids: assetIds };
        sessionApi.remember(session.session_id, activePage);
        setSession({ ...session, active_page: activePage });
        const page = await sessionApi.generate(session.session_id, text, assetIds, activePage.page_id, revise);
        setSession({ ...session, active_page: activePage, pending_review: page });
      }); }} />}
      <DraftViewer sessionId={session.session_id} pages={(session.committed_pages ?? []).map(page => sessionApi.browserPage(session.session_id, page))} context={session.context} appearance={appearance} />
    </>}
  </main>;
}
